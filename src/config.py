"""
world-simiulator.config

Centralised settings for the world-simiulator testbed.

Loading order (pydantic-settings resolves in this priority, highest first):
  1. Actual environment variables  (e.g. injected by K8s)
  2. .env file pointed to by AI_ENV_FILE  (local dev)
  3. Default values defined below

Usage
─────
  from config import Settings, build_llm_registry, LLM_ROLE_CONFIG, models

  settings = Settings()
  settings.apply_langsmith()

  registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)
  llm = registry.get("classifier")
  result = llm.invoke(messages)

Settings is constructed once at the composition root and threaded down
into anything that needs it. There is deliberately no module-level
cached singleton — it makes tests harder (cache_clear footguns), breaks
in multi-process deployments, and hides the dependency from callers.

Deployment modes
────────────────
  Local dev  — set AI_ENV_FILE=/path/to/.env  (or export vars directly)
  K8s        — leave AI_ENV_FILE unset; inject vars via ConfigMap / Secret
"""

from __future__ import annotations

import dataclasses
import logging
import os
from enum import Enum
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


# ── Provider / label enums ────────────────────────────────────────────────────


class LLMProvider(Enum):
    STUB = "STUB"
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    OLLAMA = "OLLAMA"


class LLMLabel(Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"
    GPT_MINI = "gpt-mini"
    GPT = "gpt"
    OLLAMA_LLAMA3 = "ollama-llama3"
    STUB = "STUB"


# ── Model config ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class LLMModel:
    model: str
    key_label: str
    provider: LLMProvider
    api_key: SecretStr | None = None


# ── Available model definitions ───────────────────────────────────────────────
# Maps LLMLabel → LLMModel. Add new models here as needed.
# key_label must match a field name on Settings.

models: dict[LLMLabel, LLMModel | None] = {
    # Anthropic
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
    LLMLabel.OPUS: LLMModel(
        key_label="anthropic_api_key",
        provider=LLMProvider.ANTHROPIC,
        model="claude-opus-4-7",
    ),
    # OpenAI
    LLMLabel.GPT_MINI: LLMModel(
        key_label="openai_api_key",
        provider=LLMProvider.OPENAI,
        model="gpt-4o-mini",
    ),
    LLMLabel.GPT: LLMModel(
        key_label="openai_api_key",
        provider=LLMProvider.OPENAI,
        model="gpt-4o",
    ),
    # Ollama (local)
    LLMLabel.OLLAMA_LLAMA3: LLMModel(
        key_label="ollama_base_url",
        provider=LLMProvider.OLLAMA,
        model="llama3.2:latest",
    ),
    # Stub — no LLM
    LLMLabel.STUB: None,
}


# ── Role → model label mapping ────────────────────────────────────────────────
# Maps agent role → LLMLabel.
# Change a label here to swap the model for that role everywhere.

LLM_ROLE_CONFIG: dict[str, LLMLabel] = {
    "classifier": LLMLabel.HAIKU,  # cluster agent — fast sensor pattern recognition
    "supervisor": LLMLabel.SONNET,  # supervisor — cross-cluster reasoning
}


# ── Settings ──────────────────────────────────────────────────────────────────


class Settings(BaseSettings):
    # ── LLM credentials ───────────────────────────────────────────────────────
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    # ── World data ────────────────────────────────────────────────────────────
    world_data: str = "src/domains/wildfire/scenario_data/north_south_fire.json"

    # ── LangSmith / LangChain tracing ─────────────────────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "world-simulator"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    model_config = SettingsConfigDict(
        # env_file is intentionally NOT set at class-definition time —
        # the composition root passes ``_env_file=os.getenv("AI_ENV_FILE")``
        # at construction so the lookup happens per-instance. Tests can
        # construct Settings() without any .env interference.
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def apply_langsmith(self) -> None:
        """Write LangSmith settings into os.environ so LangGraph picks them up."""
        pairs = {
            "LANGCHAIN_API_KEY": self.langchain_api_key,
            "LANGCHAIN_TRACING_V2": "true" if self.langchain_tracing_v2 else "",
            "LANGCHAIN_PROJECT": self.langchain_project,
            "LANGCHAIN_ENDPOINT": self.langchain_endpoint,
        }
        for key, value in pairs.items():
            if value and not os.environ.get(key):
                os.environ[key] = value


# ── LLM Registry ──────────────────────────────────────────────────────────────


class LLMRegistry:
    """
    Role-based catalog of LangChain chat models.

    Built once at startup and threaded into graph builders. Nodes request
    a model by role without knowing which provider or model was configured.

    Usage:
        registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)
        llm = registry.get("classifier")
        result = llm.invoke(messages)
    """

    def __init__(self, clients: dict[str, Any]) -> None:
        self._clients = clients

    def get(self, role: str, default: str | None = None) -> Any:
        client = self._clients.get(role, default)
        if client is not None:
            return client
        raise KeyError(f"No LLM registered for role {role!r}.")

    @property
    def roles(self) -> list[str]:
        return sorted(self._clients)


def _build_chat_model(model_cfg: LLMModel, ollama_base_url: str) -> Any:
    """Instantiate a LangChain chat model from a resolved LLMModel."""
    api_key = (
        model_cfg.api_key.get_secret_value()
        if isinstance(model_cfg.api_key, SecretStr)
        else model_cfg.api_key
    )
    if model_cfg.provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_cfg.model, temperature=0, api_key=api_key)
    elif model_cfg.provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model_name=model_cfg.model, api_key=api_key, temperature=0)
    elif model_cfg.provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model_cfg.model, temperature=0, base_url=ollama_base_url)
    raise ValueError(f"Unknown provider: {model_cfg.provider}")


def build_llm_registry(
    settings: Settings,
    model_catalog: dict[LLMLabel, LLMModel | None],
    role_config: dict[str, LLMLabel],
) -> LLMRegistry:
    """
    Build an LLMRegistry from settings + model catalog + role config.

    Parameters
    ----------
    settings:     Loaded Settings (carries API keys and ollama_base_url).
    model_catalog: LLMLabel → LLMModel mapping (defined above as `models`).
    role_config:  role name → LLMLabel mapping (defined above as `LLM_ROLE_CONFIG`).

    STUB roles are skipped — registry.get() will raise KeyError if all
    roles are stubs and there is no fallback.
    """
    clients: dict[str, Any] = {}

    for role, label in role_config.items():
        model_cfg = model_catalog.get(label)
        if model_cfg is None:
            logger.info("Skipping role %r — STUB label", role)
            continue

        resolved = dataclasses.replace(model_cfg)
        raw = getattr(settings, resolved.key_label, None)
        resolved.api_key = raw if raw else None

        chat_model = _build_chat_model(resolved, settings.ollama_base_url)
        clients[role] = chat_model
        logger.info(
            "Registered LLM for role %r → %s (%s)",
            role,
            resolved.model,
            resolved.provider.value,
        )

    return LLMRegistry(clients)


def get_settings() -> Settings:
    """Build a ``Settings`` instance, honouring ``AI_ENV_FILE``.

    If the ``AI_ENV_FILE`` environment variable is set, its value is
    passed as ``_env_file`` so pydantic-settings reads that file.
    Otherwise a plain ``Settings()`` is returned (env vars only).
    """
    env_file = os.getenv("AI_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()
