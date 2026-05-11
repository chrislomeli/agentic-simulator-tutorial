"""
world-simulator.agents.logistics

Logistics agent — runs after the risk agent has flagged a cell as
hazardous and is responsible for *what to do about it*.

Conceptually distinct from the risk agent:
  - Risk agent answers "what is happening here?" (assessment).
  - Logistics agent answers "what do we do about it?" (planning).

The two have different prompts, different available tools, and different
downstream consumers (risk feeds alerts/monitoring, logistics feeds
dispatch/action queues). Keeping them separate keeps each prompt focused
and lets the supervisor route conditionally — most low-risk evaluations
never invoke logistics at all, which keeps token spend in check.

This package is intentionally being built up incrementally. The current
state is:

    tools/   — internal query APIs the logistics LLM can call on demand.
    (graph, nodes, state to follow)

See ``tools/README.md`` for the design of the tools layer.
"""
