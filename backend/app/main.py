import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .models import EventEnvelope
from .providers import dallas_open_data_events, weather_events, traffic_camera_events, ccm_crime_events
from .store import EventStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
store = EventStore(retention_hours=settings.replay_retention_hours)
refresh_task = None

# ── City / Area Configuration ─────────────────────────────────────────
# Single source of truth for all supported cities, places, and bounding boxes.
# Frontend fetches this via /api/cities to build dropdowns and camera positions.
CITY_CONFIG = {
    "states": [
        {
            "code": "TX",
            "name": "Texas",
            "cities": [
                {
                    "id": "dallas",
                    "name": "Dallas",
                    "lat": 32.7767,
                    "lon": -96.797,
                    "data_sources": ["dallas-opendata", "ccm", "nws", "drivetexas"],
                    "places": [
                        {"label": "All Dallas", "lat": 32.7767, "lon": -96.797, "height": 25000, "heading": 0, "pitch": -60, "bbox": None},
                        {"label": "Downtown Dallas", "lat": 32.7767, "lon": -96.797, "height": 2200, "heading": 15, "pitch": -40, "bbox": [32.755, 32.800, -96.820, -96.775]},
                        {"label": "Dallas City Hall", "lat": 32.7763, "lon": -96.7969, "height": 1600, "heading": 0, "pitch": -35, "bbox": [32.760, 32.790, -96.815, -96.780]},
                        {"label": "Deep Ellum", "lat": 32.7843, "lon": -96.781, "height": 1600, "heading": 45, "pitch": -35, "bbox": [32.770, 32.800, -96.800, -96.760]},
                        {"label": "Fair Park", "lat": 32.7792, "lon": -96.7597, "height": 2200, "heading": -30, "pitch": -40, "bbox": [32.760, 32.800, -96.780, -96.740]},
                        {"label": "Love Field", "lat": 32.8471, "lon": -96.8517, "height": 4200, "heading": 10, "pitch": -50, "bbox": [32.825, 32.870, -96.880, -96.825]},
                        {"label": "DFW Airport", "lat": 32.8998, "lon": -97.0403, "height": 6500, "heading": 0, "pitch": -55, "bbox": [32.860, 32.940, -97.100, -96.980]},
                        {"label": "Bishop Arts", "lat": 32.7493, "lon": -96.8278, "height": 2200, "heading": 20, "pitch": -35, "bbox": [32.730, 32.770, -96.850, -96.810]},
                        {"label": "White Rock Lake", "lat": 32.8269, "lon": -96.7246, "height": 3600, "heading": -15, "pitch": -45, "bbox": [32.800, 32.860, -96.760, -96.690]},
                        {"label": "Reunion Tower", "lat": 32.7755, "lon": -96.8088, "height": 1400, "heading": 30, "pitch": -30, "bbox": [32.760, 32.790, -96.825, -96.790]},
                        {"label": "Uptown", "lat": 32.7990, "lon": -96.8025, "height": 2000, "heading": -10, "pitch": -35, "bbox": [32.785, 32.815, -96.820, -96.785]},
                    ],
                },
                {
                    "id": "mckinney",
                    "name": "McKinney",
                    "lat": 33.1972,
                    "lon": -96.6397,
                    "data_sources": ["ccm", "nws", "drivetexas"],
                    "places": [
                        {"label": "McKinney", "lat": 33.1972, "lon": -96.6397, "height": 4500, "heading": 0, "pitch": -45, "bbox": [33.150, 33.240, -96.700, -96.580]},
                        {"label": "McKinney Downtown", "lat": 33.1986, "lon": -96.6152, "height": 2000, "heading": 10, "pitch": -35, "bbox": [33.190, 33.210, -96.630, -96.600]},
                    ],
                },
                {
                    "id": "frisco",
                    "name": "Frisco",
                    "lat": 33.1507,
                    "lon": -96.8236,
                    "data_sources": ["ccm", "nws", "drivetexas"],
                    "places": [
                        {"label": "Frisco", "lat": 33.1507, "lon": -96.8236, "height": 4500, "heading": 0, "pitch": -45, "bbox": [33.100, 33.200, -96.890, -96.760]},
                    ],
                },
                {
                    "id": "plano",
                    "name": "Plano",
                    "lat": 33.0198,
                    "lon": -96.6989,
                    "data_sources": ["ccm", "nws", "drivetexas"],
                    "places": [
                        {"label": "Plano", "lat": 33.0198, "lon": -96.6989, "height": 4500, "heading": 0, "pitch": -45, "bbox": [32.980, 33.070, -96.760, -96.640]},
                    ],
                },
            ],
        },
    ],
}


async def refresh_once():
    events = []
    statuses = []

    # Camera locations from DriveTexas/MapLarge (live feed with caching)
    cam_events, cam_status = await traffic_camera_events()
    events.extend(cam_events)
    statuses.append(cam_status)

    if settings.use_live_feeds:
        logger.info("Refreshing live feeds…")
        weather_list, weather_status = await weather_events(settings)
        live_events, live_statuses = await dallas_open_data_events(settings)
        ccm_events_list, ccm_status = await ccm_crime_events()
        events.extend(weather_list)
        events.extend(live_events)
        events.extend(ccm_events_list)
        statuses.append(weather_status)
        statuses.extend(live_statuses)
        statuses.append(ccm_status)
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
        "app": "US RealView",
        "center": {"lat": settings.default_lat, "lon": settings.default_lon},
        "refreshIntervalSeconds": settings.refresh_interval_seconds,
        "retentionHours": settings.replay_retention_hours,
    }


@app.get("/api/cities")
async def cities():
    """Return the full city/state/places configuration for the frontend."""
    return CITY_CONFIG


@app.get("/api/layers")
async def layers():
    counts = await store.layer_counts()
    return {
        "layers": [
            {"id": "weather", "label": "Weather", "count": counts.get("weather", 0)},
            {"id": "traffic", "label": "Traffic / Active Calls", "count": counts.get("traffic", 0)},
            {"id": "incidents", "label": "Incidents", "count": counts.get("incidents", 0)},
            {"id": "crime", "label": "Crime (DFW-wide)", "count": counts.get("crime", 0)},
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
