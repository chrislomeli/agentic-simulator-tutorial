"""
Tests for ogar.config

Strategy: never touch the real .env file.
Each test sets env vars directly (monkeypatch) and clears the lru_cache
so a fresh Settings object is constructed from those vars.
"""

import os
import pytest

from config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear the lru_cache before and after every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    """
    Ensure tests never accidentally load the real .env file.
    Unset AI_ENV_FILE so pydantic-settings reads only from env vars.
    """
    monkeypatch.delenv("AI_ENV_FILE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")


class TestSettingsDefaults:
    def test_defaults_are_empty_strings(self):
        s = Settings()
        assert s.anthropic_api_key == ""

    def test_transport_defaults(self):
        s = Settings()
        assert s.kafka_bootstrap_servers == "localhost:9092"
        assert s.temporal_host == "localhost:7233"

    def test_tracing_off_by_default(self):
        s = Settings()
        assert s.langchain_tracing_v2 is False

    def test_default_project_name(self):
        s = Settings()
        assert s.langchain_project == "ogar"


class TestSettingsFromEnv:
    def test_reads_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        s = Settings()
        assert s.anthropic_api_key == "sk-test-123"

    def test_reads_langchain_tracing(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        s = Settings()
        assert s.langchain_tracing_v2 is True

    def test_reads_kafka_servers(self, monkeypatch):
        monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.svc:9092")
        s = Settings()
        assert s.kafka_bootstrap_servers == "kafka.svc:9092"

    def test_reads_project_name(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_PROJECT", "my-project")
        s = Settings()
        assert s.langchain_project == "my-project"

    def test_ignores_unknown_keys(self, monkeypatch):
        # extra="ignore" — should not raise
        monkeypatch.setenv("SOME_UNRELATED_KEY", "whatever")
        s = Settings()  # no exception
        assert s is not None


class TestApplyLangsmith:
    def test_sets_env_vars(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_API_KEY", "")
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "")
        monkeypatch.setenv("LANGCHAIN_PROJECT", "")

        s = Settings(
            langchain_api_key="lsv2-test-key",
            langchain_tracing_v2=True,
            langchain_project="ogar-test",
        )
        s.apply_langsmith()

        assert os.environ["LANGCHAIN_API_KEY"] == "lsv2-test-key"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_PROJECT"] == "ogar-test"

    def test_does_not_overwrite_existing_env_vars(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_API_KEY", "already-set")

        s = Settings(langchain_api_key="new-key")
        s.apply_langsmith()

        # Should NOT overwrite — the existing value wins
        assert os.environ["LANGCHAIN_API_KEY"] == "already-set"

    def test_skips_empty_values(self, monkeypatch):
        monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

        s = Settings(langchain_api_key="")
        s.apply_langsmith()

        assert "LANGCHAIN_API_KEY" not in os.environ


class TestGetSettings:
    def test_returns_settings_instance(self):
        s = get_settings()
        assert isinstance(s, Settings)

    def test_is_cached(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_returns_fresh_instance(self, monkeypatch):
        s1 = get_settings()
        get_settings.cache_clear()
        monkeypatch.setenv("LANGCHAIN_PROJECT", "fresh")
        s2 = get_settings()
        assert s1 is not s2
        assert s2.langchain_project == "fresh"
