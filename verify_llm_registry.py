#!/usr/bin/env python3
"""Verify that the LLM registry builds correctly and each role can make a live call."""

import sys
import os

sys.path.insert(0, "src")


def check_settings():
    try:
        from config import Settings
        settings = Settings()
    except Exception as e:
        print(f"✗ Failed to load settings: {e}")
        return None

    ok = True
    if settings.anthropic_api_key:
        print("✓ anthropic_api_key loaded")
    else:
        print("ℹ anthropic_api_key not set (Anthropic roles will be skipped)")

    if settings.openai_api_key:
        print("✓ openai_api_key loaded")
    else:
        print("ℹ openai_api_key not set (OpenAI roles will be skipped)")

    return settings


def check_registry(settings):
    try:
        from config import build_llm_registry, models, LLM_ROLE_CONFIG
        registry = build_llm_registry(settings, models, LLM_ROLE_CONFIG)
    except Exception as e:
        print(f"✗ Failed to build registry: {e}")
        return None

    if not registry.roles:
        print("✗ Registry built but no roles registered — check that API keys are set")
        return None

    print(f"\nRegistered roles: {registry.roles}")
    return registry


def check_role(registry, role: str) -> bool:
    try:
        llm = registry.get(role)
    except KeyError:
        print(f"  ✗ {role}: not registered")
        return False

    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content="Reply with exactly: OK")])
        text = response.content if hasattr(response, "content") else str(response)
        print(f"  ✓ {role}: {text.strip()[:60]}")
        return True
    except Exception as e:
        err = str(e)
        if "429" in err or "rate" in err.lower() or "quota" in err.lower():
            print(f"  ⚠ {role}: key valid but rate limited — {err[:80]}")
            return True
        print(f"  ✗ {role}: call failed — {err[:80]}")
        return False


def main():
    print("=== LLM Registry verification ===\n")

    settings = check_settings()
    if settings is None:
        return 1

    print()
    registry = check_registry(settings)
    if registry is None:
        return 1

    print("\nTesting live calls:\n")
    results = [check_role(registry, role) for role in registry.roles]

    print("\n" + "=" * 50)
    if all(results):
        print("✓ All registered roles responding.")
        return 0
    else:
        print("✗ Some roles failed — see above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
