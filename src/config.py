"""
ogar.config

Centralised settings for the OGAR testbed.

Loading order (pydantic-settings resolves in this priority, highest first):
  1. Actual environment variables  (e.g. injected by K8s)
  2. .env file pointed to by AI_ENV_FILE  (local dev)
  3. Default values defined below

Usage
─────
  from config import Settings

  settings = Settings(_env_file=os.getenv("AI_ENV_FILE"))
  key = settings.anthropic_api_key
  settings.apply_langsmith()

Settings is constructed once at the composition root and threaded down
into anything that needs it. There is deliberately no module-level
cached singleton — it makes tests harder, breaks in multi-process
deployments, and hides the dependency from callers.

Deployment modes
────────────────
  Local dev  — set AI_ENV_FILE=/path/to/.env  (or export vars directly)
  K8s        — leave AI_ENV_FILE unset; inject vars via ConfigMap / Secret
               No .env file is read; pydantic-settings falls back to env vars only.
"""

from __future__ import annotations

import dataclasses
import os
from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict

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
    api_key: str | None = None


class Settings(BaseSettings):
    # ── LLM credentials ───────────────────────────────────────────────────────
    llm_source: LLMProvider = LLMProvider.STUB
    llm_model: LLMModel | None = None
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    world_data: str = "src/domains/wildfire/scenario_data/north_south_fire.json"

    @property
    def selected_model(self) -> LLMModel | None:
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
        # env_file is intentionally NOT set here — pass _env_file= at
        # construction time so each caller controls which file to load.
        # Tests construct Settings() without any .env interference.
        env_file_encoding="utf-8",
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



