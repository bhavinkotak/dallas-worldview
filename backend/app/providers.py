from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio
import hashlib
import logging
import re
import json
import urllib.parse
import httpx
from .config import Settings
from .models import FeedStatus, MapEvent

logger = logging.getLogger(__name__)

# ── DriveTexas / MapLarge camera API configuration ────────────────────
# Source: DriveTexas.org uses MapLarge CDN for live traffic cameras across Texas.
# We query the cameraPoint table and filter to the Dallas metro area.
MAPLARGE_HOST = "dtx-e-cdn.maplarge.com"
MAPLARGE_TABLE = "appgeo/cameraPoint"
MAPLARGE_FIELDS = [
    "name", "description", "route", "jurisdiction", "direction",
    "httpsurl", "imageurl", "active", "XY",
]
# DFW metro bounding box: expanded to cover McKinney, Frisco, Plano, etc.
DALLAS_CAM_BBOX = {"min_lat": 32.5, "max_lat": 33.35, "min_lon": -97.5, "max_lon": -96.4}

# In-memory camera cache (refreshed periodically alongside other feeds)
_camera_cache: list[dict[str, Any]] = []
_camera_cache_ts: datetime | None = None
_CAMERA_CACHE_TTL_SECONDS = 120  # refresh every 2 minutes

# ── Dallas police‑beat approximate centroids ──────────────────────────
# These map 3‑digit beat numbers to approximate (lat, lon).
# Used as fallback when Nominatim cannot resolve an address.
BEAT_CENTROIDS: dict[str, tuple[float, float]] = {
    # Central
    "111": (32.7900, -96.8020), "112": (32.7850, -96.8050), "113": (32.7830, -96.7950),
    "114": (32.7780, -96.7970), "115": (32.7700, -96.7900), "116": (32.7750, -96.7800),
    "121": (32.7950, -96.8100), "122": (32.7980, -96.8000), "123": (32.8000, -96.7900),
    "131": (32.8050, -96.7850), "132": (32.8100, -96.8000), "133": (32.8000, -96.8150),
    "141": (32.7650, -96.7850), "142": (32.7600, -96.7900), "143": (32.7550, -96.8000),
    "151": (32.7700, -96.7700), "152": (32.7750, -96.7650), "153": (32.7800, -96.7600),
    "154": (32.7680, -96.7550), "155": (32.7850, -96.7500),
    # Northeast
    "211": (32.8400, -96.7200), "212": (32.8350, -96.7100), "213": (32.8300, -96.7000),
    "221": (32.8550, -96.7400), "222": (32.8600, -96.7300), "223": (32.8650, -96.7150),
    "224": (32.8500, -96.7050), "225": (32.8700, -96.7250),
    "231": (32.8400, -96.6900), "232": (32.8500, -96.6800), "233": (32.8600, -96.6700),
    "234": (32.8350, -96.6750), "235": (32.8450, -96.6650),
    # Southeast
    "311": (32.7500, -96.7400), "312": (32.7450, -96.7300), "313": (32.7400, -96.7200),
    "314": (32.7350, -96.7150), "315": (32.7300, -96.7050),
    "321": (32.7200, -96.7300), "322": (32.7150, -96.7200), "323": (32.7100, -96.7100),
    "331": (32.7000, -96.7400), "332": (32.6950, -96.7300), "333": (32.6900, -96.7150),
    "341": (32.7250, -96.7500), "342": (32.7200, -96.7600), "343": (32.7150, -96.7700),
    "344": (32.7300, -96.7700), "345": (32.7350, -96.7550), "346": (32.7400, -96.7450),
    "351": (32.6800, -96.7200), "352": (32.6750, -96.7100), "353": (32.6700, -96.7000),
    "354": (32.6850, -96.6900), "355": (32.6900, -96.6800), "356": (32.6800, -96.6700),
    # Southwest
    "411": (32.7500, -96.8300), "412": (32.7450, -96.8400), "413": (32.7400, -96.8500),
    "414": (32.7350, -96.8600), "415": (32.7300, -96.8700), "416": (32.7250, -96.8450),
    "421": (32.7200, -96.8500), "422": (32.7150, -96.8600), "423": (32.7100, -96.8700),
    "430": (32.7000, -96.8500), "431": (32.6950, -96.8600), "432": (32.6900, -96.8700),
    "433": (32.6850, -96.8550), "434": (32.7050, -96.8400),
    "441": (32.6800, -96.8800), "442": (32.6750, -96.8900), "443": (32.6700, -96.9000),
    "451": (32.6600, -96.8700), "452": (32.6550, -96.8800), "453": (32.6500, -96.8900),
    # North Central
    "611": (32.8700, -96.7700), "612": (32.8750, -96.7800), "613": (32.8800, -96.7900),
    "614": (32.8650, -96.7600), "615": (32.8600, -96.7750),
    "621": (32.8900, -96.7700), "622": (32.8950, -96.7800), "623": (32.9000, -96.7900),
    "631": (32.9100, -96.7600), "632": (32.9150, -96.7700), "633": (32.9200, -96.7800),
    "641": (32.9300, -96.7700), "642": (32.9350, -96.7800), "643": (32.9400, -96.7900),
    # Northwest
    "711": (32.8600, -96.8700), "712": (32.8650, -96.8800), "713": (32.8700, -96.8900),
    "721": (32.8800, -96.8700), "722": (32.8850, -96.8800), "723": (32.8900, -96.8900),
    "731": (32.9000, -96.8700), "732": (32.9050, -96.8800), "733": (32.9100, -96.8900),
    "741": (32.9200, -96.8700), "742": (32.9250, -96.8800), "743": (32.9300, -96.8900),
    "751": (32.8500, -96.8500), "752": (32.8550, -96.8600),
}

