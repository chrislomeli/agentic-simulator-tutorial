"""
ogar.bridge

Async consumer that reads SensorEvents from the transport queue
and routes them to the appropriate cluster agent graph.

This is the "glue" between the sensor/transport layer and the
agent layer.  In a production system this would be a Kafka consumer;
here it is an async loop reading from SensorEventQueue.
"""

from bridge.consumer import EventBridgeConsumer

__all__ = ["EventBridgeConsumer"]
