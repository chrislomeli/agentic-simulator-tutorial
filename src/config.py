"""
ogar.config

Centralised settings for the OGAR testbed.

Loading order (pydantic-settings resolves in this priority, highest first):
  1. Actual environment variables  (e.g. injected by K8s)
  2. .env file pointed to by AI_ENV_FILE  (local dev)
  3. Default values defined below

Usage
─────
  from ogar.config import get_settings

  settings = get_settings()
  key = settings.anthropic_api_key

  # Apply LangSmith env vars so LangGraph picks them up automatically:
  settings.apply_langsmith()

Deployment modes
────────────────
  Local dev  — set AI_ENV_FILE=/path/to/.env  (or export vars directly)
  K8s        — leave AI_ENV_FILE unset; inject vars via ConfigMap / Secret
               No .env file is read; pydantic-settings falls back to env vars only.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from functools import lru_cache
from typing import Any, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from enum import Enum

logger = logging.getLogger(__name__)

class LLMProvider(Enum):
    STUB = "STUB"
    ANTHROPIC = "ANTHROPIC"
    OPENAI = "OPENAI"

class LLMLabel(Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    GPT_MINI = "gpt-mini"
    GPT_NANO = "gpt-nano"
    GPT = "gpt"
    STUB = "STUB"

@dataclasses.dataclass
class LLMModel:
    model: str
    key_label: str
    provider: LLMProvider
    api_key: Optional[str] = None


class Settings(BaseSettings):
    # ── LLM credentials ───────────────────────────────────────────────────────
    llm_source: LLMProvider = LLMProvider.STUB
    llm_model: Optional[LLMModel] = None
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    world_data: str = "src/domains/wildfire/scenario_data/north_south_fire.json"

    @property
    def selected_model(self) -> Optional[LLMModel]:
        if self.llm_model is None:
            return None
        connection = dataclasses.replace(self.llm_model)
        connection.api_key = getattr(self, connection.key_label, "") or None
        return connection

    # ── LangSmith / LangChain tracing ─────────────────────────────────────────
    # pydantic-settings reads LANGCHAIN_API_KEY, LANGCHAIN_TRACING_V2, etc.
    # from env vars (or the .env file) automatically — field names map 1-to-1.
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "ogar"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    model_config = SettingsConfigDict(
        # AI_ENV_FILE=/path/to/.env for local dev.
        # Unset (None) on K8s — pydantic-settings skips file loading entirely
        # and reads from environment variables only.
        env_file=os.getenv("AI_ENV_FILE"),
        env_file_encoding="utf-8",
        # Silently ignore keys in the .env file that are not defined above.
        # Useful because the shared .env may contain keys for other projects.
        extra="ignore",
    )

    def apply_langsmith(self) -> None:
        """
        Write LangSmith settings into os.environ so LangGraph picks them up.

        LangGraph reads LANGCHAIN_* env vars at import time in some cases,
        so call this as early as possible — before importing langgraph or
        langchain modules — if you want tracing enabled.

        Only sets vars that have non-empty values to avoid overwriting
        vars already present in the environment.
        """
        pairs = {
            "LANGCHAIN_API_KEY": self.langchain_api_key,
            "LANGCHAIN_TRACING_V2": "true" if self.langchain_tracing_v2 else "",
            "LANGCHAIN_PROJECT": self.langchain_project,
            "LANGCHAIN_ENDPOINT": self.langchain_endpoint,
        }
        for key, value in pairs.items():
            if value and not os.environ.get(key):
                os.environ[key] = value


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    The cache means the .env file is read once per process.
    In tests, call get_settings.cache_clear() before patching env vars
    so a fresh Settings object is created.
    """
    return Settings()


# ── LLM Registry ──────────────────────────────────────────────────────────────

class LLMRegistry:
    """
    Role-based catalog of LangChain chat models.

    Built once at startup and threaded into graph builders. Nodes request
    a model by role ("classifier", "supervisor") without knowing which
    provider or model was configured.

    Usage:
        registry = build_llm_registry(settings, {"classifier": classifier_model_cfg})
        llm = registry.get("classifier")
        result = llm.invoke(messages)
    """

    def __init__(self, clients: dict[str, Any]) -> None:
        self._clients = clients

    def get(self, role: str) -> Any:
        client = self._clients.get(role)
        if client is not None:
            return client
        fallback = self._clients.get("classifier")
        if fallback is not None:
            logger.warning("No LLM for role %r — falling back to 'classifier'", role)
            return fallback
        raise KeyError(
            f"No LLM registered for role {role!r} and no 'classifier' fallback."
        )

    @property
    def roles(self) -> list[str]:
        return sorted(self._clients)


def _build_chat_model(model_cfg: LLMModel) -> Any:
    """Instantiate a LangChain chat model from an LLMModel config."""
    if model_cfg.provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_cfg.model, temperature=0, api_key=model_cfg.api_key)
    elif model_cfg.provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model_name=model_cfg.model, api_key=model_cfg.api_key, temperature=0)
    elif model_cfg.provider == LLMProvider.STUB:
        return None
    else:
        raise ValueError(f"Unknown provider: {model_cfg.provider}")


def build_llm_registry(
    settings: Settings,
    role_models: dict[str, LLMModel],
) -> LLMRegistry:
    """
    Build an LLMRegistry from a role → LLMModel mapping.

    API keys are resolved from settings at build time. STUB provider
    roles are skipped — nodes must guard against registry.get() returning
    None when running in stub mode.

    Example:
        registry = build_llm_registry(settings, {
            "classifier": LLMModel(
                model="claude-haiku-4-5-20251001",
                key_label="anthropic_api_key",
                provider=LLMProvider.ANTHROPIC,
            ),
        })
    """
    clients: dict[str, Any] = {}
    for role, model_cfg in role_models.items():
        resolved = dataclasses.replace(model_cfg)
        resolved.api_key = getattr(settings, resolved.key_label, "") or None
        if resolved.provider == LLMProvider.STUB:
            logger.info("Skipping role %r — STUB provider", role)
            continue
        chat_model = _build_chat_model(resolved)
        if chat_model is not None:
            clients[role] = chat_model
            logger.info("Registered LLM for role %r → %s (%s)", role, resolved.model, resolved.provider.value)
    return LLMRegistry(clients)


