"""runtime.entrypoints.producer — the producer role, alone.

Ticks the world and emits sensor events onto the EventQueue. Nothing
else: it does not fold state and does not call the graph.

    python -m runtime.entrypoints.producer

Under the ``local``/``docker-compose`` profiles the queue is in-process
(only meaningful collapsed — use the ``local`` entrypoint there). Under
``k8s-*``/``aws`` the queue is the broker adapter and this is its own
container; until the broker step lands, ``queue.put`` raises a clear
NotImplementedError pointing at where the real client goes. The seam is
real and wired; only the transport body is deferred.
"""

from __future__ import annotations

import asyncio
import os

from runtime.entrypoints import bootstrap, install_stop_handlers
from runtime.orchestrator import default_sampler
from world.sensors import SensorPublisher

_TICKS = int(os.getenv("SIM_TICKS", "20"))
_TICK_INTERVAL_SEC = float(os.getenv("SIM_TICK_INTERVAL_SEC", "1.0"))
_LOCATION_COUNT = (
    int(os.environ["SIM_LOCATION_COUNT"]) if os.getenv("SIM_LOCATION_COUNT") else None
)


async def _amain() -> None:
    bundle, queue = bootstrap()
    try:
        publisher = SensorPublisher(
            inventory=bundle.sensor_inventory,
            queue=queue,
            tick_interval_seconds=_TICK_INTERVAL_SEC,
            engine=bundle.engine,
            sampler=default_sampler,
        )
        install_stop_handlers(publisher.stop)
        await publisher.run(ticks=_TICKS, location_count=_LOCATION_COUNT)
        print(f"=== producer done: {publisher.ticks_completed} ticks ===")
    finally:
        bundle.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
