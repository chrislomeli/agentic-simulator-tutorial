## LangGraph Skills Rubric

Organized by topic. Levels: **foundational** (can explain), **mid-level** (has used in anger),
**advanced** (can reason about tradeoffs).

Coverage in testbed: **covered** / **partial** / **not yet**

---

### 1. Graph Primitives

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| StateGraph + TypedDict state | foundational | State is the single shared object; nodes read and return partial updates; reducers merge them | covered | Every subgraph — sensor cluster agent, supervisor |
| Nodes — functions vs runnables | foundational | Any callable works; runnables give streaming + observability for free | covered | All agent nodes |
| Edges — normal vs conditional | foundational | Conditional edge is a function on state; must return a node name or END | covered | Routing after anomaly classification |
| Reducers and Annotated state | mid-level | Default reducer overwrites; `add_messages` appends; custom reducers handle merging concurrent node outputs | covered | Merging readings from parallel sensor nodes |
| Compile + invoke / stream | foundational | `compile()` locks the graph; `stream()` yields `(node, state)` tuples for observability | covered | All graph entry points |

---

### 2. Control Flow

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| Cycles / loops | mid-level | Unlike DAGs — LangGraph supports cycles; used for retry, reflection, tool-use loops; needs explicit termination condition | covered | Agent retries ambiguous sensor reading before escalating |
| Parallel node execution (Send API) | mid-level | `Send()` dispatches dynamic fan-out; results merged by reducer; replaces static parallel edges for dynamic targets | covered | Supervisor fans out to N cluster agents simultaneously |
| Dynamic branching | mid-level | Branch target determined at runtime from state; can route to subgraphs or tool nodes | covered | Classify anomaly → route to wildfire / sensor-fault / weather branch |
| Recursion limit + error handling | advanced | `recursion_limit` in config; `GraphRecursionError`; design termination conditions deliberately | partial | Needs explicit scenario — runaway reflection loop |

**Note on Send API:** This is the skill that most separates "I've used LangGraph" from
"I understand LangGraph's execution model." The supervisor dispatching to N cluster agents
in parallel is the perfect natural exercise for it. Prioritize this.

---

### 3. Tools

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| Tool definition — `@tool` decorator | foundational | Docstring becomes the tool description; type hints become the schema; LLM sees both | covered | `get_sensor_history`, `query_world_state`, `dispatch_drone` |
| ToolNode + `bind_tools` | foundational | `ToolNode` executes tool calls from `AIMessage`; `bind_tools` attaches schema to LLM; standard ReAct loop | covered | Cluster agent tool loop |
| Tool errors + fallback | mid-level | `ToolNode` catches exceptions and returns `ToolMessage` with error; agent can retry or route differently | partial | Sensor timeout → error message → agent decides to use cached reading |
| Structured output tools | mid-level | `with_structured_output()` forces schema; use for actuator commands that must be validated before execution | covered | Actuator command schema — agent must produce valid `DroneCommand` |

---

### 4. Memory and Persistence

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| Checkpointers — in-memory vs Postgres | mid-level | `MemorySaver` for dev; `PostgresSaver` for prod; `thread_id` is the resume key; state survives crashes | covered | All persistent agents; crash recovery scenarios |
| Thread-level vs cross-thread memory | mid-level | Checkpointer = within a run; Store = shared across runs and agents; different access patterns | covered | Supervisor shares incident history across cluster agents via Store |
| Long-term memory with Store + embeddings | advanced | `InMemoryStore` / custom Store; semantic search over past decisions; pgvector integration | partial | Agent recalls similar past incidents — needs pgvector scenario |
| State schema evolution | advanced | Adding fields to TypedDict with defaults; migration strategy for persisted checkpoints | not yet | Not in testbed — separate exercise |

---

### 5. Multi-Agent

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| Subgraphs — compile and invoke | mid-level | Subgraph compiled separately; invoked as a node; has its own state schema; parent maps state in/out | covered | Each cluster agent is a compiled subgraph |
| State schema handoff between graphs | mid-level | Parent and subgraph states are different types; explicit mapping node transforms between them | covered | Supervisor state → ClusterAgentState mapping |
| Supervisor pattern | mid-level | Supervisor node routes to specialist agents; aggregates results; decides next action; owns termination | covered | Supervisor agent — core of the testbed |
| Agent handoff / swarm pattern | advanced | Agents pass control peer-to-peer via `Command`; no central supervisor; emergent coordination | partial | Cluster agents handing off to a specialist — needs explicit scenario |

