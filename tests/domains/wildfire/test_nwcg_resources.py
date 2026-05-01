"""Tests for ogar.domains.wildfire.nwcg_resources."""

import pytest

from domains.wildfire.nwcg_resources import (
    INTENSITY_THRESHOLDS,
    NWCG_CATALOG,
    NWCGResourceSpec,
    get_by_id,
    get_by_kind,
    suppression_category,
)


class TestNWCGCatalog:
    def test_catalog_nonempty(self):
        assert len(NWCG_CATALOG) > 0

    def test_required_ids_present(self):
        """Key operational resource IDs must be in the catalog."""
        ids = {s.nwcg_id for s in NWCG_CATALOG}
        for required in ("C-1", "C-2", "E-3", "D-1", "H-1", "A-1"):
            assert required in ids, f"{required} missing from NWCG_CATALOG"

    def test_get_by_id_found(self):
        spec = get_by_id("C-1")
        assert spec is not None
        assert spec.name == "Interagency Hotshot Crew (IHC)"
        assert spec.production_rate_chains_hr == 15.0

    def test_get_by_id_not_found(self):
        assert get_by_id("INVALID-99") is None

    def test_get_by_kind_crew(self):
        crews = get_by_kind("Crew")
        assert len(crews) >= 2
        for c in crews:
            assert c.kind == "Crew"

    def test_get_by_kind_engine(self):
        engines = get_by_kind("Engine")
        assert len(engines) >= 2
        for e in engines:
            assert e.kind == "Engine"

    def test_personnel_have_production_rates(self):
        """All crew and dozer specs should have production_rate_chains_hr."""
        for spec in NWCG_CATALOG:
            if spec.kind in ("Crew", "Dozer", "Smokejumpers", "Helitack"):
                assert spec.production_rate_chains_hr is not None, (
                    f"{spec.nwcg_id}: should have production_rate_chains_hr"
                )

    def test_aircraft_have_capacity(self):
        for spec in NWCG_CATALOG:
            if spec.kind in ("Air Tanker", "Helicopter"):
                assert spec.capacity_gal is not None, (
                    f"{spec.nwcg_id}: aircraft should have capacity_gal"
                )

    def test_engines_have_tank_and_pump(self):
        for spec in NWCG_CATALOG:
            if spec.kind == "Engine":
                assert spec.tank_gal is not None
                assert spec.pump_gpm is not None

    def test_spec_is_frozen(self):
        spec = get_by_id("C-1")
        with pytest.raises((AttributeError, TypeError)):
            spec.name = "MODIFIED"  # type: ignore


class TestIntensityThresholds:
    def test_thresholds_present(self):
        for key in ("hand_crew", "engine", "dozer", "air_tanker"):
            assert key in INTENSITY_THRESHOLDS

    def test_thresholds_ordered(self):
        """Each threshold must be strictly greater than the previous."""
        values = [
            INTENSITY_THRESHOLDS["hand_crew"],
            INTENSITY_THRESHOLDS["engine"],
            INTENSITY_THRESHOLDS["dozer"],
            INTENSITY_THRESHOLDS["air_tanker"],
        ]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1], (
                f"Threshold {i} ({values[i]}) must be > threshold {i-1} ({values[i-1]})"
            )

    def test_thresholds_positive(self):
        for k, v in INTENSITY_THRESHOLDS.items():
            assert v > 0, f"Threshold {k} must be positive"


class TestSuppressionCategory:
    def test_low_intensity_hand_crew(self):
        assert suppression_category(50.0) == "hand_crew"

    def test_boundary_hand_crew(self):
        assert suppression_category(99.9) == "hand_crew"

    def test_engine_range(self):
        assert suppression_category(100.0) == "engine"
        assert suppression_category(499.9) == "engine"

    def test_dozer_range(self):
        assert suppression_category(500.0) == "dozer"
        assert suppression_category(999.9) == "dozer"

    def test_aerial_only_range(self):
        assert suppression_category(1000.0) == "aerial_only"
        assert suppression_category(1999.9) == "aerial_only"

    def test_beyond_suppression(self):
        assert suppression_category(2000.0) == "beyond_suppression"
        assert suppression_category(5000.0) == "beyond_suppression"

    def test_zero_intensity(self):
        assert suppression_category(0.0) == "hand_crew"