# Division‑level fallback centres
DIVISION_CENTROIDS: dict[str, tuple[float, float]] = {
    "central":       (32.7800, -96.7970),
    "northeast":     (32.8500, -96.7100),
    "southeast":     (32.7200, -96.7300),
    "southwest":     (32.7100, -96.8600),
    "north central": (32.9000, -96.7800),
    "northwest":     (32.8900, -96.8800),
    "south central": (32.7000, -96.7900),
}

# ── In‑memory geocode cache (survives across refreshes) ──────────────
_geocode_cache: dict[str, tuple[float, float] | None] = {}
_geocode_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: Any):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _extract_lat_lon(record: dict[str, Any]):
    """Try every common coordinate pattern in the record."""
    pairs = [
        ("latitude", "longitude"),
        ("lat", "lon"),
        ("lat", "lng"),
        ("y", "x"),
        ("ycoord", "xcoord"),
        ("y_coordinate", "x_coordinate"),
    ]
    for lat_key, lon_key in pairs:
        lat = _safe_float(record.get(lat_key))
        lon = _safe_float(record.get(lon_key))
        if lat is not None and lon is not None:
            return lat, lon

    for key in ["location", "location_1", "location1", "geocoded_column", "point", "shape", "geocoded_column_1"]:
        value = record.get(key)
        if isinstance(value, dict):
            coords = value.get("coordinates")
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                return float(coords[1]), float(coords[0])
            lat = _safe_float(value.get("latitude"))
            lon = _safe_float(value.get("longitude"))
            if lat is not None and lon is not None:
                return lat, lon
    return None, None


