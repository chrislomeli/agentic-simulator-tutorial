# Tutorial Playlist — Build-and-Run Sessions

## How to use this tutorial

> **Ground rules for building from scratch.** Follow these to avoid getting stuck.

1. **Do the sessions in order.** Each session depends on the previous one. Skipping ahead will cause import errors because the dependencies don't exist yet.

2. **Type the code, don't copy-paste.** The point is to build muscle memory for LangGraph patterns. When you type `Annotated[List[SensorEvent], append_events]` yourself, you understand what it does. When you paste it, you skip over it.

3. **Run the checkpoint test after every session.** Each session ends with a `pytest` command. If it fails, fix it before moving on. The next session assumes the previous one passes.

4. **Read the Concept Boxes first.** Sessions that introduce new LangGraph primitives (Sessions 02, 03, 05, 06) have a "Concept Box" section near the top. Read it before writing code — it explains the mechanical contract so you know *what* you're typing and *why*.

5. **Use the "What can go wrong" tables.** Every Concept Box has a troubleshooting table. When something breaks (it will), check the table before debugging from scratch.

6. **Session 01 is copy-in, not build.** The infrastructure (world engine, sensors, transport) is not the learning target. Session 01 copies it in so you can focus on agent code starting in Session 02.

7. **Stub first, LLM second.** Sessions 02 and 05 build stub agents (no LLM). Sessions 03 and 06 add the LLM. This separation means you can debug graph wiring without worrying about LLM behavior, and debug LLM behavior without worrying about graph wiring.

---

## Philosophy

Each session builds **one runnable thing**. You can stop after any session and have working code. Later sessions add capabilities without breaking earlier ones.

Sessions 1–5 build infrastructure (no AI). Sessions 6–10 add agents. Sessions 11–12 add resources. Sessions 13–15 are integration, resilience, and evaluation.

---

## Session List

| # | Title | What you build | What you can run |
|---|-------|---------------|-----------------|
| 01 | World Engine + Grid | Terrain grid, cell states, environment, tick loop | `engine.tick()` → print snapshot |
| 02 | Domain Physics — Fire Spread | RothermelFirePhysicsModule, fuel models, ROS/intensity/danger rating | Ignite a cell, watch fire spread with physics-grounded metrics |
| 03 | Sensors — Noisy Observations | SensorBase subclasses, emit(), SensorEvent | Read sensors, compare to ground truth |
| 04 | Sensor Inventory + Publisher | SensorInventory, SensorPublisher, failure modes | `publisher.run()` → events into a queue |
| 05 | Event Queue + Bridge Consumer | SensorEventQueue, EventBridgeConsumer, async plumbing | Producer/consumer pipeline with logging callback |
| 06 | Cluster Agent — Stub Mode | LangGraph StateGraph, TypedDict state, stub nodes | Feed events → get AnomalyFinding output |
| 07 | Cluster Agent — LLM Mode | bind_tools, ToolNode, ReAct loop, conditional edges | Same inputs, LLM-powered classification |
| 08 | Full Sensor→Agent Pipeline | Wire publisher → queue → consumer → cluster agent | End-to-end: world ticks → findings |
| 09 | Supervisor Agent — Stub Mode | Send API fan-out, custom reducers, multi-agent | Feed findings → get ActuatorCommands |
| 10 | Supervisor Agent — LLM Mode | Two ReAct loops (assess + decide), tool composition | LLM correlates across clusters, decides actions |
| 11 | Resources — Preparedness Assets | ResourceBase, ResourceInventory, scenario knobs | Create resources, query readiness, degrade |
| 12 | Resources + Supervisor Tools | resource_tools, fire_behavior_tools, combined tool binding | Supervisor queries preparedness and fire behavior during assessment |
| 13 | Full Pipeline — Everything Wired | World → sensors → agents → supervisor → commands | Complete simulation with all components |
| 14 | Scenario Knobs — Preparedness Under Stress | Sensor failures, resource degradation, comparison | Same scenario, degraded conditions → different assessments |
| 15 | Evaluation — Preparedness Assessment Quality | Compare assessments to actual resource state | Gap detection, recommendation quality, degradation sensitivity |

---

## Rubric Coverage Matrix

Each cell shows which session(s) exercise that rubric skill.

