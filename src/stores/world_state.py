"""stores.world_state — the "end the event flow" write seam.

The graph side rebuilds the live world by folding sensor events onto an
**immutable seed** loaded from the DB (snapshot + event replay — the
introductory form of an event-sourced CQRS read model). The seed is never
mutated, which is *why the same scenario replays identically every run*.

In a real product the consumer/graph would also persist the evolved world
back to a store so other readers see it. That write is intentionally
**not done here** — and it is not hidden: it is this named, Protocol-shaped
seam with a logging no-op default. A reader sees exactly where the
production write belongs and why it is deliberately absent in this cut.

Swapping in a real ``PostgresWorldStateWriter`` later touches only this
file; nothing that calls ``WorldStateWriter`` changes.

Teaching note: the graph pod is therefore stateful across triggers (its
in-memory world accumulates). That is the expected shape for a
single-writer read model. Scaling to N graph pods would require a shared
store or per-request replay — that is the boundary, named not hidden.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class WorldStateWriter(Protocol):
    """Persist the cells that changed after an event fold ("end the flow").

    Ordering contract (CQRS): the write must complete *before* the graph
    is triggered, so a separate reader observing the store sees a
    consistent world. The logging stub satisfies this trivially.
    """

    def write(self, *, correlation_id: str, changed_cells: set[tuple[int, int]]) -> None: ...


class LoggingWorldStateWriter:
    """No-op writer — the immutable-seed binding of ``WorldStateWriter``.

    Logs what *would* be persisted, then does nothing, so scenarios stay
    byte-for-byte reproducible. This is the deliberate tutorial cut; the
    seam is real so the production writer is a drop-in.
    """

    def write(self, *, correlation_id: str, changed_cells: set[tuple[int, int]]) -> None:
        logger.info(
            "WorldStateWriter(stub): trigger %s would persist %d changed cell(s) "
            "— skipped (seed is immutable in this profile)",
            correlation_id,
            len(changed_cells),
        )
