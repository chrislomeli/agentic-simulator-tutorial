"""Tests for ogar.domains.wildfire.fuel_models."""

import pytest

from domains.wildfire.fuel_models import FUEL_MODELS, FuelModel, get_fuel_model
from world.grid import TerrainType


class TestFuelModels:
    def test_all_burnable_terrain_types_have_entries(self):
        """GRASSLAND, FOREST, SCRUB, URBAN must all have fuel models."""
        for terrain in (TerrainType.GRASSLAND, TerrainType.FOREST,
                        TerrainType.SCRUB, TerrainType.URBAN):
            assert terrain in FUEL_MODELS, f"{terrain} missing from FUEL_MODELS"

    def test_non_burnable_terrain_types_absent(self):
        """ROCK and WATER must NOT have fuel models."""
        assert TerrainType.ROCK not in FUEL_MODELS
        assert TerrainType.WATER not in FUEL_MODELS

    def test_fuel_model_fields_positive(self):
        """All numeric fields must be positive."""
        for terrain, fm in FUEL_MODELS.items():
            assert fm.base_spread_rate_ft_min > 0, f"{terrain}: base spread must be > 0"
            assert fm.heat_content_btu_lb > 0, f"{terrain}: heat content must be > 0"
            assert 0 < fm.moisture_of_extinction <= 1.0, (
                f"{terrain}: extinction moisture must be in (0, 1]"
            )

    def test_grassland_fastest_spread(self):
        """Grassland should have the highest base spread rate."""
        grass = FUEL_MODELS[TerrainType.GRASSLAND]
        for terrain, fm in FUEL_MODELS.items():
            if terrain != TerrainType.GRASSLAND:
                assert grass.base_spread_rate_ft_min >= fm.base_spread_rate_ft_min

    def test_forest_lowest_extinction_moisture(self):
        """Forest should have a higher moisture of extinction than grassland."""
        forest = FUEL_MODELS[TerrainType.FOREST]
        grass = FUEL_MODELS[TerrainType.GRASSLAND]
        assert forest.moisture_of_extinction > grass.moisture_of_extinction

    def test_get_fuel_model_burnable(self):
        fm = get_fuel_model(TerrainType.GRASSLAND)
        assert fm is not None
        assert isinstance(fm, FuelModel)

    def test_get_fuel_model_non_burnable(self):
        assert get_fuel_model(TerrainType.ROCK) is None
        assert get_fuel_model(TerrainType.WATER) is None

    def test_fuel_model_is_frozen(self):
        """FuelModel instances must be immutable (frozen dataclass)."""
        fm = FUEL_MODELS[TerrainType.GRASSLAND]
        with pytest.raises((AttributeError, TypeError)):
            fm.base_spread_rate_ft_min = 999.0  # type: ignore

    def test_descriptions_are_nonempty(self):
        for terrain, fm in FUEL_MODELS.items():
            assert fm.description, f"{terrain}: description must not be empty"
