"""
Async PostgreSQL (Supabase) persistence layer for US RealView.

Provides SupabaseStore, a drop-in replacement for the in-memory EventStore.
Uses asyncpg for high-throughput async operations.
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import asyncpg

from .models import FeedStatus, MapEvent

logger = logging.getLogger(__name__)


class SupabaseStore:
    """PostgreSQL-backed event store using asyncpg connection pool."""

    def __init__(self, dsn: str, retention_hours: int = 24):
        self.dsn = dsn
        self.retention_hours = retention_hours
        self._pool: asyncpg.Pool | None = None

    async def connect(self):
        """Initialise the connection pool."""
        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        logger.info("Connected to Supabase PostgreSQL")

    async def close(self):
        if self._pool:
            await self._pool.close()
            logger.info("Closed Supabase connection pool")

    # ── helpers ──────────────────────────────────────────────────────

    def _event_to_row(self, e: MapEvent) -> tuple:
        return (
            e.event_id,
            e.entity_id,
            e.source,
            e.layer,
            e.title,
            e.description,
            e.status,
            e.timestamp,
            e.lat,
            e.lon,
            e.altitude,
            e.speed,
            e.heading,
            json.dumps(e.properties),
        )

    def _row_to_event(self, r: asyncpg.Record) -> MapEvent:
        props = r["properties"]
        if isinstance(props, str):
            props = json.loads(props)
        return MapEvent(
            event_id=r["event_id"],
            entity_id=r["entity_id"],
            source=r["source"],
            layer=r["layer"],
            title=r["title"],
            description=r["description"],
            status=r["status"],
            timestamp=r["timestamp"],
            lat=r["lat"],
            lon=r["lon"],
            altitude=r["altitude"],
            speed=r["speed"],
            heading=r["heading"],
            properties=props,
        )

    # ── writes ───────────────────────────────────────────────────────

    async def upsert_many(self, events: list[MapEvent]):
        """Upsert current events and append to history."""
        if not events or not self._pool:
            return

        async with self._pool.acquire() as conn:
            # Batch upsert into map_events (current state)
            upsert_sql = """
                INSERT INTO map_events (
                    event_id, entity_id, source, layer, title, description,
                    status, timestamp, lat, lon, altitude, speed, heading, properties
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
                ON CONFLICT (entity_id) DO UPDATE SET
                    event_id    = EXCLUDED.event_id,
                    source      = EXCLUDED.source,
                    layer       = EXCLUDED.layer,
                    title       = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status      = EXCLUDED.status,
                    timestamp   = EXCLUDED.timestamp,
                    lat         = EXCLUDED.lat,
                    lon         = EXCLUDED.lon,
                    altitude    = EXCLUDED.altitude,
                    speed       = EXCLUDED.speed,
                    heading     = EXCLUDED.heading,
                    properties  = EXCLUDED.properties,
                    created_at  = now()
            """
            history_sql = """
                INSERT INTO event_history (
                    event_id, entity_id, source, layer, title, description,
                    status, timestamp, lat, lon, altitude, speed, heading, properties
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
            """

            rows = [self._event_to_row(e) for e in events]

            # Use executemany for batch operations
            await conn.executemany(upsert_sql, rows)
            await conn.executemany(history_sql, rows)

        logger.debug("Upserted %d events to Supabase", len(events))

    async def set_feed_status(self, statuses: list[FeedStatus]):
        if not statuses or not self._pool:
            return
        async with self._pool.acquire() as conn:
            for s in statuses:
                await conn.execute("""
                    INSERT INTO feed_status (source, ok, last_refresh, message, updated_at)
                    VALUES ($1, $2, $3, $4, now())
                    ON CONFLICT (source) DO UPDATE SET
                        ok = EXCLUDED.ok,
                        last_refresh = EXCLUDED.last_refresh,
                        message = EXCLUDED.message,
                        updated_at = now()
                """, s.source, s.ok, s.last_refresh, s.message)

    # ── reads ────────────────────────────────────────────────────────

    async def current(self, layers: set[str] | None = None) -> list[MapEvent]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            if layers:
                rows = await conn.fetch(
                    "SELECT * FROM map_events WHERE layer = ANY($1) ORDER BY layer, title",
                    list(layers),
                )
            else:
                rows = await conn.fetch("SELECT * FROM map_events ORDER BY layer, title")
        return [self._row_to_event(r) for r in rows]

    async def replay(self, minutes_ago: int = 0, layers: set[str] | None = None) -> list[MapEvent]:
        if not self._pool:
            return []
        as_of = datetime.now(timezone.utc) - timedelta(minutes=max(0, minutes_ago))
        async with self._pool.acquire() as conn:
            if layers:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (entity_id) *
                    FROM event_history
                    WHERE timestamp <= $1 AND layer = ANY($2)
                    ORDER BY entity_id, timestamp DESC
                """, as_of, list(layers))
            else:
                rows = await conn.fetch("""
                    SELECT DISTINCT ON (entity_id) *
                    FROM event_history
                    WHERE timestamp <= $1
                    ORDER BY entity_id, timestamp DESC
                """, as_of)
        return [self._row_to_event(r) for r in rows]

    async def layer_counts(self) -> dict[str, int]:
        if not self._pool:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT layer, count(*) AS cnt FROM map_events GROUP BY layer ORDER BY layer")
        return {r["layer"]: r["cnt"] for r in rows}

    async def feed_status(self) -> list[FeedStatus]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM feed_status ORDER BY source")
        return [
            FeedStatus(
                source=r["source"],
                ok=r["ok"],
                last_refresh=r["last_refresh"],
                message=r["message"],
            )
            for r in rows
        ]

    async def trim_history(self):
        """Remove history older than retention window."""
        if not self._pool:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)
        async with self._pool.acquire() as conn:
            deleted = await conn.execute("DELETE FROM event_history WHERE timestamp < $1", cutoff)
            logger.info("Trimmed old history: %s", deleted)
