# The Advanced AI Engineering Learning Rubric (Revised)

## Strategic Goal

Move from:
- building functional AI applications

to:
- building reliable, measurable, specialized, and efficient AI systems

The emphasis is not on chasing frameworks or hype cycles.  
The emphasis is on understanding:
- evaluation
- retrieval quality
- agent reliability
- inference behavior
- model specialization
- operational efficiency

This roadmap assumes you already have:
- working multi-agent systems
- retrieval pipelines
- production-style backend/frontend architecture
- database-backed memory/context
- experience integrating commercial and local models

---

# Summary Rubric

| Tier               | Primary Goal                             | Core Concepts                                                            | Core Tools                                              | Learning Focus |
|--------------------|------------------------------------------|--------------------------------------------------------------------------|---------------------------------------------------------|---|
| 10                 | API Layer                                |                                                                          | FastAPI                                                 | Build deterministic benchmarks and golden datasets |
| 11                 | Evaluation & Observability               | Accuracy measurement, hallucination detection, regression testing        | DeepEval, Ragas, Phoenix                                | Build deterministic benchmarks and golden datasets |
| 12                 | Advanced Retrieval & Context Engineering | Hybrid search, reranking, retrieval precision                            | pgvector, Postgres FTS, FlashRank, DSPy                 | Improve grounding before touching model weights |
| 13                 | Open-Source Models & Fine-Tuning         | SFT, LoRA, dataset curation, alignment                                   | Unsloth, Axolotl, Hugging Face                          | Distill expensive models into specialized local models |
| 14                 | Inference Infrastructure                 | Throughput, batching, KV cache, quantization                             | vLLM, Ollama, llama.cpp                                 | Understand inference economics and performance |
| 15                 | Distributed AI Systems (Optional Later)  | Multi-node orchestration, autoscaling, event pipelines                   | Kubernetes, Ray, Kafka                                  | Scale mature systems after reliability exists |
| Foundation Chapter | AI Systems & Model Internals             | Transformers, attention, embeddings, tokenization, quantization          | Papers, blogs, small experiments                        | Build intuition for why models behave the way they do |
| ??                 | Agent Reliability Engineering            | Structured outputs, state machines, verification loops, failure recovery | Pydantic, LangGraph, Instructor, JSON schema validation | Reduce nondeterministic agent behavior |

---

# The Strategic Execution Order

```text
┌──────────────────────────┐
│ Step 1: Evaluation &     │
│         Observability    │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Step 2: Agent Reliability│
│         Engineering      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Step 3: Retrieval &      │
│         Context Quality  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Step 4: Fine-Tuning &    │
│         Model Specialize │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Step 5: Inference &      │
│         Self-Hosting     │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Step 6: Distributed      │
│         Systems (Later)  │
└──────────────────────────┘
```

---

# Foundation Chapter — AI Systems & Model Internals

This is not a separate career path.  
It is the conceptual layer that explains why every other tier behaves the way it does.

Without this, it is easy to become dependent on frameworks without understanding:
- why prompts fail
- why retrieval fails
- why hallucinations happen
- why fine-tuning sometimes works and sometimes does not
- why inference latency explodes
- why quantization affects quality

## Topics to Study

| Topic | Importance |
|---|---|
| Transformer architecture | Extremely High |
| Attention mechanisms | High |
| Embeddings & vector geometry | Extremely High |
| Tokenization | High |
| KV cache behavior | High |
| Quantization | High |
| LoRA / QLoRA | High |
| Decoder sampling | Medium |
| RLHF / DPO | Medium |
| Mixture-of-Experts | Medium |
| Context window mechanics | High |
| Inference pipeline | Extremely High |

## Goal

Build enough systems intuition to reason about:
- performance
- memory usage
- latency
- hallucinations
- retrieval behavior
- context saturation
- fine-tuning tradeoffs

You do not need to become an ML researcher.  
You want practical engineering intuition.

---

# Tier 1 — Evaluation & Observability

## Goal

Treat AI systems like testable software systems.

Before modifying:
- prompts
- retrieval
- agent graphs
- model providers
- fine-tunes

…you need deterministic ways to measure improvement.

This is the highest-leverage step in the entire roadmap.

---

## Core Tools

- DeepEval
- Ragas
- Phoenix (Arize)
- LangSmith (optional)
- Custom regression suites

---

## Core Concepts

- Golden datasets
- Hallucination detection
- Faithfulness scoring
- Context relevance
- Answer relevance
- Regression testing
- Evaluation drift
- LLM-as-a-judge systems

---

## Implementation Goal

Build:
- a deterministic evaluation harness
- repeatable scoring
- baseline metrics
- versioned benchmark suites

---

## Recommended Workflow

### 1. Build a Golden Dataset

Create:
- 50–100 realistic scenarios
- edge cases
- failure cases
- geographic/context-heavy queries
- adversarial prompts

Store:
- expected outputs
- expected tool calls
- retrieved contexts

---

### 2. Instrument Your Agent System

Every agent execution should log:
- input
- retrieved context
- intermediate reasoning
- tool usage
- final output
- latency
- token usage

---

### 3. Implement RAG Evaluation

Evaluate:
- faithfulness
- hallucination rate
- context precision
- answer relevance

---

### 4. Establish Baselines

Save benchmark scores to:
- JSON
- Postgres
- dashboards

Treat them like unit-test snapshots.

---

# Tier 1.5 — Agent Reliability Engineering

## Goal

Reduce nondeterministic behavior and improve predictability.

This is where advanced AI systems are actually won.

