# 04 — Full Sensor + Agent Pipeline

## Teaching goal
Student wires `SensorPublisher → SensorEventQueue → EventBridgeConsumer` and understands that the consumer's job is event collection only — cluster agents are invoked later by the supervisor.

## I/O
- In: `WorldEngine`, list of sensors
- Out: `consumer.events_by_cluster` (dict mapping `cluster_id → list[SensorEvent]`), `queue.total_enqueued` == sensors × ticks
- No new source files — pure integration

## Must cover
- [ ] `SensorPublisher.run(ticks=N)` — async loop, each tick advances engine + emits events
- [ ] `SensorEventQueue` — the buffer between publisher and consumer
- [ ] `EventBridgeConsumer` — drains the queue and groups events by `cluster_id`; does NOT invoke cluster agents
- [ ] `consumer.events_by_cluster` — the output; passed to supervisor as `events_by_cluster` in the invoke call
- [ ] `await publisher.run()` then `await consumer.run(max_events=queue.total_enqueued)` — sequential async
- [ ] Events enqueued = sensors × ticks (verify this)
- [ ] LangSmith tracing — `LANGCHAIN_TRACING_V2=true` and what you see in the UI
- [ ] `pytest tests/bridge/ -v`
