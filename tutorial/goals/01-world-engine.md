# 01 — World Engine and Infrastructure

## Teaching goal
Student understands the data pipeline they'll be building agents on top of — what the agent sees vs. what's ground truth.

## I/O
- In: nothing (infrastructure is checked out from tutorial remote, not written)
- Out: all infrastructure tests pass; student can call `engine.tick()`, read `SensorEvent` from queue, and see `ResourceInventory`

## Must cover
- [ ] The pipeline shape: World → Sensors → Transport → Agent (Resources as queryable sidebar)
- [ ] Agent sees sensor events, NOT the grid directly — this gap is intentional
- [ ] `SensorEvent` schema: what fields are in it (source_id, cluster_id, payload, confidence, sim_tick)
- [ ] `engine.history` — ground truth snapshots for later evaluation
- [ ] `ResourceInventory` — queryable, not streamed (agent pulls, not pushed)
- [ ] No code to write — purpose is orientation + test verification
- [ ] `pytest tests/world/ tests/domains/ tests/sensors/ tests/transport/ -v` all pass


## Tutorial Notes
- run `python examples/world_builder.py` to build the world
