# Steps 10–12 Detailed Design

Implementation plan for FastAPI, Evaluation, and RAG layers.
This is the working design doc — pick up from wherever you left off.

---

## Status

| Step | Status | Notes |
|---|---|---|
| Step 10 — FastAPI | NOT STARTED | |
| Step 11 — Evaluation | NOT STARTED | |
| Step 12 — RAG + Analyst Chat | NOT STARTED | |

---

# Step 10 — FastAPI Layer

## Goal

Wrap the existing async runtime in HTTP/WebSocket endpoints. No new logic —
just an API surface over `RuntimeOrchestrator`, `CellStateManager`, and the
existing repos.

## Package layout

```
src/api/
├── __init__.py
├── app.py                  # FastAPI app factory + lifespan
├── dependencies.py         # DI: get_data_store, get_orchestrator, get_engine
├── routes/
│   ├── __init__.py
│   ├── simulation.py       # simulation lifecycle
│   ├── grid.py             # grid/cell state queries
│   ├── advisories.py       # advisory CRUD
│   └── resources.py        # resource queries
└── ws/
    ├── __init__.py
    └── events.py           # WebSocket: stream sensor events + advisories
```

## Endpoints

### Simulation lifecycle

| Method | Path | Body/Params | What it does |
|---|---|---|---|
| POST | `/simulation/start` | `{ ticks?: int, tick_interval_sec?: float, location_count?: int }` | Launches `orchestrator.run()` as background task. Returns 202 + task ID. |
| DELETE | `/simulation/stop` | — | Calls `orchestrator.stop()`. Returns 200 when cooperative stop completes. |
| GET | `/simulation/status` | — | Returns `RuntimeStats` snapshot (ticks, events, scores). |

### Grid state

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/grid/status` | — | All cells with latest metric values + triggered status |
| GET | `/grid/{row}/{col}` | — | Single cell detail: metrics, history, coverage summary |
| GET | `/grid/heatmap` | `?metric=temperature` | 2D array of latest values for one metric type |

### Advisories

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/advisories` | `?row=&col=&limit=10` | Recent advisories for a cell |
| GET | `/advisories/{id}` | — | Single advisory detail |

### Resources

| Method | Path | Params | Returns |
|---|---|---|---|
| GET | `/resources/nearby` | `?row=&col=&radius_mi=` | Resources within radius + commitment status |

## Key implementation details

### Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    data_store = get_postgres_data_store()
    engine, sensor_inventory = load_scenario_from_db("lpnf-south", data_store)
    cell_state_manager = CellStateManager(
        world_grid=engine.grid,
        sensor_inventory=sensor_inventory,
    )
    agent_deps = build_agent_deps(engine, cell_state_manager, data_store=data_store)
    supervisor_graph = build_supervisor_graph(agent_dependencies=agent_deps)

    app.state.data_store = data_store
    app.state.engine = engine
    app.state.sensor_inventory = sensor_inventory
    app.state.cell_state_manager = cell_state_manager
    app.state.agent_deps = agent_deps
    app.state.supervisor_graph = supervisor_graph
    app.state.orchestrator = None  # created on POST /simulation/start
    app.state.sim_task = None

    yield

    # Shutdown
    if app.state.orchestrator:
        app.state.orchestrator.stop()
    data_store.close()
```

### Background simulation task

```python
@router.post("/simulation/start", status_code=202)
async def start_simulation(request: Request, params: SimStartParams):
    if request.app.state.sim_task and not request.app.state.sim_task.done():
        raise HTTPException(409, "Simulation already running")

    orch = RuntimeOrchestrator(
        sensor_inventory=request.app.state.sensor_inventory,
        engine=request.app.state.engine,
        supervisor_graph=request.app.state.supervisor_graph,
        cell_state_manager=request.app.state.cell_state_manager,
        sampler=sample_local_conditions,
        tick_interval_seconds=params.tick_interval_sec,
        location_count=params.location_count,
    )
    request.app.state.orchestrator = orch
    request.app.state.sim_task = asyncio.create_task(orch.run(ticks=params.ticks))
    return {"status": "started", "ticks": params.ticks}
```

### WebSocket events

Tap the existing `SensorEventQueue` pattern. Add a broadcast list that the
orchestrator's consume loop also pushes to:

```python
# In ws/events.py
@router.websocket("/ws/events")
async def event_stream(ws: WebSocket):
    await ws.accept()
    broadcast = request.app.state.broadcast  # asyncio.Queue per client
    try:
        while True:
            event = await broadcast.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
