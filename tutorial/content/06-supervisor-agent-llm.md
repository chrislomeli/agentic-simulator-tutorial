# Session 6: The Supervisor Agent (LLM Mode)

---

## What you're doing and why

Session 5 proved the multi-agent coordination works: fan-out, parallel execution, reducer, stub assess, stub decide. Now you add the LLM — but with a twist. The supervisor has two distinct reasoning tasks that need *separate* loops:

1. **Assess** — examine findings across all clusters, look for correlations, produce a situation summary
2. **Decide** — based on the assessment, choose what actuator commands to issue

These are separate because they have different inputs, different tools, and different outputs. A single ReAct loop trying to do both tends to collapse the two phases together and produce worse decisions than two focused loops.

The Send API fan-out and the `aggregate_findings_reducer` stay exactly the same as Session 5.

---

## Setup

This session builds on Session 5. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/world/ src/domains/ src/sensors/ src/transport/ src/bridge/ src/resources/ src/config.py tests/
git checkout tutorial/main -- src/agents/ src/tools/sensor_tools.py
pytest tests/agents/test_supervisor.py -q   # should pass before you start
```

---

## Rubric coverage

| Skill | Level | Where in this session |
|-------|-------|-----------------------|
| Cycles / loops | mid-level | Two independent ReAct loops: assess and decide |
| Tool definition — @tool decorator | foundational | `supervisor_tools.py` — 4 tools for cross-cluster analysis |
| ToolNode + bind_tools | foundational | `ToolNode(all_tools)` for both assess and decide phases |
| Structured output tools | mid-level | `_parse_assessment` and `_parse_commands` extract JSON from LLM responses |

---

## What you're building

| File | Change | What it contains |
|------|--------|-----------------|
| `src/tools/supervisor_tools.py` | **Create** | 4 `@tool` functions for cross-cluster finding analysis: `get_all_findings`, `get_findings_by_cluster`, `get_finding_summary`, `check_cross_cluster` |
| `src/agents/supervisor/graph.py` | **Modify** | Add LLM mode: `_make_assess_llm_node`, `_make_decide_llm_node`, `route_after_assess_llm`, `route_after_decide_llm`, `_parse_assessment`, `_parse_commands` |

When you're done:

```bash
pytest tests/agents/test_supervisor.py tests/tools/ -v
```

---

## Concept Box: Dual ReAct loops and tool state lifecycle

> **Read this before the code.** This session has two ReAct loops in the same graph. Understanding the wiring and the tool state lifecycle prevents the most common bugs.

### Why two loops, not one

A single ReAct loop trying to both assess *and* decide tends to collapse the phases: the LLM starts deciding before it finishes assessing. Two focused loops produce better results because each has a **different system prompt, different mental frame, and different output schema**.

```
START → fan_out → run_cluster_agent (×N)
         ↓
    assess_situation_llm ←──→ assess_tool_node    (loop 1: "what is happening?")
         ↓
    parse_assessment
         ↓
    decide_actions_llm ←──→ decide_tool_node      (loop 2: "what should we do?")
         ↓
    parse_commands → dispatch_commands → END
```

Both loops share the **same ToolNode tool set** but have **different system prompts**. The assess loop's prompt says "examine findings, produce a summary." The decide loop's prompt says "given the summary, produce commands."

### Tool state lifecycle

The supervisor tools read from a module-level `_state` holder (same pattern as sensor tools in Session 03). The lifecycle matters:

1. **Before assess loop:** `set_supervisor_tool_state(findings, cluster_ids, ...)` loads all findings into the holder
2. **During assess loop:** tools read from `_state` — `get_all_findings()`, `check_cross_cluster()`, etc.
3. **Between loops:** tool state stays loaded (tools are still valid for the decide phase)
4. **After decide loop:** `clear_supervisor_tool_state()` cleans up

If you forget step 1, all tools return empty results. If you clear too early (between loops), the decide phase has no data.

### How the graph builder wires it

```python
# Assess phase
builder.add_node("assess_situation", assess_llm_node)
builder.add_node("assess_tool_node", ToolNode(all_tools))
builder.add_node("parse_assessment", _parse_assessment)

