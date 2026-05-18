# Deployment

One codebase, one image. The **deployment profile** (`DEPLOYMENT_PROFILE`,
read by `runtime.profiles`) binds the adapter behind each seam — store,
event queue, graph client. Nothing in the app branches on the target;
splitting or collapsing roles is a wiring decision, not a code change.

## Profile → topology

| Profile | Store | Queue | Graph client | Runs end-to-end today? |
|---|---|---|---|---|
| `local` | Postgres *(or `mock`)* | in-process | in-process | **Yes** |
| `docker-compose` | Postgres | in-process* | HTTP | DB + collapsed app: yes. Split: after broker+API |
| `k8s-desktop` | Postgres | broker | HTTP | After broker+API steps |
| `k8s-deployed` | Postgres | broker | HTTP | After broker+API steps |
| `aws` | RDS (just a URL) | broker | AgentCore | After broker+API steps |

\* compose collapses producer+queue+consumer into one container; only the
graph is separate.

## Roles (one container = one process = one command)

`wildfire-local` (collapsed) · `wildfire-producer` · `wildfire-consumer`
— same image, different command. Equivalent to
`python -m runtime.entrypoints.<role>`.

## Run it

```bash
# Collapsed, no database (fastest):
DEPLOYMENT_PROFILE=local STORE_BACKEND=mock uv run wildfire-local

# Compose: Postgres + collapsed app (seed the DB via the data pipeline):
docker compose up --build

# k8s skeleton (validate / apply):
kubectl kustomize deploy/k8s/overlays/k8s-desktop
```

## What's real vs. deliberately stubbed (tutorial cut, stated not hidden)

The **seams** are real and fully wired for every profile — the topology
is correct now. What's deferred is transport *bodies*, each a named,
Protocol-shaped stub that fails loudly pointing at its step:

- **Broker `EventQueue`** (`world.transport.broker`): one networked impl
  (Redis Streams) is the broker step. Kafka/SQS are named, not built.
- **HTTP / AgentCore `GraphClient`** (`runtime.graph_client`): the
  FastAPI route / AgentCore handler they call is the **API step**.
- **`WorldStateWriter`** (`stores.world_state`): logging no-op — the DB
  is an immutable seed so scenarios replay identically. A real
  `PostgresWorldStateWriter` is a drop-in.

Filling any of these in changes only that adapter — never the producer,
consumer, or graph, because they depend on Protocols.

### Out of scope (explicit trade-offs)

Kustomize, not Helm. No Skaffold/Tilt inner loop. Image is single-stage
(multi-stage is an easy later optimisation). Secrets are ConfigMap
placeholders — use real `Secret`s in a real cluster.
