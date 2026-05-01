# Session 3: LLM Client + Registry

---

## What you're doing and why

You just shipped a working graph in stub mode. Session 7 will replace the stub `classify` node with an LLM. Before that, you need a clean way to *acquire* an LLM that doesn't bake provider-specific imports (`ChatOpenAI`, `ChatAnthropic`) into graph code.

This session introduces two pieces:

1. **`LLMClient`** — a thin wrapper over a LangChain chat model. Graph nodes call `client.chat(messages)` or `client.get_client()` (for `bind_tools`) and never know which provider is underneath.
2. **`LLMRegistry`** — a role-based catalog (`"classifier"`, `"supervisor"`, `"evaluator"`) built once at startup. Each agent asks the registry for the LLM that matches its role.

---

## Why this matters

Most LangGraph tutorials hardcode `ChatOpenAI(model="gpt-4o-mini")` in the graph file. That works for one agent. The moment you have two agents that should use *different* models — a small/cheap classifier for the cluster agent and a stronger reasoner for the supervisor — hardcoding falls apart. You start threading `llm=` parameters through every builder, every test fixture, and every notebook.

Looking ahead in this tutorial:
- Session 7 — cluster classify needs a small, fast model
- Session 10 — supervisor needs a stronger model that can reason about cross-cluster correlations
- Session 14 — evaluation needs its own LLM (possibly different again)

A registry lets each session say `registry.get("classifier")` without coordinating on construction details.

---

## What you're building

| File | What it contains |
|------|-----------------|
| `src/comms/__init__.py` | Package marker |
| `src/comms/llm_client.py` | `LLMClient` wrapper + `create_llm_client()` factory |
| `src/comms/llm_registry.py` | `LLMRegistry` dataclass + `build_llm_registry()` |
| `src/config.py` (modify) | Add `models` catalog, `LLM_ROLE_CONFIG`, and `configure_environment()` |

---

## Coding guidance

### `LLMClient`

Keep this intentionally thin. Hold a private `_client` (the LangChain chat model) and forward calls. The methods that earn their place:

- `chat(messages) -> AIMessage` — synchronous invoke
- `achat(messages)` — async invoke
- `astream(messages)` — async iterator over `AIMessageChunk` (useful in session 10+ for streaming supervisor output)
- `structured(schema)` — wraps `client.with_structured_output(schema, method="json_schema")`
- `get_client()` — escape hatch for `bind_tools()` and any LangChain feature you haven't wrapped yet

**Don't add abstractions that only one caller uses.** If you find yourself adding a `chat_with_retry()` method, it belongs in the caller until two callers need it.

### `create_llm_client(provider, api_key, model, base_url=None)`

A factory function — one branch per `LLMProvider`. Use **lazy imports** inside each branch so that if a user only has OpenAI installed, importing `comms` doesn't blow up trying to import `langchain_anthropic`.

For Anthropic, watch out: `SecretStr` from pydantic needs `.get_secret_value()` before being passed to `ChatAnthropic` — that's a real foot-gun.

### `LLMRegistry`

A `@dataclass` holding `_clients: dict[str, LLMClient]`. The only public API:
- `get(role: str) -> LLMClient` — return the role's client. If missing, fall back to a default role (`"classifier"` is a sensible choice). If the fallback also doesn't exist, raise.
- `roles -> list[str]` — for debugging and tests

Never let the registry construct lazily. Construct everything at startup so misconfiguration fails fast, not on the first user request.

### `build_llm_registry(settings, models, role_config) -> LLMRegistry`

The builder reads three things:
- `settings: Settings` — carries API keys
- `models: dict[LLMLabel, LLMModel | None]` — the catalog of available models
- `role_config: dict[str, LLMLabel]` — which model each role should use

For each entry in `role_config`, look up the model, inject the API key from settings (the `key_label` field on `LLMModel` tells you which `Settings` attribute holds the key), then call `create_llm_client`. Skip with a warning if the model is missing — don't crash the whole startup because one optional role isn't configured.

### Updates to `src/config.py`

Three additions:

1. **Extend `LLMProvider`** with `OLLAMA = "OLLAMA"` if you want local-dev support. Optional — skip if the friction of `langchain-ollama` outweighs the benefit at this stage.

2. **Add `models` catalog** — module-level `dict[LLMLabel, LLMModel | None]` mapping each label to its `LLMModel(model=..., key_label=..., provider=...)`. This is the single source of truth for "what models exist."

3. **Add `LLM_ROLE_CONFIG`** — module-level `dict[str, LLMLabel]` mapping roles to labels. Start with `"classifier": LLMLabel.GPT_MINI` and add `"supervisor"` when you get to session 10.

4. **Add `configure_environment() -> Settings`** — single bootstrap function. Loads `.env`, calls `settings.apply_langsmith()`, sets up logging (basic format + httpx silenced). This is what every notebook, test conftest, and entry point calls first.

---

## Don't forget

- `comms/__init__.py` can be empty — just makes `comms` a package.
- `LLMProvider.STUB` should map to `None` in the `models` dict — useful for tests that need the registry to skip rather than connect.
- Add `langchain-anthropic` (and `langchain-ollama` if you support it) to `pyproject.toml` under the `llm` optional group.
- The bootstrap pattern any caller uses: `settings = configure_environment(); registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)`.

---

## Tests worth writing

- `build_llm_registry` with an empty role_config returns an empty registry (no errors).
- `registry.get("nonexistent")` falls back to `"classifier"` if present, else raises `KeyError`.
- `create_llm_client(LLMProvider.STUB, ...)` is allowed to raise — STUB is a config marker, not a provider.

---

*Next: Session 4 externalizes prompts so they're versioned, swappable, and not buried inside graph code.*