builder.add_conditional_edges("assess_situation", route_after_assess_llm)
builder.add_edge("assess_tool_node", "assess_situation")  # assess loop
builder.add_edge("parse_assessment", "decide_actions")

# Decide phase
builder.add_node("decide_actions", decide_llm_node)
builder.add_node("decide_tool_node", ToolNode(all_tools))
builder.add_node("parse_commands", _parse_commands)

builder.add_conditional_edges("decide_actions", route_after_decide_llm)
builder.add_edge("decide_tool_node", "decide_actions")   # decide loop
builder.add_conditional_edges("parse_commands", route_after_decide)
```

**Note:** `assess_tool_node` and `decide_tool_node` are separate ToolNode instances with the same tool set. They need separate names because LangGraph requires unique node names.

### What can go wrong

| Symptom | Cause | Fix |
|---------|-------|-----|
| Assess tools return empty | `set_supervisor_tool_state()` not called | Call it in the assess LLM node before `llm.invoke()` |
| Decide tools return empty | Tool state cleared between loops | Only call `clear_supervisor_tool_state()` in `_parse_commands`, not in `_parse_assessment` |
| LLM produces assessment in decide phase | Messages carry over | The decide node checks `has_decide_prompt` and replaces messages with fresh system+user if needed |
| Both loops use same system prompt | Copy-paste error | Assess uses `ASSESS_SYSTEM_PROMPT`, decide uses `DECIDE_SYSTEM_PROMPT` — different focus |

---

## Why two separate loops

The supervisor has two distinct responsibilities:

**1. Assess the situation** — look at findings from all clusters, correlate them, distinguish real threats from noise, and produce a summary of what's happening.

**2. Decide what to do** — based on the assessment, choose which actuator commands to issue (alerts, escalations, notifications, etc.).

These are separate reasoning tasks with different tools and different outputs. The assess loop produces a `situation_summary` string. The decide loop produces a list of `ActuatorCommand` objects.

Session 5 had two stub nodes (`assess_situation` and `decide_actions`). This session replaces each with its own LLM + ToolNode ReAct loop. The LLM can call tools during assessment to examine findings, then call tools during decision-making to review the assessment and choose actions.

---

## The four supervisor tools

Supervisor tools give the LLM structured access to aggregated findings:

### 1. `get_all_findings` — fetch all findings

```python
@tool
def get_all_findings(limit: int = 50) -> List[Dict[str, Any]]:
    """Return all cluster findings from the current supervisor execution.
    
    Args:
        limit: Maximum number of findings to return (default 50).
    
    Returns:
        List of finding dicts with finding_id, cluster_id, anomaly_type,
        affected_sensors, confidence, and summary.
    """
    findings = _state.findings[:limit]
    return [
        {
            "finding_id": f["finding_id"],
            "cluster_id": f["cluster_id"],
            "anomaly_type": f["anomaly_type"],
            "affected_sensors": f["affected_sensors"],
            "confidence": f["confidence"],
            "summary": f["summary"],
        }
        for f in findings
    ]
```

The LLM calls this to see all findings at once.

### 2. `get_findings_by_cluster` — filter by cluster

```python
@tool
def get_findings_by_cluster(cluster_id: str) -> List[Dict[str, Any]]:
    """Return findings for a specific cluster."""
    findings = [f for f in _state.findings if f["cluster_id"] == cluster_id]
    return [
        {
            "finding_id": f["finding_id"],
            "cluster_id": f["cluster_id"],
            "anomaly_type": f["anomaly_type"],
            "affected_sensors": f["affected_sensors"],
            "confidence": f["confidence"],
            "summary": f["summary"],
        }
        for f in findings
    ]
```

The LLM calls this to zoom in on one cluster: "what did cluster-north report?"

### 3. `get_finding_summary` — aggregate stats

```python
@tool
def get_finding_summary() -> Dict[str, Any]:
    """Compute aggregate statistics across all cluster findings.
    
    Returns:
        Dict with:
          - total_findings: total count
          - by_cluster: dict mapping cluster_id to finding count
          - by_type: dict mapping anomaly_type to finding count
          - avg_confidence: mean confidence across all findings
          - high_confidence_count: findings with confidence >= 0.7
          - affected_clusters: list of cluster IDs with findings
    """
    findings = _state.findings
    by_cluster = Counter(f["cluster_id"] for f in findings)
    by_type = Counter(f["anomaly_type"] for f in findings)
    confs = [f["confidence"] for f in findings]
    
    return {
        "total_findings": len(findings),
        "by_cluster": dict(by_cluster),
        "by_type": dict(by_type),
        "avg_confidence": round(sum(confs) / len(confs), 3),
        "high_confidence_count": sum(1 for c in confs if c >= 0.7),
        "affected_clusters": list(by_cluster.keys()),
    }
