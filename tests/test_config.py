"""
Tests for world-simiulator.config

Strategy: never touch the real .env file. Each test sets env vars
directly (monkeypatch) and constructs ``Settings()`` fresh — there is
no module-level cache to clear.
"""

import os

import pytest

from config import Settings


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch):
    """Ensure tests never accidentally load the real .env file.

    Unset AI_ENV_FILE so pydantic-settings reads only from env vars,
    and zero out the credential vars so they don't leak in from the
    developer's environment.
    """
    monkeypatch.delenv("AI_ENV_FILE", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")


class TestSettingsDefaults:
    def test_defaults_are_empty_strings(self):
        s = Settings()
        assert s.anthropic_api_key.get_secret_value() == ""

    def test_tracing_off_by_default(self):
        s = Settings()
        assert s.langchain_tracing_v2 is False

    def test_default_project_name(self):
        s = Settings()
        assert s.langchain_project == "world-simulator"


class TestSettingsFromEnv:
    def test_reads_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
        s = Settings()
        assert s.anthropic_api_key.get_secret_value() == "sk-test-123"

    def test_reads_langchain_tracing(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
        s = Settings()
        assert s.langchain_tracing_v2 is True

    def test_reads_project_name(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_PROJECT", "my-project")
        s = Settings()
        assert s.langchain_project == "my-project"

    def test_ignores_unknown_keys(self, monkeypatch):
        # extra="ignore" — should not raise
        monkeypatch.setenv("SOME_UNRELATED_KEY", "whatever")
        Settings()  # no exception


class TestApplyLangsmith:
    def test_sets_env_vars(self, monkeypatch):
        monkeypatch.setenv("LANGCHAIN_API_KEY", "")
        monkeypatch.setenv("LANGCHAIN_TRACING_V2", "")
        monkeypatch.setenv("LANGCHAIN_PROJECT", "")

        s = Settings(
            langchain_api_key="lsv2-test-key",
            langchain_tracing_v2=True,
            langchain_project="world-simiulator-test",
        )
        s.apply_langsmith()

        assert os.environ["LANGCHAIN_API_KEY"] == "lsv2-test-key"
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_PROJECT"] == "world-simiulator-test"

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
