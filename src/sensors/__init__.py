from sensors.publisher import SensorPublisher

"""
ogar.sensors

Abstract sensor base class and mock sensor implementations.

How sensors work in this system
────────────────────────────────
A sensor's job is simple:
  1. Know its own identity (source_id, source_type, cluster_id).
  2. Produce a domain-specific reading when asked (read() method).
  3. Wrap that reading in a SensorEvent envelope and return it (emit()).

The base class (SensorBase) handles step 3.
Each concrete sensor subclass handles step 2.

The sensor does NOT publish to Kafka.  That is the transport layer's job.
Keeping I/O out of the sensor class makes it easy to test without a
running Kafka broker.

Modules
───────
  base.py   ← SensorBase abstract class — all sensors inherit from this
  mock/     ← Simple mock sensors for hello-world and testing (coming)
"""