```

The LLM calls this to get a high-level overview: "how many findings? which types? which clusters?"

### 4. `check_cross_cluster` — detect correlations

```python
@tool
def check_cross_cluster(anomaly_type: Optional[str] = None) -> Dict[str, Any]:
    """Detect correlated anomalies across multiple clusters.
    
    Looks for the same anomaly_type appearing in multiple clusters,
    which may indicate a large-scale event (e.g. a fire front crossing
    cluster boundaries).
    
    Returns:
        Dict with:
          - correlated: True if the same anomaly type appears in 2+ clusters
          - correlations: list of dicts with anomaly_type, clusters, count
    """
    # Group by anomaly_type → set of cluster_ids
    type_to_clusters: Dict[str, set] = {}
    for f in findings:
        type_to_clusters.setdefault(f["anomaly_type"], set()).add(f["cluster_id"])
    
    correlations = []
    for atype, clusters in type_to_clusters.items():
        if len(clusters) >= 2:
            correlations.append({
                "anomaly_type": atype,
                "clusters": sorted(clusters),
                "cluster_count": len(clusters),
            })
    
    return {
        "correlated": len(correlations) > 0,
        "correlations": correlations,
    }
```

The LLM calls this to check: "is the same anomaly happening in multiple clusters?" This is the key cross-cluster correlation tool.

**Module-level state holder:** Same pattern as sensor tools and cluster tools. The supervisor graph calls `set_supervisor_tool_state(findings, cluster_ids, resource_inventory, fire_behavior_summary)` before the LLM loop, loading all context into `_state`. Tools read from `_state`. After the loop, `clear_supervisor_tool_state()` cleans up.

---

## The assess loop: situation assessment

The assess loop has its own system prompt, LLM node, tool node, and parse node:

**System prompt:**

```python
ASSESS_SYSTEM_PROMPT = """You are a wildfire monitoring supervisor agent.

You have received anomaly findings from {cluster_count} cluster agent(s):
{cluster_list}

Your job is to assess the overall situation by:
  1. Using tools to examine the findings in detail
  2. Looking for cross-cluster correlations (same anomaly in multiple clusters)
  3. Distinguishing real threats from noise
  4. Writing a concise situation summary

After your analysis, respond with a JSON object (and nothing else):
{{
  "severity": "critical" | "high" | "moderate" | "low" | "none",
  "situation_summary": "Brief description of what is happening",
  "correlated_events": true/false,
  "affected_clusters": ["cluster-id-1", ...],
  "recommended_actions": ["action description", ...]
}}
"""
```

The LLM is told it's a supervisor, given the cluster count and list, and instructed to use tools to examine findings and produce a structured JSON assessment.

**LLM node factory:**

```python
def _make_assess_llm_node(
    llm_with_tools: BaseChatModel,
    store: Optional[BaseStore] = None,
    resource_inventory: Optional[ResourceInventory] = None,
    fire_behavior_summary: Optional[Dict] = None,
):
    def assess_situation_llm(state: SupervisorState) -> dict:
        findings = state.get("cluster_findings", [])
        cluster_ids = state.get("active_cluster_ids", [])
        messages = state.get("messages", [])
        
        # Load tool state
        set_supervisor_tool_state(
            findings, cluster_ids, resource_inventory, fire_behavior_summary
        )
        
        # Build initial messages on first call
        if not messages:
            sys_msg = SystemMessage(
                content=ASSESS_SYSTEM_PROMPT.format(
                    cluster_count=len(cluster_ids),
                    cluster_list=", ".join(cluster_ids),
                )
            )
            # Summarize findings for the LLM (last 30 findings)
            finding_lines = []
            for f in findings[:30]:
                finding_lines.append(
                    f"  [{f['anomaly_type']}] cluster={f['cluster_id']} "
                    f"conf={f['confidence']:.2f} — {f['summary'][:80]}"
                )
            
            # Load past incidents from store
            past_lines = []
            if store is not None:
                for cid in cluster_ids:
                    items = store.search(("incidents", cid))
                    for item in items[-10:]:  # last 10 per cluster
                        v = item.value
                        past_lines.append(
                            f"  [PAST][{v.get('cluster_id', cid)}] "
                            f"{v.get('anomaly_type', '?')} "
                            f"conf={v.get('confidence', 0):.2f} — "
                            f"{v.get('summary', '')[:80]}"
                        )
            
            user_content = (
                f"Active clusters: {', '.join(cluster_ids)}\n"
                f"Total findings: {len(findings)}\n"
                f"Findings:\n" + "\n".join(finding_lines)
            )
            if past_lines:
                user_content += "\n\nPast incidents (from store):\n" + "\n".join(past_lines)
            
            user_msg = HumanMessage(content=user_content)
            messages = [sys_msg, user_msg]
        
        response = llm_with_tools.invoke(messages)
        
        return {
            "messages": [response],
            "status": "assessing",
        }
    
    return assess_situation_llm
