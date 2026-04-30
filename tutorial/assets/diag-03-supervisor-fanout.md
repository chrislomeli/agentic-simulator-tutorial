# Diagram 3: Supervisor Fan-out — Send API Pattern

Used in: Sessions 05 (stub) and 06 (LLM).

Key message: the supervisor does not call cluster agents sequentially.
It dispatches all of them in parallel via the Send API. Results are
merged back into supervisor state by a custom reducer — not by the supervisor
node itself.

```mermaid
flowchart TD
    START(("START"))
    END_(("END"))

    FAN["fan_out_to_clusters\nreturns List[Send]"]

    subgraph PARALLEL["parallel execution — one per cluster"]
        CA1["run_cluster_agent\ncluster-north\n→ ClusterAgent subgraph"]
        CA2["run_cluster_agent\ncluster-south\n→ ClusterAgent subgraph"]
        CA3["run_cluster_agent\ncluster-east\n→ ClusterAgent subgraph"]
    end

    REDUCER[["aggregate_findings_reducer\nmerge findings into SupervisorState"]]

    ASSESS["assess_situation\n— STUB: count findings + past incidents —\n— LLM: correlate across clusters —"]
    DECIDE["decide_actions\n— STUB: no commands —\n— LLM: choose ActuatorCommands —"]
    DISPATCH["dispatch_commands\nwrite situation to Store\nsend commands"]

    ROUTE_DECIDE{{"route_after_decide\nstatus == error?"}}

    START --> FAN
    FAN -->|"Send(cluster-north)"| CA1
    FAN -->|"Send(cluster-south)"| CA2
    FAN -->|"Send(cluster-east)"| CA3

    CA1 & CA2 & CA3 -->|"anomalies[]"| REDUCER
    REDUCER --> ASSESS
    ASSESS --> DECIDE
    DECIDE --> ROUTE_DECIDE
    ROUTE_DECIDE -->|"ok"| DISPATCH
    ROUTE_DECIDE -->|"error"| END_
    DISPATCH --> END_
```

---

*Note: the number of parallel branches is determined at runtime by
`active_cluster_ids`. Add a cluster → one more branch. No code changes.
This is the key LangGraph skill: dynamic fan-out where the number of
targets is known only at runtime.*
