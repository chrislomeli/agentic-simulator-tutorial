# Session 9: Scenario Knobs — Resilience Testing

---

## What you're doing and why

Session 8 proved the complete pipeline works under normal conditions. This session breaks it on purpose.

You'll run the same pipeline four times with the same random seed (same fire conditions) but different degradation settings — fewer sensors, disabled resources — and compare the supervisor's assessments. The goal isn't to see if the agent predicts fires. It's to see if it correctly identifies *gaps*: "cluster-south is missing water suppression capacity."

This framing matters. An agent that says "fire potential is high given current conditions" is always defensible. An agent that says "cluster-south has 0 engines available" is stating a verifiable fact. The evaluation in Session 10 measures both.

---

## Setup

This session builds on Session 8. If you're continuing, activate your environment and move on.

If you're starting fresh:

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[llm]" --group dev
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
git checkout tutorial/main -- src/ tests/
pytest tests/ -q   # everything should pass before you start
```

---

## Rubric coverage

This session exercises the system rather than introducing new LangGraph patterns. The resilience testing pattern itself — controlled degradation + comparison — is the skill.

---

## What you're building

No new source files. This session uses the scenario knobs already built into `ResourceInventory` and `SensorInventory`.

---

## Why preparedness, not prediction

The agent isn't trying to predict whether a fire will happen. That's a binary win/lose with no training data behind it. Instead, the agent assesses:

**1. Fire potential** — based on sensor conditions (low humidity, high temperature, wind)

**2. Resource readiness** — whether assets are positioned and available to respond

This framing is:
- **Always defensible** — "high fire potential due to low humidity" is correct whether or not a fire starts
- **Demo-safe** — false positives are caution, not errors (exactly what preparedness should produce)
- **Useful** — the value is in the gap analysis ("cluster-south lacks helicopter coverage"), not the prediction
- **Evaluable** — we can verify gap detection against actual resource state

This session demonstrates that preparedness assessment remains valuable even when conditions degrade.

---

## The scenario knobs

You have experimental controls for both sensors and resources:

### Sensor knobs

```python
from world.sensor_inventory import SensorInventory

inventory = SensorInventory(grid_rows=10, grid_cols=10)
# ... register sensors ...

# Remove 50% of sensors randomly
inventory.thin_sensors(keep_fraction=0.5)

# Inject intermittent failures (30% dropout rate)
inventory.inject_failures(failure_rate=0.3)

# Reset to baseline
inventory.reset_all()
```

**Why this matters:** Fewer sensors = less visibility. The supervisor should express lower confidence or note blind spots.

### Resource knobs

```python
from resources.inventory import ResourceInventory

resources = ResourceInventory(grid_rows=10, grid_cols=10)
# ... register resources ...

# Remove 50% of engines (budget cuts)
resources.reduce_resources("engine", keep_fraction=0.5)

# Set 30% of engines to OUT_OF_SERVICE (equipment failure)
resources.disable_resources("engine", fraction=0.3)

# Reset to baseline
resources.reset_all()
```

**Why this matters:** Fewer resources = coverage gaps. The supervisor should identify which clusters are under-resourced and recommend redeployment or escalation.

---

## The experiment matrix

We'll run 4 scenarios with the same random seed (same fire conditions, same sensor readings):

| Scenario | Sensors | Resources | What supervisor should assess |
|----------|---------|-----------|-------------------------------|
| **Baseline** | 100% | 100% | Fire potential noted, resources adequate |
| **Blind spots** | 50% thinned | 100% | Reduced confidence, may note limited visibility |
| **Under-resourced** | 100% | 50% engines disabled | Fire potential clear, coverage gaps identified |
| **Worst case** | 50% thinned | 50% engines disabled | Limited visibility AND coverage gaps — should escalate |

Each scenario runs the same pipeline (Session 13) but with different knob settings.

---

## Building the experiment

Here's the complete experiment runner:

```python
import asyncio
import random
from domains.wildfire import create_full_wildfire_scenario
from domains.wildfire.sensors import TemperatureSensor, SmokeSensor
from sensors import SensorPublisher
from transport import SensorEventQueue
from bridge.consumer import EventBridgeConsumer
from agents.cluster.graph import build_cluster_agent_graph
from agents.supervisor.graph import build_supervisor_graph
from langgraph.store.memory import InMemoryStore

