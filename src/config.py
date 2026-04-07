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

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── LLM credentials ───────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── LangSmith / LangChain tracing ─────────────────────────────────────────
    # pydantic-settings reads LANGCHAIN_API_KEY, LANGCHAIN_TRACING_V2, etc.
    # from env vars (or the .env file) automatically — field names map 1-to-1.
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "ogar"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    # ── Transport ─────────────────────────────────────────────────────────────
    # Defaults point at local dev instances; override in K8s via env vars.
    kafka_bootstrap_servers: str = "localhost:9092"
    temporal_host: str = "localhost:7233"

    # ── Database (future — Postgres checkpointer / pgvector) ─────────────────
    database_url: str = ""

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