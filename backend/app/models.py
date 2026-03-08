from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class MapEvent(BaseModel):
    event_id: str
    entity_id: str
    source: str
    layer: str
    title: str
    description: str = ""
    status: str = "active"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lat: float
    lon: float
    altitude: float = 0.0
    speed: float | None = None
    heading: float | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class FeedStatus(BaseModel):
    source: str
    ok: bool
    last_refresh: datetime | None = None
    message: str = ""


class EventEnvelope(BaseModel):
    mode: str
    as_of: datetime
    count: int
    events: list[MapEvent]
