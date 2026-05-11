"""Wildfire repository — query historical wildfire activity for resource planning."""

from __future__ import annotations

import logging

from stores.pg_gateway import PgGateway
from stores.schemas import WildfireActivity

logger = logging.getLogger(__name__)


class WildfireRepository:
    """Query historical wildfire data for resource estimation fallback."""

    def __init__(self, pg_gateway: PgGateway):
        self._pg = pg_gateway

    def fetch_similar_fires(
        self,
        min_acres: int,
        max_acres: int,
        limit: int = 10,
    ) -> list[WildfireActivity]:
        """Fetch historical fires by size range, most recent first.

        Used as fallback data when the agent cannot estimate resource needs
        from current scenario data alone.

        Parameters
        ----------
        min_acres : Minimum fire size to include
        max_acres : Maximum fire size to include
        limit     : Maximum number of records to return (default 10)

        Returns
        -------
        List of WildfireActivity records, sorted by date descending
        """
        rows = self._pg.fetch_rows(
            """
            select
                imsr_date,
                gacc,
                gacc_priority,
                fire_priority,
                new_large_fire_mark,
                fire_name,
                unit,
                fire_size_acres,
                fire_size_change,
                percent_containment,
                contained_completed,
                est_containment_date,
                personnel,
                personnel_change,
                crews,
                engines,
                helicopters,
                structures_lost,
                cost_to_date,
                origin_ownership
            from wildfire.wildfire_activity
            where fire_size_acres between %s and %s
            order by imsr_date desc
            limit %s
            """,
            (min_acres, max_acres, limit),
        )

        results = [WildfireActivity.model_validate(r) for r in rows]

        logger.info(
            "Fetched %d historical fires between %d and %d acres",
            len(results),
            min_acres,
            max_acres,
        )
        return results

    def fetch_by_fire_name(
        self,
        fire_name: str,
        limit: int = 5,
    ) -> list[WildfireActivity]:
        """Fetch records matching a fire name (case-insensitive partial match).

        Useful for looking up specific known fires by name.
        """
        rows = self._pg.fetch_rows(
            """
            select
                imsr_date,
                gacc,
                gacc_priority,
                fire_priority,
                new_large_fire_mark,
                fire_name,
                unit,
                fire_size_acres,
                fire_size_change,
                percent_containment,
                contained_completed,
                est_containment_date,
                personnel,
                personnel_change,
                crews,
                engines,
                helicopters,
                structures_lost,
                cost_to_date,
                origin_ownership
            from wildfire.wildfire_activity
            where fire_name ilike %s
            order by imsr_date desc
            limit %s
            """,
            (f"%{fire_name}%", limit),
        )

        results = [WildfireActivity.model_validate(r) for r in rows]
        logger.info(
            "Fetched %d records for fire name matching %r",
            len(results),
            fire_name,
        )
        return results
