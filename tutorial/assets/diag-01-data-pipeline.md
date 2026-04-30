# Diagram 1: Data Pipeline — Layered Architecture

Used in: Session 01, referenced in Sessions 04 and 08.

Key message: the agent never sees the world directly. Everything passes through
layers. The gap between ground truth and sensor observation is intentional.

```mermaid
flowchart LR
    subgraph WORLD["World Engine (ground truth)"]
        WE["GenericWorldEngine\ntick()"]
        GRID["TerrainGrid\n10×10 cells"]
        PHYS["RothermelPhysics\nfire spread"]
        WE --> GRID
        WE --> PHYS
    end

    subgraph SENSORS["Sensors (noisy observations)"]
        S1["TemperatureSensor"]
        S2["SmokeSensor"]
        S3["ThermalCamera"]
        S4["WindSensor"]
    end

    subgraph TRANSPORT["Transport (async queue)"]
        PUB["SensorPublisher\nemit()"]
        Q["SensorEventQueue\nasync buffer"]
        CON["EventBridgeConsumer\nbatch by cluster_id"]
        PUB --> Q --> CON
    end

    subgraph AGENT["Agent (your code)"]
        CA["ClusterAgent\nLangGraph graph"]
        FIND["AnomalyFindings"]
        CA --> FIND
    end

    subgraph RESOURCES["Resources (queryable)"]
        RES["ResourceInventory\ncrews · engines · helicopters"]
    end

    WORLD -->|"samples ground truth\n(with noise)"| SENSORS
    SENSORS --> PUB
    CON -->|"ClusterAgentState\nbatch of events"| CA
    RES -->|"readiness_summary()"| CA
```

---

*Design note: the agent receives `ClusterAgentState` — a batch of `SensorEvent`
objects. It never calls `engine.tick()` or reads the grid directly. Resources
are queried by the agent via tools, not pushed automatically.*
