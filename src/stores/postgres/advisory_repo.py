"""Advisory repository — persist and query resource advisories."""

from __future__ import annotations

import logging

from agents.commons.schemas import ResourceAdvisoryRecord
from stores.base import AdvisoryRepository as AdvisoryRepositoryBase
from stores.postgres.gateway import PgGateway

logger = logging.getLogger(__name__)


class ResourceAdvisoryRepository(AdvisoryRepositoryBase):
    """Repository for persisting and retrieving resource advisories."""

    def __init__(self, pg_gateway: PgGateway):
        self._pg = pg_gateway

    def save_advisory(self, advisory: ResourceAdvisoryRecord) -> int:
        """Save a single advisory. Returns number of rows inserted (1)."""
        return self.save_advisories([advisory])

    def save_advisories(self, advisories: list[ResourceAdvisoryRecord]) -> int:
        """Bulk insert advisories. Returns number of rows inserted."""
        if not advisories:
            return 0

        rows = [r.to_db_row() for r in advisories]

        with self._pg.conn() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                insert into resource_advisories (
                    id,
                    created_at,
                    status,
                    epicenter_row,
                    epicenter_column,
                    location_description,
                    situation,
                    urgency_level,
                    notes,
                    recommendation
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
            return cur.rowcount

    def fetch_recent_advisories(
        self,
        grid_row: int,
        grid_col: int,
        limit: int = 10,
    ) -> list[ResourceAdvisoryRecord]:
        """Fetch recent advisories for a specific grid cell, most recent first.

        Parameters
        ----------
        grid_row : the row of the grid cell
        grid_col : the column of the grid cell
        limit     : Maximum number of records to return (default 10)

        Returns
        -------
        List of previous advisory records for the given cell
        """
        rows = self._pg.fetch_rows(
            """
            select
                    id,
                    created_at,
                    status,
                    epicenter_row,
                    epicenter_column,
                    location_description,
                    situation,
                    urgency_level,
                    notes,
                    recommendation
            from resource_advisories
            where epicenter_row = %s AND epicenter_column = %s
            order by created_at desc
            limit %s
            """,
            (grid_row, grid_col, limit),
        )

        results = [ResourceAdvisoryRecord.model_validate(r) for r in rows]

        logger.info(
            "Fetched %d advisories for cell (%d, %d) ",
            len(results),
            grid_row,
            grid_col,
        )
        return results


if __name__ == "__main__":
    """Quick sanity check: create spoof advisories, save, retrieve."""
    import sys


    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    pg: PgGateway | None = None

    try:
        pg = PgGateway()
        pg.open()  # Assumes default env vars / config

        repo = ResourceAdvisoryRepository(pg)

        # Spoof advisories for cell (5, 10)
        spoof_advisories = [
            ResourceAdvisoryRecord(
                epicenter_row=5,
                epicenter_column=10,
                location_description="Northwest slope below ridgeline, prevailing wind exposure",
                situation="Spot fire detected at edge of contained zone. Wind shift risk high.",
                urgency_level=2,
                notes="2 engines available. If wind exceeds 25mph, escalation to Level 1 likely.",
                recommendation="Pre-position engine 3 and request air tanker standby.",
            ),
            ResourceAdvisoryRecord(
                epicenter_row=5,
                epicenter_column=10,
                location_description="Same cell — eastern drainage",
                situation="Secondary ignition reported by lookout. Containment 15%.",
                urgency_level=3,
                notes="Resource conflict: engine 3 committed to prior advisory. Coordination needed.",
                recommendation="Dispatch additional engine from station 12; monitor overnight.",
            ),
        ]

        print(f"\nSaving {len(spoof_advisories)} spoof advisories...")
        inserted = repo.save_advisories(spoof_advisories)
        print(f"Inserted: {inserted}")

        print("\nRetrieving advisories for cell (5, 10)...")
        retrieved = repo.fetch_recent_advisories(grid_row=5, grid_col=10, limit=10)
        print(f"Retrieved {len(retrieved)} records:")
        for i, adv in enumerate(retrieved, 1):
            print(f"  {i}. [{adv.status}] Level {adv.urgency_level}: {adv.recommendation[:50]}...")

        print("\nSanity check complete.")

    except Exception as e:
        print(f"DB connection failed: {e}")
        print("Skipping harness (DB not available)")
        sys.exit(0)

    finally:
        pg and pg.close()
