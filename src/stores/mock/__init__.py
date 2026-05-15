"""Mock (JSON-backed) DataStore for tutorial / stub mode.

No database or PostGIS required. Data is loaded from JSON files under
stores/mock/data/ which were extracted from the real Postgres seed data.

Usage::

    from stores.mock import get_mock_data_store

    data_store = get_mock_data_store()
    engine, sensors = load_scenario_from_db("lpnf-south", data_store)
"""

from stores.mock.data_store import MockDataStore, get_mock_data_store

__all__ = ["MockDataStore", "get_mock_data_store"]
