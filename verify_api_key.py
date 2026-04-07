#!/usr/bin/env python3
"""Verify that API keys are loading correctly via pydantic-settings."""

import os
import sys

def check_env_file():
    """Check that AI_ENV_FILE is set and the file exists."""
    env_file = os.getenv("AI_ENV_FILE")
    if not env_file:
        print("✗ AI_ENV_FILE not set")
        print("  Add this to your shell profile and reload:")
        print("    export AI_ENV_FILE=/path/to/your/project/.env")
        return False
    if not os.path.exists(env_file):
        print(f"✗ .env file not found at: {env_file}")
        print("  Create the file or update AI_ENV_FILE to point at the right path")
        return False
    print(f"✓ AI_ENV_FILE set and file exists ({env_file})")
    return True

def check_settings():
    """Load settings directly via pydantic-settings and verify required keys."""
    try:
        from pydantic_settings import BaseSettings, SettingsConfigDict

        class VerifySettings(BaseSettings):
            openai_api_key: str = ""
            langchain_api_key: str = ""
            langchain_tracing_v2: bool = False
            langchain_project: str = "ogar"
            model_config = SettingsConfigDict(
                env_file=os.getenv("AI_ENV_FILE"),
                env_file_encoding="utf-8",
                extra="ignore",
            )

        settings = VerifySettings()
    except ImportError:
        print("✗ pydantic-settings not installed (run: uv pip install -e .)")
        return False

    ok = True

    if settings.openai_api_key:
        print(f"✓ OPENAI_API_KEY loaded ({settings.openai_api_key[:10]}...)")
    else:
        print("✗ OPENAI_API_KEY not set in .env (required for Sessions 07+)")
        ok = False

    if settings.langchain_api_key and settings.langchain_tracing_v2:
        print(f"✓ LangSmith tracing enabled (project: {settings.langchain_project})")
    else:
        print("ℹ LangSmith tracing not configured (optional)")

    return ok, settings

def check_api_call(settings):
    """Optionally make a live API call to confirm the key works."""
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=settings.openai_api_key)
        response = llm.invoke("Say 'API key works'")
        print(f"✓ API key verified (test call successful)")
        print(f"  Response: {response.content}")
        return True
    except ImportError:
        print("ℹ langchain-openai not installed — skipping live test (run: uv pip install -e '.[llm]')")
        return True
    except Exception as e:
        err = str(e)
        if "429" in err or "insufficient_quota" in err or "rate limit" in err.lower():
            print("⚠ API key is set but quota exceeded or rate limited")
            print("  Check your OpenAI plan and billing at https://platform.openai.com/account/billing")
            print("  Your key is likely valid — this won't block Sessions 01-06")
            return True  # key loaded correctly, billing issue is separate
        print(f"✗ API call failed: {e}")
        return False

def main():
    print("Checking API key configuration...\n")

    if not check_env_file():
        print("\n" + "="*50)
        print("✗ Fix AI_ENV_FILE before continuing")
        return 1

    print()
    settings_ok, settings = check_settings()
    print()
    api_ok = check_api_call(settings) if settings_ok else False

    print("\n" + "="*50)
    if settings_ok and api_ok:
        print("✓ Ready for LLM-powered sessions!")
        return 0
    else:
        print("✗ Fix the issues above before running LLM sessions")
        print("  (Sessions 01-06 work without API keys)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
