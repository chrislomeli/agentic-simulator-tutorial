#!/usr/bin/env python3
"""Verify that all required packages are installed."""

import sys

def check_import(module_name, package_name=None):
    """Try to import a module and report success/failure."""
    package_name = package_name or module_name
    try:
        __import__(module_name)
        print(f"✓ {package_name} installed")
        return True
    except ImportError:
        print(f"✗ {package_name} NOT installed")
        return False

def main():
    print("Checking core dependencies...\n")
    
    checks = [
        ("pydantic", "pydantic"),
        ("pydantic_settings", "pydantic-settings"),
        ("langgraph", "langgraph"),
        ("langchain_core", "langchain-core"),
    ]
    
    all_ok = all(check_import(mod, pkg) for mod, pkg in checks)
    
    print("\nChecking optional dependencies...\n")
    
    optional_checks = [
        ("langchain_openai", "langchain-openai (for LLM agents)"),
        ("pytest", "pytest (for testing)"),
    ]
    
    for mod, pkg in optional_checks:
        check_import(mod, pkg)
    
    print("\n" + "="*50)
    if all_ok:
        print("✓ Core setup complete! Ready to start tutorials.")
        print("\nNext steps:")
        print("  1. Set OPENAI_API_KEY if using LLM agents")
        print("  2. Start with Session 01: World Engine and Grid")
        return 0
    else:
        print("✗ Setup incomplete. Install missing packages.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