def _beat_or_division_centroid(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Resolve coordinates from beat number or division name."""
    beat = str(record.get("beat", "")).strip()
    if beat and beat in BEAT_CENTROIDS:
        return BEAT_CENTROIDS[beat]

    division = str(record.get("division", "")).strip().lower()
    if division and division in DIVISION_CENTROIDS:
        return DIVISION_CENTROIDS[division]

    return None, None


async def _geocode_address(block: str, street: str, client: httpx.AsyncClient) -> tuple[float | None, float | None]:
    """Geocode a Dallas address via Nominatim with caching."""
    address = f"{block} {street}, Dallas, TX".strip()
    cache_key = hashlib.md5(address.lower().encode()).hexdigest()

    async with _geocode_lock:
        if cache_key in _geocode_cache:
            result = _geocode_cache[cache_key]
            return result if result else (None, None)

    try:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": "1", "countrycodes": "us"},
            headers={"User-Agent": "USRealView/1.0 (local demo)"},
        )
        if resp.status_code == 429:
            # Rate limited — do NOT cache, try again later
            return None, None
        resp.raise_for_status()
        results = resp.json()
        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            async with _geocode_lock:
                _geocode_cache[cache_key] = (lat, lon)
            return lat, lon
    except Exception:
        pass

    # Cache only confirmed "not found" (successful 200 with empty results)
    async with _geocode_lock:
        _geocode_cache[cache_key] = None
    return None, None


def _string_or_default(record: dict[str, Any], keys: list[str], default: str):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return default


# ── Traffic Cameras (live from DriveTexas / MapLarge) ─────────────────
async def _fetch_cameras_from_maplarge() -> list[dict[str, Any]]:
    """Fetch all Texas traffic cameras from the MapLarge API and filter to Dallas area."""
    query = {
        "action": "table/query",
        "query": {
            "sqlselect": MAPLARGE_FIELDS,
            "start": 0,
            "table": MAPLARGE_TABLE,
            "take": 5000,
            "where": [],
        },
    }
    req_str = json.dumps(query, separators=(",", ":"))
    encoded = urllib.parse.quote(req_str, safe="")
    url = f"https://{MAPLARGE_HOST}/Api/ProcessDirect?request={encoded}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.content
            # Strip UTF-8 BOM if present
            if raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            data = json.loads(raw)

        cols = data.get("data", {}).get("data", {})
        total = data.get("data", {}).get("totals", {}).get("Records", 0)
        names = cols.get("name", [])
        if not names:
            logger.warning("MapLarge returned no camera data (total=%s)", total)
            return []

        cameras: list[dict[str, Any]] = []
        bbox = DALLAS_CAM_BBOX
        for i in range(len(names)):
            xy = cols.get("XY", [""])[i]
            m = re.match(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", xy)
            if not m:
                continue
            lng, lat = float(m.group(1)), float(m.group(2))
            # Filter to Dallas metro area
            if not (bbox["min_lat"] <= lat <= bbox["max_lat"] and bbox["min_lon"] <= lng <= bbox["max_lon"]):
                continue
            # Skip inactive cameras
            if cols.get("active", [1])[i] != 1:
                continue
            cameras.append({
                "name": names[i],
                "description": cols.get("description", [""])[i],
                "route": cols.get("route", [""])[i],
                "jurisdiction": cols.get("jurisdiction", [""])[i],
                "direction": cols.get("direction", [""])[i],
                "httpsurl": cols.get("httpsurl", [""])[i],
                "imageurl": cols.get("imageurl", [""])[i],
                "lat": lat,
                "lng": lng,
            })

        logger.info("MapLarge: %d total cameras, %d in Dallas area", total, len(cameras))
        return cameras

    except Exception as exc:
        logger.exception("Failed to fetch cameras from MapLarge: %s", exc)
        return []


async def traffic_camera_events() -> tuple[list[MapEvent], FeedStatus]:
    """Return camera locations as MapEvents (layer='cameras') from DriveTexas/MapLarge."""
    global _camera_cache, _camera_cache_ts
    ts = _now()

    # Use cache if fresh enough
    if _camera_cache_ts and (ts - _camera_cache_ts).total_seconds() < _CAMERA_CACHE_TTL_SECONDS and _camera_cache:
        cameras = _camera_cache
    else:
        cameras = await _fetch_cameras_from_maplarge()
        if cameras:
            _camera_cache = cameras
            _camera_cache_ts = ts
        elif _camera_cache:
            # Keep stale cache on fetch failure
            cameras = _camera_cache

    events: list[MapEvent] = []
    for cam in cameras:
        events.append(MapEvent(
            event_id=f"camera-{cam['name']}-{ts.isoformat()}",
            entity_id=f"camera-{cam['name']}",
            source="drivetexas",
            layer="cameras",
            title=cam["description"] or cam["name"],
            description=f"{cam['route']} — {cam['direction']} ({cam['jurisdiction']})",
            status="online",
            timestamp=ts,
            lat=cam["lat"],
            lon=cam["lng"],
            properties={
                "camera_id": cam["name"],
                "highway": cam["route"],
                "direction": cam["direction"],
                "jurisdiction": cam["jurisdiction"],
                "type": "traffic_camera",
                "httpsurl": cam["httpsurl"],
                "stream_url": cam["httpsurl"],
            },
        ))
    return events, FeedStatus(
        source="drivetexas", ok=bool(events), last_refresh=ts,
        message=f"{len(events)} live cameras from DriveTexas.",
    )


# ── Community Crime Map (LexisNexis) ─────────────────────────────────
# Works across ALL DFW cities — not limited to Dallas Open Data.
# API: https://communitycrimemap.com/api/
CCM_BASE = "https://communitycrimemap.com/api/"
_ccm_token: str | None = None
_ccm_token_ts: datetime | None = None
_CCM_TOKEN_TTL = 7200  # refresh JWT every 2 hours
# Full DFW metro bounding box for agency + data queries
DFW_BBOX = {"south": 32.50, "north": 33.35, "west": -97.50, "east": -96.40}


async def _ccm_get_token(client: httpx.AsyncClient) -> str | None:
    """Get an anonymous JWT from the Community Crime Map API."""
    global _ccm_token, _ccm_token_ts
    now = _now()
    if _ccm_token and _ccm_token_ts and (now - _ccm_token_ts).total_seconds() < _CCM_TOKEN_TTL:
        return _ccm_token
    try:
        resp = await client.get(CCM_BASE + "v1/auth/newToken")
        resp.raise_for_status()
        _ccm_token = resp.json()["data"]["jwt"]
        _ccm_token_ts = now
        return _ccm_token
    except Exception as exc:
        logger.warning("CCM token fetch failed: %s", exc)
        return _ccm_token  # return stale if available


async def _ccm_get_layers(client: httpx.AsyncClient, token: str) -> dict:
    """Get crime type layers and build selection dict."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.get(CCM_BASE + "v1/search/map-layers", headers=headers)
    resp.raise_for_status()
    selection: dict[str, dict] = {}
    for group in resp.json().get("data", []):
        for grp in group.get("groups", []):
            for sg in grp.get("subgroups", []):
                selection[str(sg["id"])] = {"selected": True}
    return selection


async def _ccm_get_agencies(client: httpx.AsyncClient, token: str, bbox: dict) -> dict:
    """Get agencies for a bounding box and build agencies payload."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "MinLatitude": bbox["south"], "MaxLatitude": bbox["north"],
        "MinLongitude": bbox["west"], "MaxLongitude": bbox["east"],
    }
    resp = await client.get(CCM_BASE + "v1/search/agency-layers", headers=headers, params=params)
    resp.raise_for_status()
    agencies: dict[str, dict] = {}
    for agency in resp.json().get("data", []):
        # Select first 2 groups per agency with empty dict (= all layers)
        for grp in agency.get("groups", [])[:2]:
            agencies[str(grp["id"])] = {}
    return agencies


async def ccm_crime_events() -> tuple[list[MapEvent], FeedStatus]:
    """Fetch recent crime data from Community Crime Map for all DFW agencies."""
    ts = _now()
    try:
        async with httpx.AsyncClient(
            timeout=25.0,
            headers={
                "User-Agent": "USRealView/1.0",
                "Content-Type": "application/json",
                "Origin": "https://communitycrimemap.com",
                "Referer": "https://communitycrimemap.com/",
            },
        ) as client:
            token = await _ccm_get_token(client)
            if not token:
                return [], FeedStatus(source="ccm-crime", ok=False, last_refresh=ts,
                                      message="Failed to obtain CCM token.")

            selection = await _ccm_get_layers(client, token)
            agencies = await _ccm_get_agencies(client, token, DFW_BBOX)

            if not selection:
                return [], FeedStatus(source="ccm-crime", ok=False, last_refresh=ts,
                                      message="No crime layers from CCM.")

            end = datetime.now()
            start = end - timedelta(days=14)

            payload = {
                "buffer": {"enabled": False, "restrictArea": False, "value": []},
                "date": {"start": start.strftime("%m/%d/%Y"), "end": end.strftime("%m/%d/%Y")},
                "agencies": agencies,
                "layers": {"selection": selection},
                "location": {
                    "lat": (DFW_BBOX["south"] + DFW_BBOX["north"]) / 2,
                    "lng": (DFW_BBOX["west"] + DFW_BBOX["east"]) / 2,
                    "zoom": 10,
                    "bounds": DFW_BBOX,
                },
                "analyticLayers": {"density": {"selected": False, "transparency": 60}},
            }

            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.post(CCM_BASE + "v1/search/load-data",
                                     json=payload, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        data = result.get("data", result)
        grid_eve = data.get("grid", {}).get("eve", [])

        events: list[MapEvent] = []
        for rec in grid_eve:
            lat = _safe_float(rec.get("YCoordinate"))
            lon = _safe_float(rec.get("XCoordinate"))
            if lat is None or lon is None:
                continue

            ir = rec.get("IRNumber", "")
            entity_key = ir or f"ccm-{len(events)}"
            crime_class = rec.get("Class", rec.get("label", "Crime"))
            crime_desc = rec.get("Crime", crime_class)
            address = rec.get("AddressOfCrime", "")
            dt_str = rec.get("DateTime", "")
            agency = rec.get("Agency", "")

            events.append(MapEvent(
                event_id=f"ccm-{entity_key}-{ts.isoformat()}",
                entity_id=f"ccm-{entity_key}",
                source="ccm",
                layer="crime",
                title=crime_desc or crime_class,
                description=f"{address} — {agency}" if address else agency,
                status="reported",
                timestamp=ts,
                lat=lat,
                lon=lon,
                properties={
                    "crime_class": crime_class,
                    "crime": crime_desc,
                    "ir_number": ir,
                    "address": address,
                    "location_type": rec.get("LocationType", ""),
                    "datetime": dt_str,
                    "agency": agency,
                    "ucr_group": rec.get("UCRGroup", ""),
                    "source_api": "communitycrimemap",
                },
            ))

        logger.info("CCM: %d crime events from %d grid records", len(events), len(grid_eve))
        return events, FeedStatus(
            source="ccm-crime", ok=True, last_refresh=ts,
            message=f"{len(events)} crime events from Community Crime Map ({len(grid_eve)} records).",
        )

    except Exception as exc:
        logger.exception("CCM crime feed failed: %s", exc)
        return [], FeedStatus(source="ccm-crime", ok=False, last_refresh=ts, message=str(exc))


# ── Weather (NWS) ────────────────────────────────────────────────────
# Weather locations are now derived dynamically from city config.
# Pass locations via weather_events(settings, locations=[...])

# NWS grid-point cache (lat,lon → forecastHourly URL) — won't change
_nws_grid_cache: dict[str, str] = {}


async def weather_events(settings: Settings, locations: list[dict] | None = None) -> tuple[list[MapEvent], FeedStatus]:
    """Fetch NWS weather for each location. Locations auto-derived from city config."""
    ts = _now()
    nws_headers = {
        "User-Agent": settings.nws_user_agent,
        "Accept": "application/geo+json, application/ld+json, application/json",
    }
    all_events: list[MapEvent] = []
    errors: list[str] = []

    # Fallback if no locations provided
    if not locations:
        locations = [{"name": "Dallas", "lat": 32.7767, "lon": -96.797}]

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=nws_headers) as client:
            for loc in locations:
                try:
                    loc_key = f"{loc['lat']},{loc['lon']}"
                    slug = loc["name"].lower().replace(" ", "-")

                    # Resolve grid point (cached)
                    if loc_key not in _nws_grid_cache:
                        pt = await client.get(f"https://api.weather.gov/points/{loc_key}")
                        pt.raise_for_status()
                        _nws_grid_cache[loc_key] = pt.json()["properties"]["forecastHourly"]

                    forecast_url = _nws_grid_cache[loc_key]
                    fc = await client.get(forecast_url)
                    fc.raise_for_status()
                    periods = fc.json().get("properties", {}).get("periods", [])
                    current = periods[0] if periods else {}

                    all_events.append(MapEvent(
                        event_id=f"nws-current-{slug}-{ts.isoformat()}",
                        entity_id=f"nws-current-{slug}",
                        source="nws",
                        layer="weather",
                        title=f"{loc['name']} Weather",
                        description=current.get("detailedForecast") or current.get("shortForecast") or "Current weather summary.",
                        status="current",
                        timestamp=ts,
                        lat=loc["lat"],
                        lon=loc["lon"],
                        properties={
                            "temperature": current.get("temperature"),
                            "temperatureUnit": current.get("temperatureUnit"),
                            "windSpeed": current.get("windSpeed"),
                            "windDirection": current.get("windDirection"),
                            "shortForecast": current.get("shortForecast"),
                        },
                    ))

                    # Alerts for this location
                    al = await client.get(f"https://api.weather.gov/alerts/active?point={loc_key}")
                    al.raise_for_status()
                    for idx, feature in enumerate(al.json().get("features", []), start=1):
                        props = feature.get("properties", {}) or {}
                        all_events.append(MapEvent(
                            event_id=f"nws-alert-{slug}-{idx}-{ts.isoformat()}",
                            entity_id=f"nws-alert-{slug}-{props.get('id', idx)}",
                            source="nws",
                            layer="weather",
                            title=props.get("headline") or props.get("event") or "Weather Alert",
                            description=props.get("description") or props.get("instruction") or "",
                            status=props.get("severity") or "alert",
                            timestamp=ts,
                            lat=loc["lat"],
                            lon=loc["lon"],
                            properties={
                                "event": props.get("event"),
                                "severity": props.get("severity"),
                                "urgency": props.get("urgency"),
                                "certainty": props.get("certainty"),
                                "areaDesc": props.get("areaDesc"),
                            },
                        ))
                except Exception as loc_exc:
                    errors.append(f"{loc['name']}: {loc_exc}")

        msg = f"NWS weather: {len(all_events)} events for {len(locations)} locations."
        if errors:
            msg += f" Errors: {'; '.join(errors)}"
        return all_events, FeedStatus(source="nws", ok=bool(all_events), last_refresh=ts, message=msg)
    except Exception as exc:
        return [], FeedStatus(source="nws", ok=False, last_refresh=ts, message=str(exc))


# ── Dallas Open Data (traffic / incidents / crime) ───────────────────
async def dallas_open_data_events(settings: Settings) -> tuple[list[MapEvent], list[FeedStatus]]:
    ts = _now()
    statuses: list[FeedStatus] = []
    events: list[MapEvent] = []

    async def _fetch_with_geocoding(
        url: str,
        source: str,
        layer: str,
        title_keys: list[str],
        desc_keys: list[str],
        geocode: bool = False,
    ):
        """Fetch rows, extract or geocode coordinates, and return MapEvents."""
        try:
            async with httpx.AsyncClient(timeout=20.0, headers={"Accept": "application/json"}) as client:
                response = await client.get(url)
                response.raise_for_status()
                rows = response.json()

                if not isinstance(rows, list):
                    statuses.append(FeedStatus(source=source, ok=False, last_refresh=ts,
                                               message=f"Unexpected response type: {type(rows).__name__}"))
                    return []

                total_rows = len(rows)
                created: list[MapEvent] = []
                geocoded_count = 0
                beat_count = 0

                # Rate‑limit geocoding: at most ~25 per refresh cycle
                geocode_budget = 25

                for idx, row in enumerate(rows, start=1):
                    # 1) Try embedded coordinates first
                    lat, lon = _extract_lat_lon(row)

                    # 2) Geocode via Nominatim if address fields present
                    if (lat is None or lon is None) and geocode and geocode_budget > 0:
                        block = str(
                            row.get("block", "")
                            or row.get("offenseblock", "")
                        ).strip().lstrip("0").replace("xx", "00")
                        street = str(
                            row.get("location", "")
                            or row.get("incident_address", "")
                            or row.get("offensestreet", "")
                        ).strip()
                        if street:
                            lat, lon = await _geocode_address(block, street, client)
                            if lat is not None:
                                geocoded_count += 1
                            geocode_budget -= 1
                            # Tiny delay to respect Nominatim rate limit (1 req/sec)
                            await asyncio.sleep(1.1)

                    # 3) Fallback to beat / division centroid
                    if lat is None or lon is None:
                        # Support crime records where beat is "offensebeat"
                        beat_row = row
                        if "offensebeat" in row and "beat" not in row:
                            beat_row = {**row, "beat": row["offensebeat"]}
                        lat, lon = _beat_or_division_centroid(beat_row)
                        if lat is not None:
                            beat_count += 1

                    if lat is None or lon is None:
                        continue

                    # Validate coordinates are within Dallas metro area
                    if not (32.5 <= lat <= 33.1 and -97.5 <= lon <= -96.3):
                        continue

                    title = _string_or_default(row, title_keys, f"{layer.title()} {idx}")
                    description = _string_or_default(row, desc_keys, f"Dallas {layer} event.")
                    entity_key = (
                        row.get("incident_number")
                        or row.get("incidentnum")
                        or row.get("servnumid")
                        or row.get("offenseservicenumber")
                        or row.get("id")
                        or row.get("objectid")
                        or row.get("case_number")
                        or row.get("service_number_id")
                        or f"{layer}-{idx}"
                    )

                    created.append(
                        MapEvent(
                            event_id=f"{source}-{entity_key}-{ts.isoformat()}",
                            entity_id=f"{source}-{entity_key}",
                            source=source,
                            layer=layer,
                            title=title,
                            description=description,
                            status=_string_or_default(
                                row,
                                ["status", "priority", "offense_status", "severity",
                                 "type_of_incident", "offensestatus"],
                                "active",
                            ),
                            timestamp=ts,
                            lat=lat,
                            lon=lon,
                            properties=row,
                        )
                    )

                parts = [f"{len(created)}/{total_rows} records mapped"]
                if geocoded_count:
                    parts.append(f"{geocoded_count} geocoded")
                if beat_count:
                    parts.append(f"{beat_count} via beat centroid")
                statuses.append(FeedStatus(source=source, ok=True, last_refresh=ts,
                                           message="; ".join(parts) + "."))
                return created

        except Exception as exc:
            logger.exception("Feed %s failed", source)
            statuses.append(FeedStatus(source=source, ok=False, last_refresh=ts, message=str(exc)))
            return []

    # ── Traffic: active police calls (no native coords → geocode) ─────
    traffic = await _fetch_with_geocoding(
        settings.dallas_traffic_url,
        source="dallas-traffic",
        layer="traffic",
        title_keys=["nature_of_call", "location", "street", "description"],
        desc_keys=["status", "block", "location", "division", "beat", "priority"],
        geocode=True,
    )

    # ── Incidents: police incidents (has geocoded_column) ─────────────
    incidents = await _fetch_with_geocoding(
        settings.dallas_incidents_url,
        source="dallas-incidents",
        layer="incidents",
        title_keys=["offincident", "signal", "incident_address"],
        desc_keys=["incident_address", "premise", "division", "nibrs_crime_category"],
        geocode=False,
    )

    # ── Crime: offense records (beat centroid only — street names are concatenated/abbreviated) ──
    crimes = await _fetch_with_geocoding(
        settings.dallas_crimes_url,
        source="dallas-crimes",
        layer="crime",
        title_keys=["offensedescription", "offensename", "nibrs_crime_category"],
        desc_keys=["offenseblock", "offensestreet", "offensecity", "offensepremises"],
        geocode=False,
    )

    events.extend(traffic)
    events.extend(incidents)
    events.extend(crimes)
    return events, statuses