async def run_scenario(label, sensor_thin=1.0, resource_disable_frac=0.0):
    """
    Run the full pipeline with degradation knobs.
    
    Args:
        label: Scenario name for output
        sensor_thin: Fraction of sensors to keep (1.0 = all, 0.5 = 50%)
        resource_disable_frac: Fraction of engines to disable (0.0 = none, 0.5 = 50%)
    """
    # Same random seed = same fire conditions
    random.seed(42)
    
    # Create scenario
    engine, resources = create_full_wildfire_scenario()
    
    # Apply resource degradation
    if resource_disable_frac > 0:
        disabled = resources.disable_resources("engine", fraction=resource_disable_frac)
        print(f"  Disabled {len(disabled)} engines: {disabled}")
    
    # Create sensors
    queue = SensorEventQueue()
    sensors = [
        TemperatureSensor(
            source_id="temp-n1", cluster_id="cluster-north",
            engine=engine, grid_row=3, grid_col=3,
        ),
        SmokeSensor(
            source_id="smoke-s1", cluster_id="cluster-south",
            engine=engine, grid_row=7, grid_col=5,
        ),
    ]
    
    # Apply sensor degradation (thin would remove sensors, but we'll keep it simple)
    # For a real experiment, you'd use SensorInventory.thin_sensors()
    
    publisher = SensorPublisher(sensors=sensors, queue=queue, engine=engine)
    
    # Build agents
    store = InMemoryStore()
    cluster_graph = build_cluster_agent_graph(store=store)
    supervisor_graph = build_supervisor_graph(
        store=store,
        resource_inventory=resources,
    )
    
    # Run pipeline
    findings = []
    consumer = EventBridgeConsumer(
        queue=queue,
        agent_graph=cluster_graph,
        batch_size=5,
        on_finding=lambda f: findings.append(f),
    )
    
    await publisher.run(ticks=20)
    await consumer.run(max_events=queue.total_enqueued)
    
    # Run supervisor
    result = supervisor_graph.invoke({
        "active_cluster_ids": ["cluster-north", "cluster-south"],
        "cluster_findings": findings,
        "messages": [],
        "pending_commands": [],
        "situation_summary": None,
        "status": "idle",
        "error_message": None,
    })
    
    # Output results
    print(f"\n{'='*60}")
    print(f"SCENARIO: {label}")
    print(f"{'='*60}")
    print(f"\nPipeline stats:")
    print(f"  Events: {consumer.events_consumed}")
    print(f"  Findings: {len(findings)}")
    print(f"  Commands: {len(result['pending_commands'])}")
    
    print(f"\nSupervisor assessment:")
    print(f"  {result['situation_summary'][:200]}...")
    
    print(f"\nResource state (ground truth):")
    readiness = resources.readiness_summary()
    for rtype in ["crew", "engine", "dozer", "helicopter"]:
        if rtype in readiness["by_type"]:
            info = readiness["by_type"][rtype]
            print(f"  {rtype}: {info['available']}/{info['total']} available, "
                  f"{info['out_of_service']} out of service")
    
    print(f"\nCommands issued:")
    if result['pending_commands']:
        for i, cmd in enumerate(result['pending_commands'], 1):
            print(f"  {i}. [{cmd.command_type}] → {cmd.cluster_id} (priority={cmd.priority})")
    else:
        print(f"  (none)")
    
    # Reset for next scenario
    resources.reset_all()
    
    return result

# Run all scenarios
async def main():
    await run_scenario("Baseline — full preparedness")
    await run_scenario("50% engines disabled", resource_disable_frac=0.5)
    await run_scenario("All engines disabled", resource_disable_frac=1.0)

asyncio.run(main())
```

---

## Expected output

**Baseline scenario:**

```
============================================================
SCENARIO: Baseline — full preparedness
============================================================

Pipeline stats:
  Events: 40
  Findings: 2
  Commands: 0

