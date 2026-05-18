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
from enum import Enum
from typing import Any

from pydantic import SecretStr

from config import Settings
from llm.token_callback import TokenUsageCallback

logger = logging.getLogger(__name__)


# ── Provider / label enums ────────────────────────────────────────────────────


class LLMProvider(Enum):
    STUB = "STUB"
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    OLLAMA = "OLLAMA"
    BEDROCK = "BEDROCK"


class LLMLabel(Enum):
    HAIKU = "haiku"
    SONNET = "sonnet"
    OPUS = "opus"
    GPT_MINI = "gpt-mini"
    GPT = "gpt"
    OLLAMA_LLAMA3 = "ollama-llama3"
    BEDROCK_SONNET = "bedrock-sonnet"
    BEDROCK_HAIKU = "bedrock-haiku"
    STUB = "STUB"


# ── Model config ──────────────────────────────────────────────────────────────


@dataclasses.dataclass
class LLMModel:
    model: str
    provider: LLMProvider
    # Settings attribute holding the API key. Only meaningful for
    # single-key providers (OpenAI/Anthropic). None for Ollama (endpoint)
    # and Bedrock (AWS credential chain). All catalog entries below use
    # keyword args, so field order is free to change.
    key_label: str | None = None
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
    # AWS Bedrock — Claude via the Converse API. No key_label: auth is the
    # AWS credential chain (see Settings.aws_region / aws_profile).
    # NOTE: depending on region/account these may need an inference-profile
    # ID/ARN (e.g. "us.anthropic.claude-3-5-sonnet-...") rather than the
    # bare on-demand model ID below.
    LLMLabel.BEDROCK_SONNET: LLMModel(
        provider=LLMProvider.BEDROCK,
        model="anthropic.claude-3-5-sonnet-20240620-v1:0",
    ),
    LLMLabel.BEDROCK_HAIKU: LLMModel(
        provider=LLMProvider.BEDROCK,
        model="anthropic.claude-3-5-haiku-20241022-v1:0",
    ),
    # Stub — no LLM
    LLMLabel.STUB: None,
}


# ── Role → model label mapping ────────────────────────────────────────────────
# Maps agent role → LLMLabel. This is the SINGLE source of truth: the
# composition root (main.py) builds the registry from this dict. Change a
# label here to swap the model for that role everywhere.
#
# Only roles that are actually consumed via llm_registry.get(<role>) belong
# here — listing a role nothing requests is just a lie waiting to mislead.
# Consumers today:
#   - "classifier"        : cluster agent  (agents/cluster/nodes.py)
#   - "logistics"         : logistics ReAct loop, Phase 1 (agents/logistics/nodes.py)
#   - "logistics_extract" : logistics structured extraction, Phase 2 (same file)
#
# Phases 1 and 2 are deliberately separate roles so the structured-output
# pass can use a different model than the tool-calling loop without touching
# code — see make_extract_plan_node. They point at the same label for now.

LLM_ROLE_CONFIG: dict[str, LLMLabel] = {
    "classifier": LLMLabel.GPT_MINI,        # fast sensor pattern recognition
    "logistics": LLMLabel.GPT_MINI,         # ReAct tool-calling loop
    "logistics_extract": LLMLabel.GPT_MINI,  # transcript → LogisticsAssessment
}


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

    def __init__(
        self,
        clients: dict[str, Any],
        callbacks: dict[str, TokenUsageCallback] | None = None,
    ) -> None:
        self._clients = clients
        self._callbacks = callbacks or {}

    def get(self, role: str, default: str | None = None) -> Any:
        client = self._clients.get(role, default)
        if client is not None:
            return client
        raise KeyError(f"No LLM registered for role {role!r}.")

    @property
    def roles(self) -> list[str]:
        return sorted(self._clients)

    def usage_report(self) -> list[dict]:
        """Return per-role token usage totals accumulated since registry was built."""
        return [cb.report() for cb in self._callbacks.values()]


def _resolve_provider_kwargs(model_cfg: LLMModel, settings: Settings) -> dict[str, Any]:
    """Resolve provider-specific construction kwargs from Settings.

    This is the credential seam. It is the only place that knows how a
    provider authenticates, so the role-based registry and every node
    above it stay provider-agnostic:

      - OpenAI / Anthropic : a single API key from a Settings attribute.
      - Ollama             : a base URL (no credential).
      - Bedrock            : the AWS credential chain — region/profile are
                             optional overrides; omitting them lets boto3
                             fall back to env / shared config / IAM role.

    Returns kwargs ready to splat into the LangChain chat-model ctor.
    """
    provider = model_cfg.provider

    if provider in (LLMProvider.OPENAI, LLMProvider.ANTHROPIC):
        raw = getattr(settings, model_cfg.key_label, None) if model_cfg.key_label else None
        api_key = raw.get_secret_value() if isinstance(raw, SecretStr) else raw
        return {"api_key": api_key or None}

    if provider == LLMProvider.OLLAMA:
        return {"base_url": settings.ollama_base_url}

    if provider == LLMProvider.BEDROCK:
        kwargs: dict[str, Any] = {}
        if settings.aws_region:
            kwargs["region_name"] = settings.aws_region
        if settings.aws_profile:
            kwargs["credentials_profile_name"] = settings.aws_profile
        return kwargs

    raise ValueError(f"Unknown provider: {provider}")


def _build_chat_model(
    model_cfg: LLMModel,
    provider_kwargs: dict[str, Any],
    callback: TokenUsageCallback | None = None,
) -> Any:
    """Instantiate a LangChain chat model from a resolved LLMModel.

    ``provider_kwargs`` comes from :func:`_resolve_provider_kwargs` — this
    function only knows which LangChain class maps to which provider, not
    how that provider authenticates.
    """
    callbacks = [callback] if callback is not None else []

    if model_cfg.provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_cfg.model, temperature=0, callbacks=callbacks, **provider_kwargs
        )
    elif model_cfg.provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=model_cfg.model, temperature=0, callbacks=callbacks, **provider_kwargs
        )
    elif model_cfg.provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model_cfg.model, temperature=0, callbacks=callbacks, **provider_kwargs
        )
    elif model_cfg.provider == LLMProvider.BEDROCK:
        try:
            from langchain_aws import ChatBedrockConverse
        except ImportError as exc:  # pragma: no cover - exercised only when Bedrock is selected
            raise RuntimeError(
                "Bedrock provider selected but 'langchain-aws' is not installed. "
                "Add langchain-aws to enable Bedrock — no other code change is needed."
            ) from exc

        return ChatBedrockConverse(
            model=model_cfg.model, temperature=0, callbacks=callbacks, **provider_kwargs
        )
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
    callbacks: dict[str, TokenUsageCallback] = {}

    for role, label in role_config.items():
        model_cfg = model_catalog.get(label)
        if model_cfg is None:
            logger.info("Skipping role %r — STUB label", role)
            continue

        provider_kwargs = _resolve_provider_kwargs(model_cfg, settings)
        callback = TokenUsageCallback(role)
        chat_model = _build_chat_model(model_cfg, provider_kwargs, callback)
        clients[role] = chat_model
        callbacks[role] = callback
        logger.info(
            "Registered LLM for role %r → %s (%s)",
            role,
            model_cfg.model,
            model_cfg.provider.value,
        )

    return LLMRegistry(clients, callbacks)