```

### Dependencies to add to pyproject.toml

```toml
"fastapi>=0.115",
"uvicorn[standard]>=0.34",
```

### Entry point

```bash
# New ASGI entry (api/app.py)
uvicorn src.api.app:app --reload --port 8000

# Existing CLI stays untouched
python main.py
```

## What to test

- `POST /simulation/start` → confirm background task runs, stats increment
- `GET /simulation/status` → returns valid `RuntimeStats`
- `DELETE /simulation/stop` → cooperative stop, task completes
- `GET /grid/status` → returns cell snapshots after events processed
- `GET /advisories` → returns advisories after graph produces them
- WebSocket → receives events in real-time during sim run

---

# Step 11 — Evaluation Harness

## Goal

Deterministic evaluation of agent outputs using the physics engine as oracle.

## Core insight

The simulator generates ground truth. You know the *actual* temperature,
wind speed, fuel moisture at every cell. The agent receives *noisy sensor
readings* and must infer risk. You can score the agent's inference against
reality.

## Package layout

```
src/evaluation/
├── __init__.py
├── scenarios.py           # ScenarioSpec: ignition pattern + expected outcomes
├── golden_dataset.py      # generate + persist golden records
├── harness.py             # run agent on scenario, collect outputs
├── metrics.py             # scoring functions
├── reporter.py            # persist results to DB / JSON
└── trace_exporter.py      # (for step 13) export scored traces to JSONL
tests/eval/
├── conftest.py            # fixtures: load golden dataset
├── test_risk_accuracy.py  # cluster agent regression
└── test_faithfulness.py   # narrative matches sensor data
```

## Scenario format

```python
@dataclass
class ScenarioSpec:
    """A reproducible test case for the evaluation harness."""
    name: str
    region: str                        # scenario DB region
    ignition_cells: list[tuple[int,int]]  # where to ignite
    ticks: int                         # how long to run
    expected_high_risk_cells: set[tuple[int,int]]  # ground truth
    expected_min_score: dict[str, int]  # cluster_id → minimum acceptable score
    notes: str = ""
```

## Metrics

### Deterministic (no LLM needed)

| Metric | What it measures | Formula |
|---|---|---|
| **Risk accuracy** | Did agent flag the right cells as high-risk? | precision/recall of high-risk cells vs physics ground truth |
| **Score calibration** | Are scores proportional to actual danger? | Spearman correlation: agent scores vs ground-truth severity ranking |
| **Confidence calibration** | Does confidence=9 mean the agent is usually right? | Bin by confidence, measure accuracy per bin |
| **Latency** | How fast is the full pipeline? | p50, p95, p99 per node |

### LLM-as-judge (requires second model call)

| Metric | What it measures |
|---|---|
| **Faithfulness** | Does the risk narrative cite only facts present in the CollatedRecord? |
| **Hallucination rate** | Did the agent invent sensor readings or conditions not in the input? |
| **Relevance** | Is the logistics plan relevant to the risk assessment it received? |

### Tools

- **DeepEval** — faithfulness + hallucination metrics out of the box
- **Custom scoring functions** — risk accuracy, calibration (pure Python, no deps)
- **Ragas** — optional, if you want context precision/recall metrics for RAG (step 12)

## Golden dataset generation

```python
async def generate_golden_dataset(scenario: ScenarioSpec) -> GoldenRecord:
    """Run physics engine, capture ground truth, run agent, capture output."""
    engine, inventory = load_scenario_from_db(scenario.region, data_store)

    # Ignite specified cells
    for row, col in scenario.ignition_cells:
        engine.grid.get_cell(row, col).cell_state.ignite()

    # Run physics for N ticks — captures ground truth per cell
    ground_truth = []
    for _ in range(scenario.ticks):
        engine.tick()
        ground_truth.append(snapshot_grid(engine))

    # Run agent pipeline on the final state
    agent_output = await run_agent_on_snapshot(engine, inventory, scenario)

    return GoldenRecord(
        scenario=scenario,
        ground_truth=ground_truth,
        agent_output=agent_output,
    )