```

The factory:
- Loads tool state before invoking the LLM
- Builds initial messages with a summary of findings (last 30) and past incidents from the Store (last 10 per cluster)
- Invokes the LLM with tools bound
- Returns the AIMessage

**Router:**

```python
def route_after_assess_llm(
    state: SupervisorState,
) -> Literal["assess_tool_node", "parse_assessment", "__end__"]:
    if state.get("status") == "error":
        return "__end__"
    
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "assess_tool_node"  # LLM wants to call tools
    
    return "parse_assessment"  # LLM is done, parse the JSON
```

If the LLM produces `tool_calls`, route to `assess_tool_node`. Otherwise, route to `parse_assessment`.

**Parse node:**

```python
def _parse_assessment(state: SupervisorState) -> dict:
    messages = state.get("messages", [])
    
    # Find the last AI message with content
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            last_ai = msg
            break
    
    if last_ai is None:
        return {
            "situation_summary": "[No assessment produced]",
            "status": "deciding",
        }
    
    # Parse JSON
    try:
        content = last_ai.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        parsed = json.loads(content)
    except (json.JSONDecodeError, Exception):
        parsed = {
            "severity": "unknown",
            "situation_summary": last_ai.content[:300],
        }
    
    summary = parsed.get("situation_summary", last_ai.content[:300])
    
    return {
        "situation_summary": summary,
        "status": "deciding",
    }
```

Extracts the JSON from the last AI message, handles markdown code fences, falls back to raw text if parsing fails, and sets `situation_summary` and `status="deciding"`.

---

## The decide loop: action decision-making

The decide loop has its own system prompt, LLM node, tool node, and parse node:

**System prompt:**

```python
DECIDE_SYSTEM_PROMPT = """You are a wildfire monitoring supervisor making action decisions.

Situation summary: {situation_summary}

Based on the situation assessment, decide what actuator commands to issue.
Available command types:
  - "alert": Send alerts to operators
  - "notify": Send async notification via Slack/PagerDuty
  - "escalate": Escalate to higher authority
  - "suppress": Suppress a known false positive
  - "drone_task": Deploy a drone for closer inspection

Use the available tools to review findings before deciding.

Respond with a JSON object (and nothing else):
{{
  "commands": [
    {{
      "command_type": "alert" | "notify" | "escalate" | "suppress" | "drone_task",
      "cluster_id": "target-cluster-id",
      "priority": 1-5,
      "payload": {{ ... }}
    }}
  ],
  "reasoning": "Brief explanation of why these commands were chosen"
}}

If no action is needed, return: {{"commands": [], "reasoning": "No action needed because ..."}}
"""
```

The LLM is given the situation summary from the assess phase and instructed to decide what commands to issue.

**LLM node factory:**

```python
def _make_decide_llm_node(
    llm_with_tools: BaseChatModel,
    resource_inventory: Optional[ResourceInventory] = None,
    fire_behavior_summary: Optional[Dict] = None,
):
    def decide_actions_llm(state: SupervisorState) -> dict:
        findings = state.get("cluster_findings", [])
        cluster_ids = state.get("active_cluster_ids", [])
        situation = state.get("situation_summary", "No assessment available")
        messages = state.get("messages", [])
        
        # Reload tool state for the decide phase
        set_supervisor_tool_state(
            findings, cluster_ids, resource_inventory, fire_behavior_summary
        )
        
        # Check if we need to add the decide prompt
        has_decide_prompt = any(
            isinstance(m, SystemMessage)
            and "action decisions" in (m.content or "")
            for m in messages
        )
        if not has_decide_prompt:
            sys_msg = SystemMessage(
                content=DECIDE_SYSTEM_PROMPT.format(situation_summary=situation)
            )
            user_msg = HumanMessage(
                content=f"Situation: {situation}\n\nDecide what actions to take."
            )
            messages = [sys_msg, user_msg]
        
        response = llm_with_tools.invoke(messages)
        
        return {
            "messages": [response],
            "status": "deciding",
        }
    
    return decide_actions_llm