Most failures in production AI systems are not model failures.

They are:
- orchestration failures
- state failures
- context failures
- tool failures
- schema failures

---

## Core Tools

- Pydantic
- Instructor
- JSON Schema
- LangGraph
- Guardrails
- Structured outputs
- Retry middleware

---

## Core Concepts

| Concept | Why It Matters |
|---|---|
| Typed outputs | Prevent parsing chaos |
| Planner/executor separation | Reduce reasoning instability |
| State machines | Control workflow behavior |
| Verification loops | Catch invalid outputs |
| Confidence scoring | Estimate uncertainty |
| Retry policies | Recover from transient failures |
| Tool contracts | Stabilize agent interactions |
| Failure taxonomies | Understand failure patterns |

---

## Recommended Focus Areas

### Structured Outputs Everywhere

Avoid freeform outputs whenever possible.

Prefer:
- typed JSON
- validated schemas
- deterministic tool contracts

---

### Separate Planning From Execution

Instead of:
- one giant agent prompt

Use:
- planner agent
- executor agents
- verification passes

---

### Add Verification Layers

Examples:
- schema validators
- secondary review agents
- retrieval consistency checks
- confidence thresholds

---

# Tier 2 — Advanced Retrieval & Context Engineering

## Goal

Improve retrieval quality before fine-tuning models.

Most AI systems are retrieval-limited, not model-limited.

---

## Core Tools

- pgvector
- Postgres full-text search
- FlashRank
- DSPy
- Reciprocal Rank Fusion (RRF)

---

## Core Concepts

| Concept | Importance |
|---|---|
| Hybrid retrieval | Extremely High |
| Reranking | Extremely High |
| Embedding quality | High |
| Chunking strategy | High |
| Context compression | Medium |
| Cross-encoders | High |
| Retrieval latency | Medium |

---

## Implementation Plan

### Hybrid Search

Combine:
- semantic vector search
- BM25/full-text search

inside Postgres.

---

### Reciprocal Rank Fusion

Fuse:
- keyword ranking
- semantic ranking

into a unified relevance score.

---

### Cross-Encoder Reranking

Use FlashRank or rerankers to:
- rerank top candidates
- discard weak context
- maximize precision

---

## Key Insight

Better retrieval often outperforms:
- larger models
- longer prompts
- fine-tuning

at dramatically lower cost.

---

# Tier 3 — Fine-Tuning & Model Specialization

## Goal

Distill expensive model behavior into smaller local models.

Not to replace GPT-5-level reasoning.

But to:
- specialize workflows
- reduce cost
- reduce latency
- improve consistency

---

## Core Tools

- Unsloth
- Axolotl
- Hugging Face
- QLoRA
- LoRA adapters

---

## Core Concepts

| Concept | Importance |
|---|---|
| SFT (supervised fine-tuning) | Extremely High |
| Dataset quality | Extremely High |
| Overfitting | High |
| QLoRA | High |
| Chat templates | High |
| Alignment | Medium |
| Distillation | High |

---

## The Fine-Tuning Pipeline

### 1. Collect Logs

Capture:
- successful interactions
- validated outputs
- high-scoring evaluations

---

### 2. Build Datasets

Convert traces into:

```json
{
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

---

### 3. Fine-Tune Small Models

Start with:
- Llama
- Qwen
- Mistral

using:
- QLoRA
- 4-bit training
- small curated datasets

---

### 4. Re-Run Evaluation Suite

Never trust subjective impressions.

Re-run:
- hallucination tests
- benchmark suites
- retrieval evaluation

against the fine-tuned model.

---

# Tier 4 — Inference Infrastructure & Self-Hosting

## Goal

Understand how modern inference systems actually operate.

This tier teaches:
- throughput
- batching
- memory pressure
- KV cache behavior
- concurrency tradeoffs

---

## Core Tools

- vLLM
- llama.cpp
- Ollama
- AWQ/GGUF quantization

---

## Core Concepts

| Concept | Importance |
|---|---|
| KV cache | Extremely High |
| Continuous batching | High |
| Quantization | High |
| VRAM economics | High |
| Concurrent inference | High |
| Memory fragmentation | Medium |

---

## Implementation Goals

### Deploy vLLM

Run:
- OpenAI-compatible endpoints
- local inference servers
- quantized models

---

### Experiment With Quantization

Compare:
- FP16
- 8-bit
- 4-bit

Measure:
- latency
- VRAM
- output degradation

---

### Benchmark Inference

Track:
- tokens/sec
- latency
- concurrency
- memory usage

---

# Tier 5 — Distributed AI Systems (Optional Later)

## Goal

Scale mature systems only after:
- reliability exists
- evaluation exists
- inference behavior is understood

---

## Core Tools

- Kubernetes
- Ray
- Kafka
- distributed GPU scheduling

---

## Important Perspective

These tools solve:
- scaling
- orchestration
- autoscaling
- multi-node compute

They do NOT solve:
- hallucinations
- reasoning quality
- retrieval quality
- agent reliability

---

## Recommendation

Delay deep Kubernetes/Kafka investment until:
- you are operating multiple GPUs
- you need autoscaling
- you have real concurrency pressure
- you have mature inference infrastructure

Otherwise infrastructure complexity can overwhelm actual AI learning.

---

# Final Strategic Perspective

Your current bottleneck is probably not:

> “Can I build AI systems?”

You already can.

Your next bottleneck is:
- reliability
- measurement
- retrieval quality
- specialization
- inference efficiency
- operational understanding

That is the transition from:
- AI application builder

to:
- advanced AI systems engineer.
