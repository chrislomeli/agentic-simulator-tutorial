"""
prompts

File-based prompt registry using Jinja2.

Layout:
    src/prompts/
        __init__.py          — PromptRegistry class (this file)
        filters.py           — Jinja2 filter implementations
        templates/
            <prompt_name>/
                v1.j2        — Jinja2 template
                manifest.yaml — required_vars, description

Public API:
    registry = PromptRegistry()
    text = registry.render("classify", {"cluster_id": "north", ...})
    text = registry.render("classify", ctx, version="v1")
    version = registry.latest_version("classify")

Versioning:
    Versions are directory names sorted lexicographically.
    "latest" resolves to the highest sort value (v2 > v1, v10 > v9 iff
    you zero-pad: v01, v02, ..., v10). Use zero-padded names if you
    expect more than 9 versions.

Manifest validation:
    Each template directory contains a manifest.yaml with at minimum:
        required_vars: [var1, var2]
        description: "one-line description"
    The registry validates that all required_vars are present in the
    context dict before rendering. Missing vars raise KeyError — fail
    loud, not silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from prompts.filters import make_schema_filter

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Models available to the {{ "ModelName" | schema }} filter.
# Add new Pydantic models here as the project grows.
from agents.cluster.state import AnomalyFinding

_MODEL_REGISTRY: dict[str, Any] = {
    "AnomalyFinding": AnomalyFinding,
}


class PromptRegistry:
    """
    Loads and renders Jinja2 prompt templates from the templates/ directory.

    One instance is enough for the whole application — create it once and
    pass it to the nodes that need it, or import a module-level singleton.
    """

    def __init__(self, templates_dir: Path = _TEMPLATES_DIR) -> None:
        self._templates_dir = templates_dir
        self._env = self._build_env()

    def _build_env(self) -> Environment:
        env = Environment(
            loader=FileSystemLoader(str(self._templates_dir)),
            undefined=StrictUndefined,  # raise on missing vars, never silently blank
            trim_blocks=True,           # strip newline after block tags
            lstrip_blocks=True,         # strip leading whitespace before block tags
        )
        env.filters["schema"] = make_schema_filter(_MODEL_REGISTRY)
        return env

    def latest_version(self, prompt_name: str) -> str:
        """Return the highest version directory name for a prompt."""
        prompt_dir = self._templates_dir / prompt_name
        if not prompt_dir.is_dir():
            raise KeyError(f"No prompt named '{prompt_name}' in {self._templates_dir}")
        versions = sorted(
            d.name for d in prompt_dir.iterdir()
            if d.is_dir() and (d / "manifest.yaml").exists()
        )
        if not versions:
            raise KeyError(f"No versioned templates found for prompt '{prompt_name}'")
        return versions[-1]

    def _load_manifest(self, prompt_name: str, version: str) -> dict:
        manifest_path = self._templates_dir / prompt_name / version / "manifest.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing manifest: {manifest_path}")
        with open(manifest_path) as f:
            return yaml.safe_load(f) or {}

    def render(
        self,
        prompt_name: str,
        context: dict[str, Any],
        *,
        version: str | None = None,
    ) -> str:
        """
        Render a prompt template and return the completed string.

        Parameters
        ----------
        prompt_name : Key matching a subdirectory of templates/.
        context     : Dict of variables passed to the template.
        version     : Explicit version (e.g. "v1"). Defaults to latest.

        Raises
        ------
        KeyError           : Unknown prompt or missing required context var.
        FileNotFoundError  : Missing manifest or template file.
        """
        resolved_version = version or self.latest_version(prompt_name)
        manifest = self._load_manifest(prompt_name, resolved_version)

        required = manifest.get("required_vars", [])
        missing = [v for v in required if v not in context]
        if missing:
            raise KeyError(
                f"Prompt '{prompt_name}/{resolved_version}' missing required vars: {missing}"
            )

        template_path = f"{prompt_name}/{resolved_version}/prompt.j2"
        template = self._env.get_template(template_path)
        return template.render(**context)


# Module-level singleton — import and use directly in nodes.
registry = PromptRegistry()
