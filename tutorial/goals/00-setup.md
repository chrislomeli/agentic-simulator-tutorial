# 00 — Setup

## Teaching goal
Student has a working environment and knows how to run the test suite.

## I/O
- In: bare clone, Python 3.11+
- Out: active `.venv`, all deps installed, `pytest tests/world/ tests/domains/ tests/sensors/ tests/transport/ -v` passes

## Must cover
- [ ] Why uv (vs pip)
- [ ] `uv venv` + `source .venv/bin/activate`
- [ ] `uv pip install -e ".[llm]" --group dev`
- [ ] Adding the tutorial remote and `git checkout tutorial/main -- src/...`
- [ ] Optional: OPENAI_API_KEY, LANGCHAIN_API_KEY for later sessions
- [ ] What "stub mode" means — everything works without an API key
