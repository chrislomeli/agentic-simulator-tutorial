# Getting Started: Project Setup

> **What you'll build:** A clean development environment with all dependencies installed and verified.
> **Why you need it:** Before diving into the tutorials, you need a working Python environment with `uv`, LangGraph, and all required packages.
> **What you'll have at the end:** A fully configured project ready to run the tutorial examples from Sessions 01–15.

---

## Prerequisites

**Required:**
- Python 3.11 or 3.12 installed
- Basic familiarity with Python and command-line tools
- A terminal/shell (bash, zsh, or similar)

**Optional (for LLM-powered agents):**
- OpenAI API key (for Sessions 07, 10, and beyond)
- LangSmith account (for tracing and debugging)

---

## What is `uv`?

[`uv`](https://github.com/astral-sh/uv) is a fast Python package installer and resolver written in Rust. It's a drop-in replacement for `pip` and `pip-tools` that's significantly faster and more reliable for dependency management.

**Why we use it:**
- **Fast** — 10-100x faster than pip for installing packages
- **Reliable** — deterministic dependency resolution
- **Simple** — works like pip but better
- **Modern** — supports PEP 621 `pyproject.toml` natively

If you're familiar with `pip`, you already know 90% of `uv`. The main commands are:
- `uv pip install <package>` — install a package
- `uv pip sync requirements.txt` — install exact versions from a lockfile
- `uv venv` — create a virtual environment

---

## Step 1: Install `uv`

### macOS/Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Windows

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Verify installation

```bash
uv --version
```

You should see something like:

```
uv 0.4.x (or later)
```

---

## Step 2: Set up your own repo with tutorial reference

Follow this workflow so you have your own repo while keeping the tutorial code accessible for reference and comparison.

**Step 2a — Create your own GitHub repo**

On GitHub (or your Git platform):
1. Create a new repository (e.g., `wildfire-project`)
2. Initialize with a README (optional)
3. Copy the HTTPS clone URL

**Step 2b — Clone your repo locally**

```bash
git clone <your-repo-url>
cd <your-repo-name>
```

for example, if your repo is `agentic-tutorial` and your git url is `git@github.com:myself/agentic-tutorial.git` then you would type:
```bash
git clone git@github.com:myself/agentic-tutorial.git
cd agentic-tutorial
```



**Step 2c — Add the tutorial repo as a remote**

```bash
git remote add tutorial https://github.com/chrislomeli/agentic-world-simulator.git
git fetch tutorial
```

Now you have two remotes:
- `origin` — your own repo (where you push your work)
- `tutorial` — the reference solution (for comparison and guidance)

**Step 2d — (Optional) Check out tutorial reference branches**

Each session has a tag/branch you can reference:

```bash
# View available sessions
git branch -r --list "tutorial/*"

# Check out a specific session state (puts you in detached HEAD — fine for reference)
git checkout tutorial/session-02
```

**Step 2e — Compare and copy**

Now you can:

- **Inspect the tutorial code:**
  ```bash
  git show tutorial/session-07:src/agents/cluster/agent.py
  ```

- **Diff against your progress:**
  ```bash
  git diff HEAD tutorial/session-02
  ```

- **Copy files when you get stuck:**
  ```bash
  git checkout tutorial/session-02 -- src/domains/wildfire/physics.py
  ```

Go back to your work branch anytime:
```bash
git checkout -
```

---

## Step 3: Set up your `pyproject.toml`

You can copy it from the tutorial repo or create your own. The easiest approach:

**Option A: Copy from the tutorial repo**
(note: you must have added the remote tutorial repository and fetched it)
```bash
git show tutorial/main:pyproject.toml > pyproject.toml
git show tutorial/main:.gitignore > .gitignore
```

**Option B: Create your own**

If you prefer to start fresh, create it in your project root:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "world-simulator"
version = "0.1.0"
description = "Event-driven world simulation engine with LangGraph agent runtime"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [
    {name = "Your Name"}
]
keywords = ["langgraph", "agent", "simulation", "wildfire", "world-engine"]

dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "langgraph>=0.2",
    "langchain-core>=0.3",
]

[project.optional-dependencies]
llm = [
    "langchain-openai>=0.2",
]

[dependency-groups]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/sensors", "src/tools", "src/domains", "src/transport", "src/bridge", "src/world", "src/agents", "src/resources"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
asyncio_mode = "auto"
pythonpath = ["src"]
```

**Key dependencies explained:**

- **`pydantic`** — Data validation and settings management (used for all state models)
- **`pydantic-settings`** — Environment variable configuration
- **`langgraph`** — LangChain's graph-based agent framework (core of the agent runtime)
- **`langchain-core`** — LangChain primitives (tools, messages, runnables)
- **`langchain-openai`** — OpenAI LLM integration (optional, only needed for LLM-powered agents)

---

## Step 4: Create a virtual environment

```bash
uv venv
```

This creates a `.venv` directory with an isolated Python environment.

**Activate the virtual environment:**

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows:**
```powershell
.venv\Scripts\activate
```

You should see `(.venv)` in your terminal prompt.

---

## Step 5: Install dependencies

### Core dependencies (required for all sessions)

```bash
uv pip install -e .
```

This installs the project in editable mode with all core dependencies.

### LLM dependencies (needed for Sessions 07, 10+)

```bash
uv pip install -e ".[llm]"
```

This adds `langchain-openai` for GPT-4 integration.

### Development dependencies (optional, for testing)

```bash
uv pip install --group dev
```

This adds `pytest`, `pytest-asyncio`, and `pytest-cov`.

---

## Step 6: Verify installation

Create a simple test script to verify everything works:

**`verify_setup.py`:**

```python
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
```

Run it:

```bash
python verify_setup.py
```

Expected output:

```
Checking core dependencies...

