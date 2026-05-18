# Rubric Integration Plan — Wildfire Simulator

How to extend this project to cover all tiers of `advanced_ai_engineering_learning_rubric.md`.

---

## What Already Exists (Tier 1.5 — Agent Reliability)

The project already covers Tier 1.5 deeply:

- **Supervisor/worker multi-agent hierarchy** — `SupervisorGraph` fans out to cluster agents via Send API
- **Structured outputs** — Pydantic models everywhere (`CellReadings`, `CollatedRecordRisk`, `LogisticsAssessment`, `RiskScore`)
- **State machines** — full LangGraph StateGraph with typed reducers
- **Planner/executor separation** — supervisor plans, cluster agents evaluate, logistics agent executes
- **Tool contracts** — typed tool factories (`make_get_resources_within`, `make_get_wildfire_activity`)
- **Retry/verification** — `@node_executor` decorator with exception capture, confidence scoring in risk output

No work needed here — just reference it in your portfolio.

---

## Step 10 — FastAPI Layer (new tutorial step)

**Rubric coverage**: Operational foundation for Tiers 1, 2, and 5

### What to build

A `src/api/` package that wraps the existing runtime in HTTP/WebSocket endpoints.

```
src/api/
├── __init__.py
├── app.py              # FastAPI app factory
├── routes/
│   ├── simulation.py   # POST /simulation/start, DELETE /simulation/stop
│   ├── grid.py         # GET /grid/status, GET /grid/{row}/{col}
│   ├── advisories.py   # GET /advisories, GET /advisories/{id}
│   ├── resources.py    # GET /resources/nearby?row=&col=&radius=
│   └── knowledge.py    # POST /knowledge/query  (added in step 12)
└── ws/
    └── events.py       # WS /ws/events — stream sensor events + advisories
```

### Key design decisions

1. **FastAPI `lifespan`** manages `DataStore.open()` / `.close()` and holds the `RuntimeOrchestrator` instance.
2. **Background task** — `POST /simulation/start` launches `orchestrator.run()` as an `asyncio.Task`. The existing async architecture slots right in.
3. **WebSocket streaming** — tap the existing `SensorEventQueue` (or add a broadcast fanout) to push events to connected clients.
4. **`main.py` stays as CLI entry point** — `api/app.py` is the ASGI entry point (`uvicorn src.api.app:app`).
5. The existing `DataStore` ABC is already injected cleanly — FastAPI's dependency injection mirrors what `main.py` already does.

### Dependencies to add

```toml
# pyproject.toml
"fastapi>=0.115",
"uvicorn[standard]>=0.34",
```

### Integration points

| Endpoint | Existing code it wraps |
|---|---|
| `POST /simulation/start` | `RuntimeOrchestrator.run()` |
| `DELETE /simulation/stop` | `RuntimeOrchestrator.stop()` |
| `GET /grid/status` | `CellStateManager` snapshots |
| `GET /advisories` | `AdvisoryRepository.fetch_recent_advisories()` |
| `GET /resources/nearby` | `ResourceRepository.fetch_resources_with_commitments()` |
| `WS /ws/events` | `SensorEventQueue` consumer |

---

## Step 11 — Evaluation Harness (Tier 1)

**Rubric coverage**: Golden datasets, regression testing, LLM-as-judge, hallucination detection

### What to build

The simulator is an evaluation goldmine — it generates deterministic ground-truth scenarios that you can score agent outputs against.

```
src/evaluation/
├── __init__.py
├── golden_dataset.py     # generate scenario → expected risk scores
├── harness.py            # run agent, compare to golden, produce metrics
├── metrics.py            # faithfulness, hallucination rate, answer relevance
└── reporter.py           # JSON/Postgres persistence of eval results
tests/eval/
├── test_risk_eval.py     # regression: cluster agent risk scores
└── test_logistics_eval.py # regression: logistics recommendations
```

### Approach

1. **Golden dataset generation** — run the simulator with known ignition patterns, capture ground-truth cell states (temperature, wind, fuel moisture). The physics engine IS the oracle.
2. **Score agent outputs** — compare `RiskScore` values against physics ground truth. Measure:
   - **Risk accuracy**: did the agent flag the right cells?
   - **Confidence calibration**: are confidence scores meaningful?
   - **Hallucination rate**: did the agent invent conditions not present in sensor data?
   - **Faithfulness**: does the risk narrative match the CollatedRecord it received?