```

The factory:
- Reloads tool state (tools are still available from the assess phase)
- Checks if the decide prompt is already in messages (to avoid duplicating it during the ReAct loop)
- Builds initial messages with the situation summary
- Invokes the LLM
- Returns the AIMessage

**Router:**

```python
def route_after_decide_llm(
    state: SupervisorState,
) -> Literal["decide_tool_node", "parse_commands", "__end__"]:
    if state.get("status") == "error":
        return "__end__"
    
    messages = state.get("messages", [])
    if messages:
        last = messages[-1]
        if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
            return "decide_tool_node"  # LLM wants to call tools
    
    return "parse_commands"  # LLM is done, parse the JSON
```

Same pattern as the assess router.

**Parse node:**

```python
def _parse_commands(state: SupervisorState) -> dict:
    messages = state.get("messages", [])
    
    clear_supervisor_tool_state()  # Clean up
    
    # Find the last AI message with content
    last_ai = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            last_ai = msg
            break
    
    if last_ai is None:
        return {
            "pending_commands": [],
            "status": "dispatching",
        }
    
    # Parse JSON
    try:
        content = last_ai.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        parsed = json.loads(content)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Supervisor: failed to parse LLM decision: %s", exc)
        return {
            "pending_commands": [],
            "status": "dispatching",
        }
    
    # Convert JSON commands to ActuatorCommand objects
    commands = []
    for cmd in parsed.get("commands", []):
        try:
            commands.append(
                ActuatorCommand.create(
                    command_type=cmd["command_type"],
                    source_agent="supervisor",
                    cluster_id=cmd.get("cluster_id", "unknown"),
                    payload=cmd.get("payload", {}),
                    priority=cmd.get("priority", 3),
                )
            )
        except (KeyError, Exception) as exc:
            logger.warning("Supervisor: skipping invalid command: %s", exc)
    
    return {
        "pending_commands": commands,
        "status": "dispatching",
    }
```

Extracts the JSON, converts each command dict into an `ActuatorCommand` object, and sets `pending_commands` and `status="dispatching"`.

---

## Tool composition: supervisor + resource + fire behavior

When you build the supervisor graph in LLM mode, you can optionally provide a `ResourceInventory` and a `fire_behavior_summary`:

```python
graph = build_supervisor_graph(
    llm=llm,
    resource_inventory=resource_inventory,      # Optional
    fire_behavior_summary=fire_behavior_summary, # Optional
)
```

If provided, the supervisor's tool set expands:

```python
all_tools = SUPERVISOR_TOOLS  # 4 tools
if resource_inventory is not None:
    all_tools = all_tools + RESOURCE_TOOLS  # +4 tools = 8 total
if fire_behavior_summary is not None:
    all_tools = all_tools + FIRE_BEHAVIOR_TOOLS  # +N tools
```

The LLM gets all tools bound. During the assess and decide loops, it can call supervisor tools to examine findings, resource tools to check preparedness, and fire behavior tools to assess fire intensity.

This is **tool composition** — different tool sets combine based on what context is available. Session 11 will introduce resource tools. Fire behavior tools are covered in the Rothermel implementation (future sessions).

---

## Running it

Here's a complete script that invokes the supervisor in LLM mode:

```python
from langchain_openai import ChatOpenAI
from agents.supervisor.graph import build_supervisor_graph