✓ pydantic installed
✓ pydantic-settings installed
✓ langgraph installed
✓ langchain-core installed

Checking optional dependencies...

✓ langchain-openai (for LLM agents) installed
✓ pytest (for testing) installed

==================================================
✓ Core setup complete! Ready to start tutorials.

Next steps:
  1. Set OPENAI_API_KEY if using LLM agents
  2. Start with Session 01: World Engine and Grid
```

---

## Step 7: Configure environment variables (for LLM sessions)

**When you need this:** Sessions 07, 10, and beyond use LLM-powered agents. Sessions 01–06 work without any API keys (they use stub/deterministic agents).

The project uses `pydantic-settings` to manage configuration. It reads from a `.env` file pointed to by the `AI_ENV_FILE` environment variable.

**Step 7a — Create your `.env` file**

Create a `.env` file in your project root (never commit this file):

```bash
# LLM credentials (required for Sessions 07+)
OPENAI_API_KEY=sk-...

# LangSmith tracing (optional, for debugging agent runs)
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=wildfire-simulation
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

**Step 7b — Point `AI_ENV_FILE` at it**

Add this to your shell profile (`~/.zshrc` or `~/.bashrc`) so it persists across sessions:

```bash
export AI_ENV_FILE=/path/to/your/wildfire-project/.env
```

Then reload your shell:

```bash
source ~/.zshrc  # or ~/.bashrc
```

**Step 7c — Verify `.env` is in `.gitignore`**

```bash
grep -q "^\.env" .gitignore || echo ".env" >> .gitignore
```

---

## Step 8: Verify API key setup (for LLM sessions)

Before running LLM-powered sessions, verify your configuration loads correctly via `get_settings()`.

**`verify_api_key.py`:**

```python
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
```

Run it:

```bash
python verify_api_key.py
```

**Expected output (if configured):**

```
Checking API key configuration...

✓ AI_ENV_FILE set and file exists (/path/to/project/.env)

✓ OPENAI_API_KEY loaded (sk-proj-ab...)
✓ LangSmith tracing enabled (project: wildfire-simulation)

✓ API key verified (test call successful)
  Response: API key works

==================================================
✓ Ready for LLM-powered sessions!
```

**Expected output (if not configured):**

```
Checking API key configuration...

✗ AI_ENV_FILE not set
  Add this to your shell profile and reload:
    export AI_ENV_FILE=/path/to/your/project/.env

==================================================
✗ Fix AI_ENV_FILE before continuing
```

---

## Step 9: Create initial project structure

Create core modules and placeholder `__init__.py` files to make directories importable:

We are not really using all of these folders, so you could create them as you need them, but the tutorials will assume they are already there. 

```bash
# Core modules
mkdir -p src/{world,sensors,transport,bridge,agents/{cluster,supervisor},domains/wildfire,tools,resources}
mkdir -p tests

touch src/__init__.py
touch src/world/__init__.py
touch src/sensors/__init__.py
touch src/transport/__init__.py
touch src/bridge/__init__.py
touch src/agents/__init__.py
touch src/agents/cluster/__init__.py
touch src/agents/supervisor/__init__.py
touch src/domains/__init__.py
touch src/domains/wildfire/__init__.py
touch src/tools/__init__.py
touch src/resources/__init__.py

touch tests/__init__.py
```

**Verify imports work:**

```bash
python -c "import sys; sys.path.insert(0, 'src'); import world; import sensors; print('✓ All modules importable')"
```

---

## Common Issues

### Issue: `uv: command not found`

**Solution:** Make sure `uv` is in your PATH. Try closing and reopening your terminal, or run:

```bash
source ~/.bashrc  # or ~/.zshrc on macOS
```

### Issue: `ModuleNotFoundError: No module named 'pydantic'`

**Solution:** Make sure your virtual environment is activated:

```bash
source .venv/bin/activate  # macOS/Linux
.venv\Scripts\activate     # Windows
```

Then reinstall:

```bash
uv pip install -e .
```

### Issue: `ImportError: cannot import name 'BaseModel' from 'pydantic'`

**Solution:** You might have an old version of Pydantic. Upgrade:

```bash
uv pip install --upgrade pydantic
```

### Issue: LangGraph version conflicts

**Solution:** Make sure you have compatible versions:

```bash
uv pip install --upgrade langgraph langchain-core
```

---

## What you've built

At this point you have:

✅ **`uv` installed** — fast, modern Python package manager  
✅ **Virtual environment** — isolated Python environment in `.venv`  
✅ **Core dependencies** — Pydantic, LangGraph, LangChain  
✅ **Project structure** — organized `src/` directory with modules  
✅ **Verified setup** — all imports working  
✅ **Optional: LLM integration** — OpenAI API key configured  
✅ **Optional: Development tools** — pytest for testing  

You're ready to start building! Head to **Session 01: World Engine and Grid** to begin.

---

## Quick reference: Common `uv` commands

```bash
# Create virtual environment
uv venv

# Install package
uv pip install <package>

# Install from pyproject.toml
uv pip install -e .

# Install with optional dependencies
uv pip install -e ".[llm]"

# Install development dependencies
uv pip install --group dev

# Upgrade all packages
uv pip install --upgrade -e .

# List installed packages
uv pip list

# Freeze dependencies to requirements.txt
uv pip freeze > requirements.txt

# Install from requirements.txt
uv pip sync requirements.txt
```

---

*Next: Session 01 — World Engine and Grid. You'll build the foundation: a grid-based world with fire spread physics.*