---

### 6. Human-in-the-Loop

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| `interrupt()` — pause and resume | mid-level | `interrupt()` suspends graph at any node; state persisted; resume by invoking with same `thread_id` + new input | covered | High-confidence alert pauses for human approval before actuator fires |
| State editing before resume | advanced | Human can modify state before resuming; agent sees corrected state as if it had always been that way | partial | Human overrides agent's classification before escalation fires |
| Time travel / replay | advanced | `get_state_history()` returns all checkpoints; can re-invoke from any past checkpoint; fork execution | not yet | High value — replay incident from checkpoint to try different response |

**Note on `interrupt()` + Temporal:** This is the most impressive demo moment. Agent pauses
mid-execution waiting for human approval. Temporal keeps the workflow alive indefinitely.
Human clicks approve. Execution resumes. Any non-technical audience immediately understands
why this matters.

**Note on time travel:** Not yet in the testbed but high priority to add. The ability to
say "here's the incident — let me rewind to 10 minutes earlier and run a different response"
is genuinely jaw-dropping in a demo. It's a scenario script addition, not an architecture change.

---

### 7. Streaming and Observability

| Skill | Level | What an interviewer wants to hear | Testbed coverage | Where |
|-------|-------|----------------------------------|-----------------|-------|
| `stream_mode` — values vs updates vs debug | mid-level | `values` = full state each step; `updates` = delta only; `debug` = everything including LLM tokens | covered | Live dashboard showing agent reasoning as it happens |
| LangSmith tracing | mid-level | `LANGCHAIN_TRACING_V2=true`; traces every node, LLM call, tool call; critical for debugging multi-agent | covered | Always on — non-negotiable for debugging the testbed |
| Custom callbacks | advanced | `BaseCallbackHandler`; emit metrics, custom logs, or side effects at any node or LLM call | partial | Emit Kafka events from agent decisions — closes the feedback loop |

---

## Skills Gap Summary

### Well covered by the testbed naturally
Graph primitives, conditional routing, tool loop, ToolNode, structured output, checkpointing,
thread vs cross-thread memory, subgraphs, supervisor pattern, Send API fan-out,
interrupt() / human-in-the-loop, streaming, LangSmith tracing.

### Needs explicit scenario design
- Recursion limit / runaway loop handling
- Tool error fallback (sensor timeout scenario)
- Agent handoff / swarm pattern
- State editing before resume
- Long-term memory with pgvector similarity search
- Custom callbacks emitting to Kafka

### Not in testbed — separate exercises
- State schema evolution / migration
- Time travel (high value to add — it's a scenario, not an architecture change)

---

## Recommended Build Order

1. World engine — tick system, entity model, basic fire spread physics
2. Sensor base class + 2-3 sensor types, synthetic only
3. Kafka topics + canonical event schema
4. Single cluster agent as LangGraph graph with ToolNode loop
5. Temporal worker hosting the cluster agent as an Activity
6. Bridge consumer (Kafka → Temporal, with dedup)
7. Actuator base class + alert dispatch actuator (writes back to world state)
8. Supervisor agent with Send API fan-out to cluster agents
9. Postgres checkpointer + crash recovery scenario
10. interrupt() scenario — high-confidence alert requiring human approval
11. Cross-agent Store for shared incident history
12. LangSmith tracing throughout
13. Scenario scripts — sensor fault, real fire, simultaneous events
14. pgvector memory for past incident recall
15. Time travel scenario

Build order follows the rubric skill progression — each step exercises the next level
of LangGraph capability.

---

## Tech Stack Summary

| Layer | Technology | Notes |
|-------|-----------|-------|
| Event bus | Kafka | Sensor events, commands, results |
| Durable execution | Temporal | Worker orchestration, crash recovery, HITL |
| Agent framework | LangGraph | Subgraphs, state, tool loops |
| LLM | Anthropic Claude (via API) | Classification, correlation, planning |
| Persistence | Postgres | Temporal backend + LangGraph checkpointer |
| Vector memory | pgvector | Semantic incident recall |
| Observability | LangSmith + Temporal UI | Agent traces + workflow execution history |
| Language | Python | Temporal Python SDK + LangGraph |

---

*Document generated from design conversation — intended as context for Claude Code implementation.*