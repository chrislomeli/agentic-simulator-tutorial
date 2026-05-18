"""runtime.entrypoints — one process per role (one container = one entrypoint).

Each module here is a thin ``python -m runtime.entrypoints.<role>`` shim.
They own no wiring — they call the deployment-profile builder and run a
single role:

  local     — collapsed: producer + consumer in one process (the single
              executable; the fully runnable profile today).
  producer  — sensors → EventQueue only.
  consumer  — EventQueue → GraphClient port only.

Which adapter sits behind each seam (queue, graph client, store) is the
*profile's* decision, not the entrypoint's. Splitting vs. collapsing roles
is a deployment choice; this code is identical across every profile —
that is the whole point of the seam work.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable

from config import get_settings
from logging_config import configure_logging
from runtime.profiles import RuntimeBundle, build_event_queue, build_runtime
from world.transport import EventQueue


def bootstrap() -> tuple[RuntimeBundle, EventQueue]:
    """Configure logging, read the profile, and build the runtime + queue.

    Every entrypoint starts here, so the only thing that differs between
    roles is *which part* of the bundle they run. The queue is built from
    the same profile so a split producer and consumer agree on the seam.
    """
    configure_logging(level=logging.INFO)
    settings = get_settings()
    bundle = build_runtime(settings)
    queue = build_event_queue(settings)
    print(f"=== deployment profile: {bundle.profile.value} ===")
    return bundle, queue


def install_stop_handlers(stop: Callable[[], None]) -> None:
    """Wire SIGINT/SIGTERM to a cooperative stop.

    Containers are stopped with SIGTERM; honouring it means the role
    drains in-flight work instead of being killed mid-trigger.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            # add_signal_handler is unavailable on some platforms (e.g.
            # Windows); the cooperative stop just won't be signal-driven.
            pass
