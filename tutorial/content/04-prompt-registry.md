# Session 4: Prompt Registry

---

## What you're doing and why

Session 3 gave you a way to acquire an LLM. This session gives you a way to organize the *prompts* you send to it.

The temptation in early-stage code is to put a string constant at the top of `cluster_graph.py`:

```python
CLASSIFY_SYSTEM_PROMPT = """You are a wildfire monitoring analyst..."""
```

That's fine for one prompt. It breaks down as soon as you have more than two, and it makes domain swaps (wildfire → ocean buoys) require editing graph files instead of swapping a prompt module.

You're going to externalize prompts into their own package, with three properties:

1. **Each prompt is its own module** — one file per role.
2. **Static vs. parametric split** — simple prompts are plain `TEMPLATE` strings; prompts that need runtime data (cluster_id, sensor summary) implement a builder.
3. **Version tracking** — every prompt module exports `VERSION`. When session 14's evaluation harness records a result, it records which prompt version produced it.

---

## Why this matters

Prompts are the part that changes most often:
- You tune wording based on eval results (session 14)
- You swap domains (wildfire → flood, ocean buoys, traffic incidents)
- You A/B test variants

If prompts live inline in graph code, every one of those changes touches graph files — and prompt drift becomes invisible to your evaluator. With versioned externalized prompts, you can run two evaluations side-by-side using `v1` and `v2` and see exactly which wording change moved the needle.

By session 11 you'll have ~6 prompts (classify, supervisor_assess, supervisor_decide, evaluate, plus a couple of supporting roles). Building this registry now means each new prompt is a one-file addition with two registry edits.

---

## What you're building

| File | What it contains |
|------|-----------------|
| `src/prompts/__init__.py` | The registry: `PromptKey` enum, `_STATIC_REGISTRY`, `_TEMPLATE_REGISTRY`, `_VERSION_REGISTRY`, `get_prompt()`, `get_prompt_version()` |
| `src/prompts/base.py` | `PromptTemplateBuilder` ABC for parametric prompts |
| `src/prompts/classify.py` | First concrete prompt — the cluster agent classify prompt (parametric on `cluster_id`) |

---

## Coding guidance

### `prompts/base.py`

A single abstract class:

- `PromptTemplateBuilder` with `build(**kwargs) -> str` as the only abstract method.

Use `**kwargs` rather than a typed state argument. The journal_agent original used a typed `JournalState` — you can't do that here because you'll have multiple state types (cluster, supervisor, evaluator) that need their own prompts. `**kwargs` keeps each prompt's contract local.

### Per-prompt modules

Each prompt module exports two things:

- `VERSION: str` — a short tag like `"v1"`. Bump it when the prompt text changes meaningfully.
- One of:
  - `TEMPLATE: str` — a plain string for static prompts that need no runtime data
  - A `PromptTemplateBuilder` subclass — for parametric prompts. The class holds a `_TEMPLATE` private string and a `build(**kwargs)` method that does the formatting.

For `prompts/classify.py`, the parametric variable is `cluster_id`. Move the `CLASSIFY_SYSTEM_PROMPT` you'll write in session 7 into here. The class shape:

```
class ClassifyPrompt(PromptTemplateBuilder):
    _TEMPLATE = "..."
    def build(self, **kwargs) -> str:
        return self._TEMPLATE.format(cluster_id=kwargs["cluster_id"])
```

Use `kwargs["cluster_id"]` (will raise `KeyError` if missing) rather than `kwargs.get("cluster_id", "")` — fail loud, not silently.

### `prompts/__init__.py`

Three module-level dicts and two public functions:

- `class PromptKey(str, Enum)` — the source of truth for valid keys. Start with `CLASSIFY = "classify"`. Add comments for upcoming keys (`SUPERVISOR_ASSESS`, `SUPERVISOR_DECIDE`, `EVALUATE`) so future you knows where they go.
- `_STATIC_REGISTRY: dict[str, str]` — for plain-string prompts. Empty for now.
- `_TEMPLATE_REGISTRY: dict[str, PromptTemplateBuilder]` — for parametric prompts. Add `PromptKey.CLASSIFY.value: ClassifyPrompt()`.
- `_VERSION_REGISTRY: dict[str, str]` — keys mirror the union of the other two; values are the `VERSION` constants from each module.
- `get_prompt(key, **kwargs) -> str` — checks static first, then template registry. `**kwargs` is forwarded to `build()`. Raises `KeyError` for unknown keys.
- `get_prompt_version(key) -> str` — straight lookup in `_VERSION_REGISTRY`.

### How session 7 will use it

When you write the LLM-mode classify node in session 7, the system message is built like:

```
sys_content = get_prompt(PromptKey.CLASSIFY, cluster_id=cluster_id)
sys_msg = SystemMessage(content=sys_content)
```

No string constants in graph code. No `.format()` calls scattered around.

---

## Don't forget

- `PromptKey` should subclass `str, Enum` (not just `Enum`) so you can compare with raw strings if you ever need to.
- The `_TEMPLATE` strings inside builders need **doubled curly braces** (`{{`) to escape JSON examples in the prompt — Python's `str.format()` will choke on raw `{` otherwise. This is a common foot-gun.
- Don't try to validate prompt keys at module-import time by introspecting filenames or running glob patterns. Be explicit — if a prompt isn't in `_TEMPLATE_REGISTRY` or `_STATIC_REGISTRY`, it doesn't exist.
- `__init__.py` should `__all__ = ["get_prompt", "get_prompt_version", "PromptKey"]` so the public surface is clear.

---

## Tests worth writing

- `get_prompt(PromptKey.CLASSIFY, cluster_id="test")` returns a string containing `"test"`.
- `get_prompt_version(PromptKey.CLASSIFY)` returns `"v1"`.
- `get_prompt(PromptKey.CLASSIFY)` (no kwargs) raises `KeyError`.
- `get_prompt("nonexistent")` raises `KeyError`.

---

*Next: Session 5 adds a tracing decorator for graph nodes so every node call is automatically timed and structured-logged.*
