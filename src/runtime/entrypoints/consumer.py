"""runtime.entrypoints.consumer — the consumer role, alone.

Reads events off the EventQueue and forwards them through the GraphClient
port. Owns no world state — the facade behind the port folds onto the
immutable seed.

    python -m runtime.entrypoints.consumer

Runs until SIGINT/SIGTERM (no local producer to signal "done", so there
is no ``drain_until``). Under ``k8s-*``/``aws`` the queue is the broker
adapter and the graph client is the HTTP/AgentCore adapter — both real,
wired seams that raise a clear NotImplementedError until the broker/API
steps land. Under ``local`` use the ``local`` entrypoint instead (a
lone consumer has nothing feeding its in-process queue).
"""

from __future__ import annotations

import asyncio

from runtime.entrypoints import bootstrap, install_stop_handlers
from runtime.orchestrator import EventConsumer


async def _amain() -> None:
    bundle, queue = bootstrap()
    try:
        consumer = EventConsumer(
            queue=queue,
            graph_client=bundle.graph_client,
        )
        install_stop_handlers(consumer.stop)
        stats = await consumer.run()  # until stop(); no producer to drain
        print(
            f"=== consumer done: {stats.events_consumed} events, "
            f"{stats.graph_invocations} graph invocation(s) ==="
        )
    finally:
        bundle.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