3. **LLM-as-judge** — use a second LLM to evaluate whether the logistics plan is reasonable given the risk assessment (DeepEval or custom).
4. **Regression suite** — save baseline scores, fail CI if scores regress.

### Tools

- **DeepEval** for faithfulness/hallucination metrics
- **Custom metrics** for risk-score accuracy (deterministic, no LLM needed)
- Store results in the existing Postgres instance (new `eval_results` table)
- Expose via FastAPI: `GET /eval/results`, `POST /eval/run`

---

## Step 12 — RAG Knowledge Layer (Tier 2)

**Rubric coverage**: Hybrid search, reranking, retrieval precision, context engineering

### Two RAG surfaces

RAG serves this project in two distinct ways:

1. **Agent grounding** — the cluster `evaluate` node retrieves NWCG fire behavior SOPs to calibrate risk assessments against established doctrine. This is *injected context* before the LLM call, not a tool call.
2. **Fire Analyst Chat** — a conversational interface where a human analyst can ask questions about the simulation state, fire behavior doctrine, and historical incidents. This is the full RAG pipeline: user query → hybrid retrieval → rerank → grounded answer.

The logistics agent does NOT need RAG — its needs are structured queries already served by typed tools (`get_resources_within`, `get_wildfire_activity`).

### What to build

```
src/stores/knowledge/
├── __init__.py
├── repository.py          # KnowledgeRepository ABC + Postgres impl
├── embeddings.py          # embedding model wrapper
├── hybrid_search.py       # pgvector + Postgres FTS + RRF fusion
└── reranker.py            # FlashRank cross-encoder reranking
src/agents/analyst/
├── __init__.py
├── graph.py               # analyst chat graph (retrieve → generate)
├── state.py               # AnalystState, AnalystResponse
└── prompts/               # analyst prompt templates
src/api/routes/
└── analyst.py             # POST /analyst/chat, GET /analyst/history
```

### Knowledge sources

| Source | Content | Consumer |
|---|---|---|
| NWCG Fireline Handbook (SOPs) | Fire behavior thresholds, watchout situations, LCES, red flag criteria | Cluster `evaluate` node — risk grounding |
| LANDFIRE fuel model descriptions | Fuel behavior by vegetation type | Cluster `evaluate` node — fuel context |
| Historical incident reports (ICS-209) | Past fire outcomes, resource deployments, lessons learned | Analyst chat — precedent questions |
| Terrain/weather reference | Slope effects, wind patterns, humidity thresholds | Analyst chat + evaluate node |

### Architecture

1. **Postgres tables** — `knowledge_chunks` with columns: `id`, `content`, `source`, `metadata JSONB`, `embedding vector(1536)`, `ts_content tsvector`
2. **Hybrid search** — combine pgvector cosine similarity + Postgres `ts_rank` via Reciprocal Rank Fusion
3. **Reranking** — FlashRank cross-encoder on top-k candidates (cheap, local, no API call)
4. **Cluster agent integration** — NOT a tool call. The `evaluate` node calls `hybrid_search(query_from_sensor_context)` directly and injects retrieved SOPs into the prompt before the LLM call. This is deterministic retrieval augmentation.
5. **Analyst chat integration** — full conversational RAG. User query → retrieve → rerank → generate grounded response with citations.
6. **Chunking** — paragraph-level with overlap, metadata preserves section hierarchy and source document

### Why the analyst chat matters for the rubric

The autonomous pipeline's RAG use (evaluate node) is legitimate but narrow — you retrieve a few SOP passages to ground risk scores. The analyst chat gives you the full Tier 2 experience:
- Measure **retrieval precision** (did we find the right SOP section?)
- Measure **faithfulness** (does the answer reflect what was retrieved?)
- Experiment with **chunking strategies** (paragraphs vs sections vs sliding window)
- Tune **reranking** (FlashRank threshold, top-k cutoff)
- Build a **golden Q&A dataset** to benchmark retrieval quality

### pgvector is already a dependency

