"""runtime.profiles — the deployment backbone selector.

This is the *single config lever*. ``Settings.deployment_profile`` (one
env var, ``DEPLOYMENT_PROFILE``) names a column of temp.csv; this module
maps that column to the concrete adapter behind each seam — the store,
the event queue, and the graph client. No other code branches on the
deployment target: the producer/consumer/graph all depend on Protocols
(``EventQueue``, ``GraphClient``) and on the ``DataStore`` ABC; here is
the one place those Protocols are bound to implementations.

Profile → seam matrix (mirrors temp.csv)
────────────────────────────────────────
    profile         store      queue            graph client
    ----------------------------------------------------------------
    local           backend    in-process       in-process (builds graph)
    docker-compose  postgres   in-process*      http (separate container)
    k8s-desktop     postgres   broker           http
    k8s-deployed    postgres   broker           http
    aws             postgres†  broker           agentcore

    * compose collapses producer+queue+consumer into one container, so the
      queue stays in-process *within that container*; only the graph is a
      separate deployable.
    † "RDS" is just a different ``postgres_url`` — same Postgres adapter.

"Collapsing seams into one executable" = this table picking in-process
adapters. It never means a module calling another directly: the seam
(Protocol) is always there; only the binding changes.

Tutorial cut (stated, not hidden): only ``local`` runs end-to-end today.
The broker and http/agentcore adapters are named, Protocol-shaped stubs
(see ``world.transport.broker`` / ``runtime.graph_client``) — the wiring
type-checks and assembles for every profile, and fails loudly with a
pointer at the seam that still needs the broker/API step. Filling those
in changes only the adapter, never the producer/consumer/graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from config import Settings
from runtime.composition import build_agent_dependencies, build_supervisor
from runtime.contract import GraphClient
from runtime.facade import GraphFacade
from runtime.graph_client import (
    AgentCoreGraphClient,
    HttpGraphClient,
    InProcessGraphClient,
)
from stores.base import DataStore
from stores.world_state import LoggingWorldStateWriter, WorldStateWriter
from world import GenericWorldEngine
from world.cell_state_manager import CellStateManager
from world.domains.wildfire.scenario_loader import load_scenario_from_db
from world.sensor_inventory import SensorInventory
from world.transport import BrokerEventQueue, EventQueue, SensorEventQueue


class DeploymentProfile(StrEnum):
    """The temp.csv columns, as the single backbone selector."""

    LOCAL = "local"
    DOCKER_COMPOSE = "docker-compose"
    K8S_DESKTOP = "k8s-desktop"
    K8S_DEPLOYED = "k8s-deployed"
    AWS = "aws"


# Profiles whose graph runs in the same process as the consumer. For these
# the runtime builds the graph and binds the in-process client; for the
# rest the graph is its own deployable and the consumer gets a remote
# client (it does not build the graph — that is the graph container's job).
_GRAPH_IN_PROCESS = {DeploymentProfile.LOCAL}

# Profiles where producer and consumer share one process (queue stays an
# in-process asyncio queue). Everything else crosses a container boundary
# and needs the broker adapter.
_QUEUE_IN_PROCESS = {DeploymentProfile.LOCAL, DeploymentProfile.DOCKER_COMPOSE}


def parse_profile(settings: Settings) -> DeploymentProfile:
    """Resolve the config lever to a profile, failing loudly on a typo."""
    try:
        return DeploymentProfile(settings.deployment_profile)
    except ValueError as exc:
        valid = ", ".join(p.value for p in DeploymentProfile)
        raise ValueError(
            f"Unknown deployment_profile {settings.deployment_profile!r}. "
            f"Valid: {valid}"
        ) from exc


def build_data_store(settings: Settings) -> DataStore:
    """Bind the DataStore ABC. 'mock' = JSON-backed (no DB); else Postgres
    (a different URL is all that separates local Postgres from RDS)."""
    if settings.store_backend == "mock":
        from stores.mock import get_mock_data_store

        return get_mock_data_store()
    if settings.store_backend == "postgres":
        from stores import get_postgres_data_store

        return get_postgres_data_store()
    raise ValueError(
        f"Unknown store_backend {settings.store_backend!r}. Valid: postgres, mock"
    )


def build_event_queue(settings: Settings) -> EventQueue:
    """Bind the EventQueue port for the producer↔consumer seam."""
    profile = parse_profile(settings)
    if profile in _QUEUE_IN_PROCESS:
        return SensorEventQueue(maxsize=1000)
    return BrokerEventQueue(url=settings.event_broker_url)


def build_graph_client(
    settings: Settings,
    *,
    facade: GraphFacade | None = None,
) -> GraphClient:
    """Bind the GraphClient port for the consumer→graph seam.

    In-process profiles require the ``facade`` (the graph runs here);
    remote profiles ignore it and return the HTTP/AgentCore adapter.
    """
    profile = parse_profile(settings)
    if profile in _GRAPH_IN_PROCESS:
        if facade is None:
            raise ValueError(
                f"Profile {profile.value!r} runs the graph in-process but no "
                "GraphFacade was provided to build_graph_client()."
            )
        return InProcessGraphClient(facade)
    if profile is DeploymentProfile.AWS:
        return AgentCoreGraphClient(
            agent_runtime_arn=settings.agent_runtime_arn or "",
            region=settings.aws_region,
        )
    return HttpGraphClient(base_url=settings.graph_service_url or "")


def build_world_state_writer(settings: Settings) -> WorldStateWriter:
    """Bind the "end the event flow" write seam.

    All profiles use the logging stub today: the DB is an immutable seed
    so scenarios replay identically. A real ``PostgresWorldStateWriter``
    is a drop-in here in a later step — nothing else changes.
    """
    return LoggingWorldStateWriter()


@dataclass
class RuntimeBundle:
    """Everything an entrypoint needs, wired for the active profile.

    ``graph_client`` is the only seam the consumer touches; the rest is
    the local world it ticks. ``close()`` releases the store.
    """

    profile: DeploymentProfile
    data_store: DataStore
    engine: GenericWorldEngine
    sensor_inventory: SensorInventory
    cell_state_manager: CellStateManager
    graph_client: GraphClient

    def close(self) -> None:
        self.data_store.close()


def build_runtime(
    settings: Settings,
    *,
    region_name: str = "lpnf-south",
) -> RuntimeBundle:
    """Assemble the runtime for the active profile.

    Identical world wiring for every profile; the *only* difference is
    which adapter sits behind each seam. The collapsed/local profile also
    builds the graph and binds it in-process; split profiles get a remote
    graph client and never build the graph (that is the graph container's
    job, assembled in the API step).
    """
    profile = parse_profile(settings)

    data_store = build_data_store(settings)
    engine, sensor_inventory = load_scenario_from_db(region_name, data_store)
    cell_state_manager = CellStateManager(
        world_grid=engine.grid,
        sensor_inventory=sensor_inventory,
    )

    if profile in _GRAPH_IN_PROCESS:
        agent_deps = build_agent_dependencies(
            engine, cell_state_manager, data_store=data_store
        )
        supervisor_graph = build_supervisor(agent_deps)
        facade = GraphFacade(
            supervisor_graph=supervisor_graph,
            cell_state_manager=cell_state_manager,
            world_state_writer=build_world_state_writer(settings),
        )
        graph_client = build_graph_client(settings, facade=facade)
    else:
        graph_client = build_graph_client(settings)

    return RuntimeBundle(
        profile=profile,
        data_store=data_store,
        engine=engine,
        sensor_inventory=sensor_inventory,
        cell_state_manager=cell_state_manager,
        graph_client=graph_client,
    )
