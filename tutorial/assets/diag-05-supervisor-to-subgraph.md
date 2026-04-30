# Diagram 5: Supervisor Invoking the Cluster Subgraph

Used in: Session 05 introduction.

Key message: the cluster agent is a compiled subgraph. The supervisor treats it
as a black box — it passes in a state dict and gets a state dict back.

```mermaid
flowchart TD
    START(("START"))
    END_(("END"))

    FAN["fan_out_to_clusters\nbuilds one Send per cluster_id"]

    subgraph NODE["run_cluster_agent  ← this is just a supervisor node"]
        INVOKE["cluster_agent_graph.invoke(state)\n— black box call —"]

        subgraph SUBGRAPH["Cluster Agent Subgraph  ← compiled separately"]
            IN["ingest_events"]
            CL["classify"]
            RP["report_findings"]
            IN --> CL --> RP
        end

        INVOKE --> SUBGRAPH
    end

    ASSESS["assess_situation"]
    DECIDE["decide_actions"]
    DISPATCH["dispatch_commands"]

    START --> FAN
    FAN -->|"Send() × N clusters\nruns NODE in parallel"| NODE
    NODE -->|"anomalies[]"| ASSESS
    ASSESS --> DECIDE --> DISPATCH --> END_
```

---

## What "subgraph" means in practice

```
# The cluster agent is compiled once at module load:
cluster_agent_graph = build_cluster_agent_graph()

# The supervisor node just calls it:
def run_cluster_agent(state: ClusterAgentState) -> dict:
    result = cluster_agent_graph.invoke(state)   # ← plain Python call
    return {"cluster_findings": result["anomalies"]}
```

The cluster agent doesn't know it's inside a supervisor.
The supervisor doesn't know what happens inside the cluster agent.
They share nothing except the shape of the state dict passed between them.
