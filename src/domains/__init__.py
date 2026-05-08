"""
world-simiulator.domains

Domain-specific implementations that plug into the generic framework.

Each subdirectory is a self-contained domain package providing:
  - A CellState subclass (what lives on each grid cell)
  - An EnvironmentState subclass (ambient conditions)
  - A PhysicsModule subclass (how the world evolves)
  - Domain-specific sensors
  - Scenario configurations

Available domains:
  - wildfire : stochastic wildfire spread on a terrain grid

This package is intentionally a namespace — each domain owns its own
public API under ``domains.<name>``. Importing ``domains`` directly
returns nothing; import the specific domain you need.
"""

__all__: list[str] = []
