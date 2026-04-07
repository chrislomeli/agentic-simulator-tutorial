"""Tests for ogar.domains.wildfire.cell_state."""

import pytest

from domains.wildfire import (
    FireCellState,
    FireState,
    TerrainType,
)


class TestFireCellState:
    def test_defaults(self):
        state = FireCellState()
        assert state.terrain_type == TerrainType.GRASSLAND
        assert state.vegetation == 0.5
        assert state.fuel_moisture == 0.3
        assert state.slope == 0.0
        assert state.fire_state == FireState.UNBURNED
        assert state.fire_intensity == 0.0
        assert state.fire_start_tick is None

    def test_summary_label(self):
        assert FireCellState().summary_label() == "UNBURNED"
        burning = FireCellState(fire_state=FireState.BURNING)
        assert burning.summary_label() == "BURNING"

    def test_serialisation(self):
        state = FireCellState(
            terrain_type=TerrainType.FOREST,
            vegetation=0.85,
            fire_state=FireState.BURNING,
            fire_intensity=0.7,
            fire_start_tick=3,
        )
        d = state.model_dump()
        assert d["terrain_type"] == "FOREST"
        assert d["fire_state"] == "BURNING"
        assert d["fire_intensity"] == 0.7
        assert d["fire_start_tick"] == 3

    def test_deserialisation(self):
        state = FireCellState.model_validate({
            "terrain_type": "ROCK",
            "vegetation": 0.0,
            "fire_state": "UNBURNED",
        })
        assert state.terrain_type == TerrainType.ROCK

    def test_is_burnable_unburned_grassland(self):
        assert FireCellState().is_burnable is True

    def test_is_burnable_rock(self):
        assert FireCellState(terrain_type=TerrainType.ROCK).is_burnable is False

    def test_is_burnable_water(self):
        assert FireCellState(terrain_type=TerrainType.WATER).is_burnable is False

    def test_is_burnable_already_burning(self):
        state = FireCellState(fire_state=FireState.BURNING)
        assert state.is_burnable is False

    def test_is_burnable_already_burned(self):
        state = FireCellState(fire_state=FireState.BURNED)
        assert state.is_burnable is False

    def test_is_burnable_zero_vegetation(self):
        state = FireCellState(vegetation=0.0)
        assert state.is_burnable is False

    def test_ignited_returns_new_state(self):
        state = FireCellState(terrain_type=TerrainType.FOREST, vegetation=0.85)
        ignited = state.ignited(tick=5, intensity=0.7)
        # Original unchanged
        assert state.fire_state == FireState.UNBURNED
        # New state has fire
        assert ignited.fire_state == FireState.BURNING
        assert ignited.fire_intensity == 0.7
        assert ignited.fire_start_tick == 5
        # Terrain preserved
        assert ignited.terrain_type == TerrainType.FOREST
        assert ignited.vegetation == 0.85

    def test_ignited_clamps_intensity(self):
        state = FireCellState()
        assert state.ignited(tick=0, intensity=1.5).fire_intensity == 1.0
        assert state.ignited(tick=0, intensity=-0.5).fire_intensity == 0.0

    def test_ignited_carries_rothermel_metrics(self):
        """ignited() should carry through the optional Rothermel metric fields."""
        state = FireCellState()
        ignited = state.ignited(
            tick=3,
            intensity=0.6,
            rate_of_spread_ft_min=12.5,
            flame_length_ft=8.3,
            fireline_intensity_btu_ft_s=450.0,
        )
        assert ignited.rate_of_spread_ft_min == pytest.approx(12.5)
        assert ignited.flame_length_ft == pytest.approx(8.3)
        assert ignited.fireline_intensity_btu_ft_s == pytest.approx(450.0)

    def test_ignited_default_metrics_zero(self):
        """Without explicit metrics, Rothermel fields default to 0.0."""
        state = FireCellState()
        ignited = state.ignited(tick=0)
        assert ignited.rate_of_spread_ft_min == 0.0
        assert ignited.flame_length_ft == 0.0
        assert ignited.fireline_intensity_btu_ft_s == 0.0

    def test_extinguished_zeros_metrics(self):
        """extinguished() must zero out all fire behavior metrics."""
        state = FireCellState(
            fire_state=FireState.BURNING,
            fire_intensity=0.8,
            fire_start_tick=2,
            rate_of_spread_ft_min=14.0,
            flame_length_ft=9.5,
            fireline_intensity_btu_ft_s=600.0,
        )
        ext = state.extinguished()
        assert ext.fire_state == FireState.BURNED
        assert ext.fire_intensity == 0.0
        assert ext.rate_of_spread_ft_min == 0.0
        assert ext.flame_length_ft == 0.0
        assert ext.fireline_intensity_btu_ft_s == 0.0
        # fire_start_tick preserved (for history)
        assert ext.fire_start_tick == 2

    def test_extinguished_returns_new_state(self):
        state = FireCellState(
            fire_state=FireState.BURNING,
            fire_intensity=0.8,
            fire_start_tick=2,
        )
        ext = state.extinguished()
        assert ext.fire_state == FireState.BURNED
        assert ext.fire_intensity == 0.0

    def test_rothermel_defaults_are_zero(self):
        """New cells should have all Rothermel metrics at 0.0."""
        state = FireCellState()
        assert state.rate_of_spread_ft_min == 0.0
        assert state.flame_length_ft == 0.0
        assert state.fireline_intensity_btu_ft_s == 0.0


class TestEnumValues:
    def test_terrain_type_values(self):
        assert TerrainType.FOREST == "FOREST"
        assert TerrainType.WATER == "WATER"

    def test_fire_state_values(self):
        assert FireState.UNBURNED == "UNBURNED"
        assert FireState.BURNING == "BURNING"
        assert FireState.BURNED == "BURNED"