# Build the graph (LLM mode)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
graph = build_supervisor_graph(llm=llm)

# Invoke with 2 active clusters
result = graph.invoke({
    "active_cluster_ids": ["cluster-north", "cluster-south"],
    "cluster_findings": [],
    "messages": [],
    "pending_commands": [],
    "situation_summary": None,
    "status": "idle",
    "error_message": None,
})

# Inspect the result
print(f"Status: {result['status']}")
print(f"Findings aggregated: {len(result['cluster_findings'])}")
print(f"\nSituation Summary:")
print(result['situation_summary'])
print(f"\nCommands: {len(result['pending_commands'])}")
for i, cmd in enumerate(result["pending_commands"], 1):
    print(f"{i}. [{cmd.command_type}] → {cmd.cluster_id} (priority={cmd.priority})")
    print(f"   Payload: {cmd.payload}")
```

**Expected output (LLM mode):**

```
Status: complete
Findings aggregated: 2

Situation Summary:
Two stub findings detected from cluster-north and cluster-south. Both are placeholder findings with low confidence (0.5), indicating the cluster agents are running in stub mode. No real anomalies detected. No cross-cluster correlation. Situation is normal.

Commands: 0
```

The LLM:
1. Called `get_finding_summary()` to see the overview
2. Called `check_cross_cluster()` to check for correlations
3. Produced a JSON assessment with `severity="none"` and a summary explaining the stub findings
4. Decided no commands are needed (stub findings aren't actionable)

With real findings (from LLM-powered cluster agents), the output would be:

```
Situation Summary:
Critical situation detected. Temperature threshold breaches in cluster-north (2 sensors, confidence 0.85) correlated with smoke detection in cluster-south (1 sensor, confidence 0.90). Cross-cluster correlation suggests a fire front moving from north to south. Immediate action required.

Commands: 2
1. [alert] → cluster-north (priority=1)
   Payload: {'message': 'Temperature spike detected, possible fire activity', 'recipients': ['ops-team']}
2. [escalate] → cluster-south (priority=2)
   Payload: {'reason': 'Cross-cluster fire front detected', 'urgency': 'high'}
```

---

## What you learned: Supervisor LLM patterns

This session introduced the supervisor-specific LLM patterns:

**1. Two separate ReAct loops** — assess and decide are independent cycles with different system prompts, tools, and outputs.

**2. Tool composition** — supervisor tools + resource tools + fire behavior tools = one unified tool set for the LLM.

**3. Node factories with context** — `_make_assess_llm_node(llm, store, resource_inventory, fire_behavior_summary)` injects context into the closure.

**4. Parse nodes with fallbacks** — `_parse_assessment` and `_parse_commands` handle JSON extraction with graceful degradation.

**5. Store integration in prompts** — past incidents from the Store are included in the user message so the LLM can reason about historical patterns.

**6. Structured output** — the LLM must produce valid JSON that maps to `ActuatorCommand` objects.

The supervisor is the decision-maker. Cluster agents report findings. The supervisor correlates, assesses, and decides. This is the multi-agent hierarchy.

---

## Checkpoint

```bash
pytest tests/agents/test_supervisor.py tests/tools/ -v
```

Key tests to look for:
- `test_supervisor_tools` — all 4 tools return correct data shapes
- `test_invoke_llm_mode` — supervisor runs with a mock LLM
- `test_invoke_with_store_reads_past_incidents` — Store is read correctly during assess

---

## Key files

- `src/agents/supervisor/graph.py` — `_make_assess_llm_node`, `_make_decide_llm_node`, `route_after_assess_llm`, `route_after_decide_llm`, `_parse_assessment`, `_parse_commands`
- `src/tools/supervisor_tools.py` — 4 supervisor tools: `get_all_findings`, `get_findings_by_cluster`, `get_finding_summary`, `check_cross_cluster`
- `src/actuators/base.py` — `ActuatorCommand` model

---

*Next: Session 7 introduces resource tools — preparedness assets on the grid. Resources are queryable world state (firetrucks, hospitals, helicopters) that the supervisor can examine to assess readiness. Resource tools will be added to the supervisor's tool set so the LLM can answer "are we prepared for this situation?"*
