import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .models import EventEnvelope
from .providers import dallas_open_data_events, weather_events, traffic_camera_events
from .store import EventStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
store = EventStore(retention_hours=settings.replay_retention_hours)
refresh_task = None


async def refresh_once():
    events = []
    statuses = []

    # Camera locations are always loaded (static data, no API call)
    cam_events, cam_status = traffic_camera_events()
    events.extend(cam_events)
    statuses.append(cam_status)

    if settings.use_live_feeds:
        logger.info("Refreshing live feeds…")
        weather_list, weather_status = await weather_events(settings)
        live_events, live_statuses = await dallas_open_data_events(settings)
        events.extend(weather_list)
        events.extend(live_events)
        statuses.append(weather_status)
        statuses.extend(live_statuses)
        logger.info("Live refresh: %d events from %d feed(s)", len(events), len(statuses))
    else:
        logger.info("Live feeds disabled; no data to load.")

    await store.upsert_many(events)
    await store.set_feed_status(statuses)


async def refresh_loop():
    while True:
        try:
            await refresh_once()
        except Exception:
            pass
        await asyncio.sleep(settings.refresh_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global refresh_task
    await refresh_once()
    refresh_task = asyncio.create_task(refresh_loop())
    try:
        yield
    finally:
        if refresh_task:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_layers(layers: str | None):
    if not layers:
        return None
    parsed = {item.strip() for item in layers.split(",") if item.strip()}
    return parsed or None


def filter_bbox(events, min_lat: float | None, max_lat: float | None, min_lon: float | None, max_lon: float | None):
    if None in (min_lat, max_lat, min_lon, max_lon):
        return events
    return [event for event in events if min_lat <= event.lat <= max_lat and min_lon <= event.lon <= max_lon]


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/meta")
async def meta():
    return {
        "city": "Dallas",
        "center": {"lat": settings.dallas_lat, "lon": settings.dallas_lon},
        "refreshIntervalSeconds": settings.refresh_interval_seconds,
        "retentionHours": settings.replay_retention_hours,
    }


@app.get("/api/layers")
async def layers():
    counts = await store.layer_counts()
    return {
        "layers": [
            {"id": "weather", "label": "Weather", "count": counts.get("weather", 0)},
            {"id": "traffic", "label": "Traffic / Active Calls", "count": counts.get("traffic", 0)},
            {"id": "incidents", "label": "Incidents", "count": counts.get("incidents", 0)},
            {"id": "crime", "label": "Crime", "count": counts.get("crime", 0)},
            {"id": "cameras", "label": "Traffic Cameras", "count": counts.get("cameras", 0)},
        ]
    }


@app.get("/api/feed-status")
async def feed_status():
    statuses = await store.feed_status()
    return {"feeds": [status.model_dump(mode="json") for status in statuses]}


@app.get("/api/events/current", response_model=EventEnvelope)
async def current_events(
    layers: str | None = Query(default=None),
    min_lat: float | None = Query(default=None),
    max_lat: float | None = Query(default=None),
    min_lon: float | None = Query(default=None),
    max_lon: float | None = Query(default=None),
):
    parsed_layers = parse_layers(layers)
    events = await store.current(parsed_layers)
    events = filter_bbox(events, min_lat, max_lat, min_lon, max_lon)
    now = datetime.now(timezone.utc)
    return EventEnvelope(mode="live", as_of=now, count=len(events), events=events)


@app.get("/api/events/replay", response_model=EventEnvelope)
async def replay_events(
    minutes_ago: int = Query(default=30, ge=0, le=1440),
    layers: str | None = Query(default=None),
    min_lat: float | None = Query(default=None),
    max_lat: float | None = Query(default=None),
    min_lon: float | None = Query(default=None),
    max_lon: float | None = Query(default=None),
):
    parsed_layers = parse_layers(layers)
    events = await store.replay(minutes_ago=minutes_ago, layers=parsed_layers)
    events = filter_bbox(events, min_lat, max_lat, min_lon, max_lon)
    as_of = datetime.now(timezone.utc)
    return EventEnvelope(mode="replay", as_of=as_of, count=len(events), events=events)
