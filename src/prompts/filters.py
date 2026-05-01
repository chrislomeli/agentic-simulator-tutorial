"""
prompts.filters

Project-aware Jinja2 filters registered with the PromptRegistry environment.

Each filter is a plain function. The registry registers them via
jinja_env.filters[name] = fn. Templates use them as {{ value | filter_name }}.

Filters here:
  schema  — renders a Pydantic model class's JSON schema as an indented string.
            Usage in template: {{ "AnomalyFinding" | schema }}
            The registry passes the model_registry dict as context so the
            filter can resolve names to classes.
"""

from __future__ import annotations

import json
from typing import Any


def make_schema_filter(model_registry: dict[str, Any]):
    """
    Factory returning a Jinja2 filter that resolves a model name to its
    JSON schema. The registry passes its known models at environment build time.

    Usage in template:
        {{ "AnomalyFinding" | schema }}
    """
    def schema_filter(model_name: str) -> str:
        model_cls = model_registry.get(model_name)
        if model_cls is None:
            raise ValueError(
                f"schema filter: unknown model '{model_name}'. "
                f"Known: {list(model_registry)}"
            )
        return json.dumps(model_cls.model_json_schema(), indent=2)

    return schema_filter