```

## FastAPI integration

| Method | Path | What |
|---|---|---|
| POST | `/eval/run` | Run evaluation harness on a named scenario |
| GET | `/eval/results` | Fetch stored evaluation results |
| GET | `/eval/scenarios` | List available scenarios |

---

# Step 12 — RAG Knowledge Layer + Fire Analyst Chat

## Goal

Build a retrieval pipeline that serves two consumers:
1. The cluster `evaluate` node (automatic context injection)
2. A human-facing analyst chat (full conversational RAG)

## Data pipeline

### Source documents → chunks → embeddings → Postgres

```
NWCG PDFs / markdown
        │
        ▼
  chunker (paragraph + overlap)
        │
        ▼
  embed (OpenAI text-embedding-3-small or local)
        │
        ▼
  INSERT into knowledge_chunks
  (content, source, metadata, embedding, ts_content)
```

### NWCG data sources to pull

| Document | Where to get it | Priority |
|---|---|---|
| Incident Response Pocket Guide (IRPG) | nwcg.gov/publications/pms461 | HIGH — 18 watchout situations, LCES, fire behavior indicators |
| Wildland Fire Incident Management Field Guide | nwcg.gov/publications/pms210 | HIGH — operational thresholds, decision trees |
| S-190 Introduction to Wildland Fire Behavior | nwcg.gov/publications/training-courses/s-190 | MEDIUM — fire behavior fundamentals |
| Fuel Model Descriptions (Scott & Burgan 40) | frames.gov or LANDFIRE docs | MEDIUM — what each fuel model means for fire spread |
| Red Flag Warning criteria by GACC | weather.gov/fire | LOW — region-specific thresholds |

### Ingest script

```bash
# scripts/ingest_knowledge.py
python scripts/ingest_knowledge.py --source nwcg-irpg --path ./data/nwcg/irpg.md
python scripts/ingest_knowledge.py --source fuel-models --path ./data/nwcg/fuel_models.md
```

## Knowledge store schema

```sql
CREATE TABLE knowledge_chunks (
    id          SERIAL PRIMARY KEY,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,           -- e.g. 'nwcg-irpg', 'fuel-models'
    section     TEXT,                    -- e.g. 'Watchout Situations'
    metadata    JSONB DEFAULT '{}',      -- arbitrary: page, chapter, tags
    embedding   vector(1536),           -- pgvector
    ts_content  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_knowledge_embedding ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_knowledge_fts ON knowledge_chunks USING gin (ts_content);
CREATE INDEX idx_knowledge_source ON knowledge_chunks (source);
```

## Hybrid search implementation

```python
def hybrid_search(
    query: str,
    query_embedding: list[float],
    top_k: int = 20,
    source_filter: str | None = None,
    rrf_k: int = 60,
) -> list[ScoredChunk]:
    """
    1. Vector search: top_k by cosine similarity
    2. Full-text search: top_k by ts_rank
    3. Reciprocal Rank Fusion to merge rankings
    4. Return fused top_k
    """
    ...
```

### Reciprocal Rank Fusion (RRF)

```python
def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Fuse multiple ranked lists. Score = sum(1 / (k + rank_i))"""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

## Reranking

```python
from flashrank import Ranker

ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2")

def rerank(query: str, chunks: list[ScoredChunk], top_n: int = 5) -> list[ScoredChunk]:
    """Cross-encoder reranking on fused candidates."""
    passages = [{"id": c.id, "text": c.content} for c in chunks]
    results = ranker.rerank(query, passages)
    return results[:top_n]
```

## Consumer 1: Cluster `evaluate` node

The evaluate node currently receives a `CollatedRecord` and calls the LLM.
With RAG, it retrieves relevant SOPs first:

```python
# In agents/cluster/risk_nodes.py — evaluate()

# Build retrieval query from sensor context
query = f"fire behavior {cell.terrain} wind {cell.wind_speed} humidity {cell.humidity}"
retrieved_sops = knowledge_repo.search(query, source_filter="nwcg-irpg", top_n=3)

# Inject into prompt
prompt = prompt_registry.render("evaluate", version="v2", context={
    "sensor_data": collated_record,
    "reference_sops": retrieved_sops,  # NEW: grounding context
})

# LLM call as before
response = await llm.ainvoke(prompt)
```

The prompt template gains a `{% if reference_sops %}` section that presents
the retrieved SOP text as authoritative reference material.

### Measuring impact

Run the evaluation harness (Step 11) with and without RAG context:
- Does risk accuracy improve?
- Does the narrative cite specific standards?
- Does hallucination rate decrease?

## Consumer 2: Fire Analyst Chat

A separate LangGraph `StateGraph` for conversational Q&A:

```python
# agents/analyst/graph.py

class AnalystState(TypedDict):
    messages: Annotated[list, add_messages]
    retrieved_chunks: list[ScoredChunk]
    response: str

# Nodes:
# 1. retrieve — hybrid_search + rerank based on latest user message
# 2. generate — LLM call with retrieved context + conversation history
# 3. (optional) cite — extract citations from response

analyst_graph = StateGraph(AnalystState)
analyst_graph.add_node("retrieve", retrieve_node)
analyst_graph.add_node("generate", generate_node)
analyst_graph.add_edge("retrieve", "generate")
analyst_graph.add_edge(START, "retrieve")
analyst_graph.add_edge("generate", END)
```

### Example queries the analyst chat handles

- "What are the NWCG watchout situations that apply when wind exceeds 30 mph?"
- "How many engines were typically deployed to 500-acre chaparral fires?"
- "What's the current risk level in cluster north-ridge?"
- "Explain why cell (3,4) triggered a high-risk score"

The last two require access to **live simulation state** in addition to the
knowledge base. The `retrieve` node can query both `knowledge_chunks` AND
`CellStateManager` snapshots, making the analyst chat a bridge between
the document corpus and the running simulation.

### FastAPI endpoints

```python
# api/routes/analyst.py

@router.post("/analyst/chat")
async def analyst_chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Full RAG pipeline: user message → retrieve → generate → response."""
    graph = request.app.state.analyst_graph
    result = await graph.ainvoke({"messages": [HumanMessage(body.message)]})
    return ChatResponse(
        response=result["response"],
        sources=[c.source for c in result["retrieved_chunks"]],
    )
```

## Dependencies to add

```toml
"flashrank>=0.2",
"tiktoken>=0.9",
```

## Evaluation of RAG quality (ties back to Step 11)

Build a golden Q&A dataset for the analyst chat:

```json
{
  "question": "What NWCG watchout situations apply to chaparral terrain with winds above 25 mph?",
  "expected_sources": ["nwcg-irpg"],
  "expected_content_keywords": ["Watchout #4", "wind-driven fire", "LCES"],
  "ground_truth_answer": "Watchout Situation #4 (wind increases) and #10 (attempting frontal assault)..."
}
```

Metrics:
- **Context precision** — % of retrieved chunks that are relevant (Ragas)
- **Context recall** — % of required info that was retrieved (Ragas)
- **Faithfulness** — does the generated answer reflect only what was retrieved?
- **Answer relevance** — does it actually answer the question?

---

# Implementation Order Within Steps 10–12

These can be built incrementally across sessions:

## Step 10 (FastAPI) — sub-tasks

1. Add `fastapi` + `uvicorn` to deps
2. Create `src/api/app.py` with lifespan (reuse `main.py` composition logic)
3. `GET /simulation/status` — simplest endpoint, just returns stats
4. `POST /simulation/start` + `DELETE /simulation/stop`
5. `GET /grid/status` + `GET /grid/{row}/{col}`
6. `GET /advisories`
7. WebSocket `/ws/events`

## Step 11 (Evaluation) — sub-tasks

1. Define `ScenarioSpec` and create 3–5 test scenarios
2. Implement `golden_dataset.py` — run physics, snapshot ground truth
3. Implement deterministic metrics (risk accuracy, calibration)
4. Run baseline eval with current agent, persist scores
5. Add LLM-as-judge metrics (DeepEval faithfulness)
6. Wire into FastAPI (`POST /eval/run`)

## Step 12 (RAG) — sub-tasks

1. Create `knowledge_chunks` table + repository
2. Write ingest script, chunk + embed NWCG IRPG
3. Implement `hybrid_search` (vector + FTS + RRF)
4. Add FlashRank reranking
5. Wire into cluster `evaluate` node (inject SOP context)
6. Run eval harness: measure with/without RAG
7. Build analyst chat graph
8. Wire analyst chat into FastAPI
9. Build golden Q&A dataset for analyst, measure retrieval quality

---

# Session resumption notes

When picking this back up:
1. Check **Status** table at top of this doc
2. Read `docs/rubric-integration-plan.md` for the big picture
3. Read `docs/risk-pipeline-design.md` for existing architecture details
4. The composition root is `main.py` — that's where all wiring happens
5. All repos are behind ABCs in `src/stores/base.py`
6. `pyproject.toml` already has pgvector, pydantic, langgraph, langchain