Supervisor assessment:
  [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.

Resource state (ground truth):
  crew: 2/2 available, 0 out of service
  engine: 2/2 available, 0 out of service
  dozer: 1/1 available, 0 out of service
  helicopter: 1/1 available, 0 out of service

Commands issued:
  (none)
```

Baseline: All resources available, no gaps, no commands needed.

**50% engines disabled:**

```
============================================================
SCENARIO: 50% engines disabled
============================================================
  Disabled 1 engines: ['engine-south-1']

Pipeline stats:
  Events: 40
  Findings: 2
  Commands: 0

Supervisor assessment:
  [STUB] Received 2 finding(s) from 2 cluster(s). Store contains 0 past incident(s) across all clusters.

Resource state (ground truth):
  crew: 2/2 available, 0 out of service
  engine: 1/2 available, 1 out of service  ← GAP DETECTED
  dozer: 1/1 available, 0 out of service
  helicopter: 1/1 available, 0 out of service

Commands issued:
  (none)
```

With stub mode, the supervisor doesn't detect the gap (no LLM to query resources). But the ground truth shows the degradation.

**With LLM mode:**

If you run with an LLM:

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
cluster_graph = build_cluster_agent_graph(llm=llm, store=store)
supervisor_graph = build_supervisor_graph(
    llm=llm, store=store, resource_inventory=resources
)
```

Expected output changes:

```
Supervisor assessment:
  Temperature and smoke detected in cluster-south. Resource assessment: cluster-south has 1/2 engines out of service, reducing water capacity from 1000 to 500 gallons. Coverage gap identified. Recommend monitoring engine availability and considering redeployment from cluster-north if fire activity increases.

Commands issued:
  1. [alert] → cluster-south (priority=3)
     Payload: {'message': 'Engine capacity reduced, monitor closely', 'recipients': ['ops-team']}
```

The LLM:
1. Called `get_resource_summary()` and saw the degradation
2. Called `check_preparedness("cluster-south")` and identified the gap
3. Recommended monitoring and potential redeployment
4. Issued an alert command

**All engines disabled:**

```
Supervisor assessment:
  Critical resource gap: cluster-south has 0/2 engines available (both out of service). No water suppression capacity in this cluster. Immediate escalation required. Recommend redeploying helicopter from cluster-north or requesting mutual aid.

Commands issued:
  1. [escalate] → cluster-south (priority=1)
     Payload: {'reason': 'Zero engine capacity in cluster-south', 'urgency': 'high'}
  2. [notify] → cluster-south (priority=2)
     Payload: {'channel': 'pagerduty', 'message': 'Critical resource gap', 'urgency': 'high'}
```

The LLM escalated appropriately when all engines were disabled.

---

## What you learned: Resilience testing patterns

This session demonstrated controlled degradation experiments:

**1. Scenario knobs** — `reduce_resources()`, `disable_resources()` for resources; `thin_sensors()`, `inject_failures()` for sensors.

**2. Controlled experiments** — same random seed = same fire conditions, different preparedness levels.

**3. Assessment comparison** — compare supervisor summaries across scenarios to verify gap detection.

**4. Preparedness framing** — the value is in identifying gaps ("cluster-south lacks engines"), not predicting fires.

**5. Conservative bias** — false positives ("potential gap") are acceptable; missed gaps are not.

**6. Ground truth verification** — `readiness_summary()` provides the actual resource state for comparison.

The supervisor's preparedness assessment changes appropriately as conditions degrade. This demonstrates robustness and usefulness even when prediction is impossible.

---

## Checkpoint

Run the experiment matrix script from this session. Verify:
- Baseline: no gaps detected, no commands issued
- 50% engines disabled: gap appears in ground truth; LLM mode should detect it in the assessment
- All engines disabled: critical gap; LLM mode should escalate

In stub mode, the supervisor won't detect resource gaps (expected — no LLM to query resources). That's the motivation for Session 10's evaluation framework.

---

## Key files

- `src/resources/inventory.py` — `reduce_resources()`, `disable_resources()`, `reset_all()`
- `src/world/sensor_inventory.py` — `thin_sensors()`, `inject_failures()`
- `src/tools/resource_tools.py` — `check_preparedness()` (gap detection)

---

*Next: Session 10 evaluates the quality of preparedness assessments across scenarios. The question is: "Did the supervisor correctly identify gaps and recommend appropriate responses?" This is the evaluation framework for preparedness-based agents.*
