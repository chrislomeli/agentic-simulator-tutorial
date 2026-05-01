"""
ogar.transport.topics

Kafka topic name constants and helpers.

Why centralise topic names here?
─────────────────────────────────
Topic names are strings, and strings drift.  If the bridge consumer
hardcodes "sensors.raw.cluster-north" and a sensor hardcodes
"sensor.raw.cluster-north" (note: "sensor" vs "sensors"), nothing
connects and there is no error — messages just disappear.

Keeping all names here means:
  - One place to change if naming conventions evolve.
  - Import errors catch typos at startup rather than silently at runtime.
  - Easy to scan the full topic inventory in one glance.

Topic naming convention
───────────────────────
  {direction}.{content-type}.{optional-qualifier}

  sensors.raw.{cluster_id}   ← raw sensor readings, one topic per cluster
  events.anomaly             ← anomalies detected by cluster agents
  agents.decisions           ← audit log of agent decisions
  commands.actuators         ← agent → actuator commands
  results.actuators          ← actuator outcomes back to agents

The per-cluster sensor topics (sensors.raw.*) use a helper function
rather than a constant because the cluster_id is dynamic.
"""


# ── Static topic names ────────────────────────────────────────────────────────

# Cluster agents publish detected anomalies here.
# The supervisor agent subscribes to route its fan-out.
EVENTS_ANOMALY = "events.anomaly"

# Every agent decision is published here for audit / replay.
# Nothing subscribes to this in normal operation — it is observability only.
AGENTS_DECISIONS = "agents.decisions"

# Supervisor agent publishes structured commands here.
# Each actuator type subscribes and filters by the command's target field.
COMMANDS_ACTUATORS = "commands.actuators"

# Actuators publish outcomes here after executing a command.
# Agents can subscribe to close the feedback loop (did the drone launch?).
RESULTS_ACTUATORS = "results.actuators"


# ── Dynamic topic helpers ─────────────────────────────────────────────────────

# Prefix for per-cluster raw sensor topics.
# Full topic name is built by sensor_topic(cluster_id).
_SENSOR_RAW_PREFIX = "sensors.raw"


def sensor_topic(cluster_id: str) -> str:
    """
    Return the Kafka topic name for raw sensor readings from a given cluster.

    Each cluster has its own topic so that:
      - The bridge consumer can fan out messages to the right cluster agent
        without reading a single firehose topic and filtering.
      - Kafka partitioning can be tuned per cluster independently.
      - Adding a new cluster means creating a new topic, not modifying consumers.

    Example
    -------
    >>> sensor_topic("cluster-north")
    'sensors.raw.cluster-north'
    """
    if not cluster_id:
        raise ValueError("cluster_id must be a non-empty string")
    return f"{_SENSOR_RAW_PREFIX}.{cluster_id}"


def all_sensor_topic_pattern() -> str:
    """
    Return a Kafka topic subscription pattern that matches ALL cluster sensor topics.

    Use this when a consumer needs to read from every cluster at once
    (e.g. the bridge consumer before it routes by cluster_id).

    Kafka consumers accept regex patterns when subscribing.
    The returned string is a valid Java regex.

    Example
    -------
    >>> all_sensor_topic_pattern()
    'sensors\\.raw\\..*'
    """
    # Dots in Kafka regex need escaping — a bare dot matches any character.
    return r"sensors\.raw\..*"
