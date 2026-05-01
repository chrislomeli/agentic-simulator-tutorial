"""
ogar.agents.cluster.node_tracer

Per-node timing and structured logging decorator.

@node_trace wraps any LangGraph node function (sync or async) and
automatically emits a structlog record with:
  - node name
  - session_id (pulled from state, works across state types)
  - elapsed_ms (wall-clock time)
  - status (from the returned state dict)
  - error_message (if status is ERROR)

The decorator is transparent — it doesn't modify the node's behavior,
only instruments it. Works with structlog's stdlib bridge so the records
are JSON and queryable in log aggregators.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from functools import wraps
from time import perf_counter
from typing import Any, Union

import structlog

from src.agents.cluster.state import StatusValue

logger = structlog.get_logger(__name__)

# ── Node tracing decorator ───────────────────────────────────────────────────


def _log_result(name: str, elapsed: float, session_id: str, result: dict | None) -> None:
    """Shared logging for both sync and async wrappers."""
    status = result.get("status") if isinstance(result, dict) else None
    elapsed_ms = round(elapsed * 1000)
    if status == StatusValue.ERROR:
        logger.error(
            "node completed with error",
            node=name,
            session_id=session_id,
            elapsed_ms=elapsed_ms,
            status=str(status),
            error_message=result.get("error_message") if isinstance(result, dict) else None,
        )
    else:
        logger.info(
            "node completed",
            node=name,
            session_id=session_id,
            elapsed_ms=elapsed_ms,
            status=str(status),
        )


def node_trace(node_name: str | None = None):
    """Timing / logging decorator for LangGraph nodes.

    Wraps both sync and async node functions; records elapsed time,
    session_id, and status in structured ``extra`` fields so log
    aggregators can filter and group by node or session without parsing
    the message string.
    """
    def decorator(
        func: Callable[..., Union[dict, Coroutine[Any, Any, dict]]],
    ) -> Callable[..., Union[dict, Coroutine[Any, Any, dict]]]:
        name = node_name or func.__name__

        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(state, **kwargs) -> dict:
                start = perf_counter()
                state_type = state.__class__.__name__
                if 'session_id' in state.__class__.model_fields:
                    session_id = state.session_id or f"<{state_type}>"
                else:
                    session_id = f"<{state_type}>"
                try:
                    result = await func(state)
                    _log_result(name, perf_counter() - start, session_id, result)
                    return result
                except Exception:
                    logger.exception(
                        "node raised exception",
                        node=name,
                        session_id=session_id,
                        elapsed_ms=round((perf_counter() - start) * 1000),
                    )
                    raise

            return async_wrapper

        @wraps(func)
        def wrapper(state, **kwargs) -> dict:
            start = perf_counter()
            state_type = state.__class__.__name__
            if 'session_id' in state.model_fields:
                session_id = state.session_id or f"<{state_type}>"
            else:
                session_id = f"<{state_type}>"

            try:
                result = func(state)
                _log_result(name, perf_counter() - start, session_id, result)
                return result
            except Exception:
                logger.exception(
                    "node raised exception",
                    extra={"node": name, "session_id": session_id,
                           "elapsed_ms": round((perf_counter() - start) * 1000)},
                )
                raise

        return wrapper

    return decorator