`pyproject.toml` already includes `pgvector>=0.4.2` — no new deps needed for the vector store. Add:

```toml
"flashrank>=0.2",           # local cross-encoder reranking
"tiktoken>=0.9",            # token counting for chunking (or use model tokenizer)
```

### Expose via FastAPI

- `POST /knowledge/ingest` — upload and chunk documents
- `POST /knowledge/query` — hybrid search + rerank (raw retrieval, no generation)
- `GET /knowledge/sources` — list indexed sources
- `POST /analyst/chat` — full RAG: retrieve + generate grounded response
- `GET /analyst/history` — conversation history

---

## Step 13 — Fine-Tuning Pipeline (Tier 3)

**Rubric coverage**: SFT, dataset curation, distillation, LoRA

### Approach

1. **Capture traces** — the `@node_executor` decorator already logs inputs/outputs for every node. Add a trace exporter that writes `(system_prompt, user_input, assistant_output)` tuples to JSONL.
2. **Filter by eval score** — only keep traces where the evaluation harness (Step 11) scored the output above threshold.
3. **Fine-tune** — use the curated dataset to fine-tune a small model (Qwen 7B or Llama 8B) with QLoRA via Unsloth.
4. **Target**: the `evaluate` node in the cluster agent. This is a focused task (sensor data → risk assessment) that's ideal for distillation.
5. **Validate** — re-run the evaluation harness against the fine-tuned model. Compare to the commercial model baseline.

### What to build

```
src/evaluation/
└── trace_exporter.py     # node_executor → JSONL training data
scripts/
├── export_training_data.py
├── finetune_risk_agent.py  # Unsloth QLoRA script
└── eval_finetuned.py       # compare fine-tuned vs baseline
```

---

## Step 14 — Inference Infrastructure (Tier 4)

**Rubric coverage**: vLLM, quantization, KV cache, throughput

### Approach

1. **Self-host the fine-tuned model** from Step 13 via vLLM with OpenAI-compatible API.
2. **Add `vllm` as a provider** in the existing `LLMRegistry` — it already supports STUB/OpenAI/Anthropic/Ollama, so adding vLLM is just another provider entry.
3. **Benchmark** — run the evaluation harness with different configurations:
   - FP16 vs 8-bit vs 4-bit quantization
   - Varying batch sizes (the supervisor fans out to N clusters in parallel — natural batching)
   - Measure tokens/sec, latency, VRAM, quality degradation
4. **KV cache experiments** — the cluster agents receive similar-structured prompts across cells, so prefix caching could help. Measure the impact.

---

## Build Order Summary

| Step | Tier | What | Depends on |
|---|---|---|---|
| **10** | Ops | FastAPI layer | Nothing (wraps existing code) |
| **11** | Tier 1 | Evaluation harness | Nothing (uses existing simulator) |
| **12** | Tier 2 | RAG knowledge layer | Step 10 (API endpoints for ingest/query) |
| **13** | Tier 3 | Fine-tuning pipeline | Step 11 (needs eval scores to filter traces) |
| **14** | Tier 4 | Inference infra | Step 13 (needs fine-tuned model to serve) |

Steps 10 and 11 are independent — you can do either first. I'd recommend **Step 10 (FastAPI) first** because:
- It's the quickest win (thin wrapper over existing code)
- It gives you a visible demo surface immediately
- The eval harness and RAG layer both benefit from having API endpoints

---

## What This Covers on the Rubric

| Rubric Tier | Covered by |
|---|---|
| **Tier 1 — Evaluation** | Step 11: golden datasets from simulator, regression suites, LLM-as-judge |
| **Tier 1.5 — Agent Reliability** | Already built (steps 01–09) |
| **Tier 2 — Retrieval / RAG** | Step 12: pgvector hybrid search, FlashRank reranking, knowledge tools |
| **Tier 3 — Fine-Tuning** | Step 13: trace capture → curated dataset → QLoRA distillation |
| **Tier 4 — Inference** | Step 14: vLLM self-hosting, quantization benchmarks |
| **Tier 5 — Distributed** | Natural extension: Kafka for sensor events, K8s for scaling |
| **Foundation** | Touched throughout: embeddings (step 12), tokenization (step 12), KV cache (step 14), quantization (step 14) |
