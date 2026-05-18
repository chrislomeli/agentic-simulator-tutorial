"""runtime.entrypoints.local — the collapsed single executable.

Producer + consumer in one process, talking through the in-process
EventQueue, with an in-process GraphClient. This is the ``local`` profile
and the one role that runs end-to-end today.

    python -m runtime.entrypoints.local

Note this still goes producer → queue → consumer → port: collapsing does
not remove the seams, it just binds in-process adapters to them.
"""

from __future__ import annotations

import asyncio
import os

from runtime.entrypoints import bootstrap, install_stop_handlers
from runtime.orchestrator import RuntimeOrchestrator

_TICKS = int(os.getenv("SIM_TICKS", "20"))
_TICK_INTERVAL_SEC = float(os.getenv("SIM_TICK_INTERVAL_SEC", "1.0"))


async def _amain() -> None:
    bundle, queue = bootstrap()
    try:
        orch = RuntimeOrchestrator(
            sensor_inventory=bundle.sensor_inventory,
            engine=bundle.engine,
            graph_client=bundle.graph_client,
            event_queue=queue,
            tick_interval_seconds=_TICK_INTERVAL_SEC,
        )
        install_stop_handlers(orch.stop)
        stats = await orch.run(ticks=_TICKS)
        print(
            f"=== done: {stats.ticks_completed} ticks, "
            f"{stats.events_consumed} events, "
            f"{stats.graph_invocations} graph invocation(s) ==="
        )
    finally:
        bundle.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
