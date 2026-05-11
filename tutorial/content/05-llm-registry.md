# Session 5: LLM Registry

---

## What you're doing and why

You have a working graph skeleton. Session 7 replaces the stub `classify` node with a real LLM. Before that, you need a clean way to *configure* which LLM each agent role uses — without baking `ChatOpenAI(model="gpt-4o-mini")` into graph code.

This session adds a two-level registry to `src/config.py`:

```
role name → LLMLabel → LLMModel → LangChain chat model
```

When the cluster agent needs an LLM, it asks for `"classifier"`. The registry returns a configured LangChain model. The node never knows which provider or model was chosen — that's a config decision, not a graph decision.

---

## Why two levels?

A single `role → model` dict would work until you have multiple roles that should use the same model. With two levels:

- **`models`** — the catalog of every model that exists. Change a model string here once and it updates everywhere.
- **`LLM_ROLE_CONFIG`** — maps each role to a label. Swap a role's model by changing one line.

```python
# To upgrade the classifier from Haiku to Sonnet:
LLM_ROLE_CONFIG = {
    "classifier": LLMLabel.SONNET,   # ← one change
    "supervisor": LLMLabel.SONNET,
}
```

This also makes testing easy: override `LLM_ROLE_CONFIG` with `LLMLabel.STUB` for all roles and no LLM calls happen.

---

## The roles in this project

| Role | Used by | Model | Why |
|------|---------|-------|-----|
| `"classifier"` | Cluster agent `classify` node | Haiku | Fast and cheap — pattern recognition on sensor readings, called once per cluster per tick |
| `"supervisor"` | Supervisor `assess_situation` node | Sonnet | Cross-cluster reasoning — needs to correlate findings and make higher-stakes decisions |

---

## What's in `config.py`

Open `src/config.py`. The three additions are at the bottom of the file:

### `models` — the catalog

```python
models: dict[LLMLabel, LLMModel | None] = {
    LLMLabel.HAIKU: LLMModel(
        key_label="anthropic_api_key",
        provider=LLMProvider.ANTHROPIC,
        model="claude-haiku-4-5-20251001",
    ),
    LLMLabel.SONNET: LLMModel(
        key_label="anthropic_api_key",
        provider=LLMProvider.ANTHROPIC,
        model="claude-sonnet-4-6",
    ),
    ...
    LLMLabel.STUB: None,   # ← STUB maps to None — registry skips it silently
}
```

`key_label` is the name of the field on `Settings` that holds the API key for this provider. When the registry builds a model it does `getattr(settings, model_cfg.key_label)` to inject the key.

### `LLM_ROLE_CONFIG` — the role mapping

```python
LLM_ROLE_CONFIG: dict[str, LLMLabel] = {
    "classifier": LLMLabel.HAIKU,
    "supervisor": LLMLabel.SONNET,
}
```

This is the only file you need to touch to change which model an agent uses.

### `LLMRegistry` and `build_llm_registry`

```python
registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)
llm = registry.get("classifier")      # returns a LangChain BaseChatModel
result = llm.invoke(messages)
```

`registry.get("role")` returns the raw LangChain chat model — call `.invoke()`, `.ainvoke()`, `.bind_tools()`, `.with_structured_output()` directly. No wrapper in between.

If you request a role that isn't registered, the registry falls back to `"classifier"`. If that's also missing it raises `KeyError`.

---

## Get the code

```bash
git fetch tutorial
git checkout tutorial/tutorial-05 -- src/config.py verify_llm_registry.py
```

---

## Verify it works

```bash
python verify_llm_registry.py
```

Expected output when both API keys are configured:

```
=== LLM Registry verification ===

✓ anthropic_api_key loaded
✓ openai_api_key loaded

Registered roles: ['classifier', 'supervisor']

Testing live calls:

  ✓ classifier: OK
  ✓ supervisor: OK

==================================================
✓ All registered roles responding.
```

If you only have Anthropic keys (both roles use Anthropic models by default):

```
✓ anthropic_api_key loaded
ℹ openai_api_key not set (OpenAI roles will be skipped)

Registered roles: ['classifier', 'supervisor']

Testing live calls:

  ✓ classifier: OK
  ✓ supervisor: OK

✓ All registered roles responding.
```

---

## How the registry is used in a graph

In Session 7, the `classify` node will receive an `LLMRegistry` at graph build time via the node factory pattern you already know from `make_report_findings`:

```python
def make_classify_node(registry: LLMRegistry):
    def classify(state: ClusterAgentState) -> dict:
        llm = registry.get("classifier")
        ...
    return classify

# In graph.py:
builder.add_node("evaluate", make_classify_node(registry=registry))
```

The graph doesn't own the registry — it's passed in. That keeps the graph testable without real API calls (pass in a registry built with `LLMLabel.STUB`).

---

## Customising

**To add a new role:**
1. Add an entry to `LLM_ROLE_CONFIG` in `config.py`
2. Use `registry.get("new_role")` in the node factory that needs it

**To add a new model:**
1. Add a `LLMLabel` enum member
2. Add an `LLMModel` entry to `models`
3. Point a role at it in `LLM_ROLE_CONFIG`

**To use OpenAI instead of Anthropic for the classifier:**
```python
LLM_ROLE_CONFIG = {
    "classifier": LLMLabel.GPT_MINI,
    "supervisor": LLMLabel.SONNET,
}
```

**To run without any LLM (stub mode):**
```python
LLM_ROLE_CONFIG = {
    "classifier": LLMLabel.STUB,
    "supervisor": LLMLabel.STUB,
}
```

---

*Next: Session 6 adds routing helpers — utilities that make conditional edges and fan-out patterns reusable across graphs. The registry you just built will be threaded through the graph builders starting in Session 7.*