### 1. Graph Primitives

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| StateGraph + TypedDict state | foundational | 06, 09 | ✅ covered |
| Nodes — functions vs runnables | foundational | 06, 07 | ✅ covered |
| Edges — normal vs conditional | foundational | 06, 07 | ✅ covered |
| Reducers and Annotated state | mid-level | 06, 09 | ✅ covered |
| Compile + invoke / stream | foundational | 06, 08 | ✅ covered |

### 2. Control Flow

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| Cycles / loops | mid-level | 07, 10 | ✅ covered |
| Parallel node execution (Send API) | mid-level | 09 | ✅ covered |
| Dynamic branching | mid-level | 07, 10 | ✅ covered |
| Recursion limit + error handling | advanced | — | ⚠️ GAP |

### 3. Tools

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| Tool definition — @tool decorator | foundational | 07, 12 | ✅ covered |
| ToolNode + bind_tools | foundational | 07, 10 | ✅ covered |
| Tool errors + fallback | mid-level | — | ⚠️ GAP |
| Structured output tools | mid-level | 10 | ✅ covered |

### 4. Memory and Persistence

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| Checkpointers — in-memory vs Postgres | mid-level | — | ⚠️ GAP |
| Thread-level vs cross-thread memory | mid-level | — | ⚠️ GAP |
| Long-term memory with Store + embeddings | advanced | — | ⚠️ GAP |
| State schema evolution | advanced | — | ⚠️ GAP (rubric: not yet) |

### 5. Multi-Agent

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| Subgraphs — compile and invoke | mid-level | 09 | ✅ covered |
| State schema handoff between graphs | mid-level | 09 | ✅ covered |
| Supervisor pattern | mid-level | 09, 10 | ✅ covered |
| Agent handoff / swarm pattern | advanced | — | ⚠️ GAP |

### 6. Human-in-the-Loop

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| interrupt() — pause and resume | mid-level | — | ⚠️ GAP |
| State editing before resume | advanced | — | ⚠️ GAP |
| Time travel / replay | advanced | — | ⚠️ GAP (rubric: not yet) |

### 7. Streaming and Observability

| Rubric Skill | Level | Sessions | Status |
|-------------|-------|----------|--------|
| stream_mode — values vs updates vs debug | mid-level | 08 | ✅ covered |
| LangSmith tracing | mid-level | 08, 13 | ✅ covered |
| Custom callbacks | advanced | — | ⚠️ GAP |

---

## Gap Analysis

The 15 sessions cover the **foundational** and **mid-level** skills for Graph Primitives, Control Flow, Tools, and Multi-Agent well. But several rubric areas have no session:

### Gaps that could become additional sessions

| Gap | Rubric Level | Suggested Session |
|-----|-------------|-------------------|
| Checkpointers + crash recovery | mid-level | **16: Persistence — Checkpointers** |
| Cross-agent Store (read/write) | mid-level | **17: Cross-Agent Memory — Store** |
| interrupt() — pause and resume | mid-level | **18: Human-in-the-Loop — interrupt()** |
| Recursion limit + error handling | advanced | **19: Error Handling — Recursion Limits** |
| Tool errors + fallback | mid-level | **20: Tool Error Handling + Fallback** |

### Gaps that are explicitly "not yet" in rubric

These are noted in the rubric as aspirational — not bugs in the tutorial:

- **Long-term memory with pgvector** (advanced) — needs pgvector infrastructure
- **State schema evolution** (advanced) — rubric says "separate exercise"
- **Time travel / replay** (advanced) — rubric says "not yet, high value to add"
- **Agent handoff / swarm** (advanced) — rubric says "needs explicit scenario"
- **State editing before resume** (advanced) — rubric says "partial"
- **Custom callbacks** (advanced) — rubric says "partial"

### Recommendation

Add sessions **16–20** to cover the mid-level gaps. The advanced gaps are fine to leave as future work — the rubric itself marks them as aspirational.

The codebase already has the plumbing for sessions 16–17 (Store is wired into `report_findings` and `assess_situation`, `build_cluster_agent_graph` and `build_supervisor_graph` both accept `store` parameter). Session 18 requires adding `interrupt()` to the supervisor graph, which is a clean additive change.
