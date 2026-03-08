import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from .models import MapEvent, FeedStatus


class EventStore:
    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours
        self._current_by_entity: dict[str, MapEvent] = {}
        self._history: list[MapEvent] = []
        self._feed_status: dict[str, FeedStatus] = {}
        self._lock = asyncio.Lock()

    async def upsert_many(self, events: list[MapEvent]):
        async with self._lock:
            for event in events:
                self._current_by_entity[event.entity_id] = event
                self._history.append(event)
            self._trim_history_locked()

    async def set_feed_status(self, statuses: list[FeedStatus]):
        async with self._lock:
            for status in statuses:
                self._feed_status[status.source] = status

    async def current(self, layers: set[str] | None = None) -> list[MapEvent]:
        async with self._lock:
            events = list(self._current_by_entity.values())
        return self._filter_layers(events, layers)

    async def replay(self, minutes_ago: int = 0, layers: set[str] | None = None) -> list[MapEvent]:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=max(0, minutes_ago))
        async with self._lock:
            candidates = [event for event in self._history if event.timestamp <= as_of]
        latest: dict[str, MapEvent] = {}
        for event in candidates:
            previous = latest.get(event.entity_id)
            if previous is None or previous.timestamp <= event.timestamp:
                latest[event.entity_id] = event
        return self._filter_layers(list(latest.values()), layers)

    async def layer_counts(self) -> dict[str, int]:
        events = await self.current()
        counts = defaultdict(int)
        for event in events:
            counts[event.layer] += 1
        return dict(sorted(counts.items()))

    async def feed_status(self) -> list[FeedStatus]:
        async with self._lock:
            return list(self._feed_status.values())

    def _trim_history_locked(self):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)
        self._history = [event for event in self._history if event.timestamp >= cutoff]

    def _filter_layers(self, events: list[MapEvent], layers: set[str] | None = None) -> list[MapEvent]:
        filtered = [event for event in events if not layers or event.layer in layers]
        return sorted(filtered, key=lambda item: (item.layer, item.title))
