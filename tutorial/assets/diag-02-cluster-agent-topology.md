# Diagram 2: Cluster Agent Topology — Stub and LLM Modes

Used in: Sessions 02 (stub) and 03 (LLM).

Key message: the graph structure is the same in both modes. Session 03 replaces
one node (classify) and adds a cycle. Everything else stays identical.

```mermaid
flowchart TD
    START(("START"))
    END_(("END"))

    INGEST["ingest_events\nset status = processing"]
    CLASSIFY_STUB["classify\n— STUB MODE —\nreturns placeholder finding"]
    CLASSIFY_LLM["classify\n— LLM MODE —\nLLM + bound tools"]
    TOOLS["tool_node\nToolNode(SENSOR_TOOLS)\nget_recent_readings · check_threshold ..."]
    PARSE["parse_findings\nextract JSON from LLM response"]
    ROUTE{{"route_after_classify\nstatus == error?"}}
    ROUTE_LLM{{"route_after_classify_llm\ntool_calls present?"}}
    REPORT["report_findings\nwrite to Store\nreturn AnomalyFinding list"]

    START --> INGEST

    %% Stub mode path
    INGEST -->|"stub mode"| CLASSIFY_STUB
    CLASSIFY_STUB --> ROUTE
    ROUTE -->|"ok"| REPORT
    ROUTE -->|"error"| END_

    %% LLM mode path
    INGEST -->|"llm mode"| CLASSIFY_LLM
    CLASSIFY_LLM --> ROUTE_LLM
    ROUTE_LLM -->|"tool_calls"| TOOLS
    TOOLS -->|"loop back"| CLASSIFY_LLM
    ROUTE_LLM -->|"done"| PARSE
    PARSE --> REPORT

    REPORT --> END_
```

---

*Note: only one of the two `classify` paths exists at runtime — the graph is
compiled with either stub or LLM mode. Both paths share `ingest_events` and
`report_findings` unchanged.*
