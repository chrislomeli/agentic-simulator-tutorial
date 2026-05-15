"""
world-simiulator.domains.wildfire

Wildfire domain — stochastic fire spread on a terrain grid.

Public API:
  FireCellState              — per-cell state (terrain, fuel, fire status)
  FireEnvironmentState       — weather conditions (temp, humidity, wind)
  SimpleFirePhysicsModule    — heuristic fire spread model
  RothermelFirePhysicsModule — physics-based fire spread (Rothermel 1972)
  FuelModel / get_fuel_model — fuel load by terrain type
  NWCGResourceSpec           — NWCG-standard resource definitions
  Sensor classes             — temperature, smoke, humidity, wind, thermal
  Scenario factories         — create_basic_wildfire, create_full_wildfire_scenario
"""

from world.domains.wildfire.cell_state import FireCellState as FireCellState
from world.domains.wildfire.cell_state import FireState as FireState
from world.domains.wildfire.cell_state import TerrainType as TerrainType
from world.domains.wildfire.environment import FireEnvironmentState as FireEnvironmentState
from world.domains.wildfire.fuel_models import FuelModel as FuelModel
from world.domains.wildfire.fuel_models import get_fuel_model as get_fuel_model
from world.domains.wildfire.nwcg_resources import NWCGResourceSpec as NWCGResourceSpec
from world.domains.wildfire.nwcg_resources import get_by_id as get_by_id
from world.domains.wildfire.nwcg_resources import get_by_kind as get_by_kind
from world.domains.wildfire.nwcg_resources import suppression_category as suppression_category
from world.domains.wildfire.physics import FirePhysicsModule as FirePhysicsModule
from world.domains.wildfire.physics import SimpleFirePhysicsModule as SimpleFirePhysicsModule
from world.domains.wildfire.rothermel_physics import (
    RothermelFirePhysicsModule as RothermelFirePhysicsModule,
)
from world.domains.wildfire.sampler import sample_local_conditions as sample_local_conditions
from world.domains.wildfire.sampler import sample_thermal_region as sample_thermal_region
from world.domains.wildfire.scenarios import create_basic_wildfire as create_basic_wildfire
from world.domains.wildfire.scenarios import (
    create_full_wildfire_scenario as create_full_wildfire_scenario,
)
from world.domains.wildfire.scenarios import create_wildfire_resources as create_wildfire_resources
from world.domains.wildfire.sensors import BarometricSensor as BarometricSensor
from world.domains.wildfire.sensors import HumiditySensor as HumiditySensor
from world.domains.wildfire.sensors import SmokeSensor as SmokeSensor
from world.domains.wildfire.sensors import TemperatureSensor as TemperatureSensor
from world.domains.wildfire.sensors import ThermalCameraSensor as ThermalCameraSensor
from world.domains.wildfire.sensors import WindSensor as WindSensor

__all__ = [
    # Cell state
    "FireCellState",
    "FireState",
    "TerrainType",
    # Environment
    "FireEnvironmentState",
    # Physics
    "FirePhysicsModule",
    "SimpleFirePhysicsModule",
    "RothermelFirePhysicsModule",
    # Fuel models
    "FuelModel",
    "get_fuel_model",
    # NWCG resources
    "NWCGResourceSpec",
    "get_by_id",
    "get_by_kind",
    "suppression_category",
    # Scenarios
    "create_basic_wildfire",
    "create_wildfire_resources",
    "create_full_wildfire_scenario",
    # Sensors
    "TemperatureSensor",
    "HumiditySensor",
    "WindSensor",
    "SmokeSensor",
    "BarometricSensor",
    "ThermalCameraSensor",
    # Sampler
    "sample_local_conditions",
    "sample_thermal_region",
]
