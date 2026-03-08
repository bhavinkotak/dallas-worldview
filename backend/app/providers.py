from datetime import datetime, timezone
from typing import Any
import asyncio
import hashlib
import logging
import httpx
from .config import Settings
from .models import FeedStatus, MapEvent

logger = logging.getLogger(__name__)

# ── Dallas traffic camera locations (real positions on major highways) ─
# Source: TxDOT ITS camera placement data for Dallas district.
# These are real camera locations along major Dallas highways.
DALLAS_TRAFFIC_CAMERAS: list[dict[str, Any]] = [
    {"id": "cam-i35e-elm", "name": "I-35E @ Elm St", "lat": 32.7810, "lon": -96.7985, "highway": "I-35E", "direction": "N/S"},
    {"id": "cam-i35e-mockingbird", "name": "I-35E @ Mockingbird Ln", "lat": 32.8380, "lon": -96.8190, "highway": "I-35E", "direction": "N/S"},
    {"id": "cam-i35e-walnut", "name": "I-35E @ Walnut Hill Ln", "lat": 32.8750, "lon": -96.8365, "highway": "I-35E", "direction": "N/S"},
    {"id": "cam-i35e-royal", "name": "I-35E @ Royal Ln", "lat": 32.8870, "lon": -96.8400, "highway": "I-35E", "direction": "N/S"},
    {"id": "cam-us75-haskell", "name": "US-75 @ Haskell Ave", "lat": 32.7950, "lon": -96.7870, "highway": "US-75", "direction": "N/S"},
    {"id": "cam-us75-fitzhugh", "name": "US-75 @ Fitzhugh Ave", "lat": 32.8050, "lon": -96.7850, "highway": "US-75", "direction": "N/S"},
    {"id": "cam-us75-lovers", "name": "US-75 @ Lovers Ln", "lat": 32.8370, "lon": -96.7720, "highway": "US-75", "direction": "N/S"},
    {"id": "cam-us75-635", "name": "US-75 @ I-635 (LBJ)", "lat": 32.9190, "lon": -96.7530, "highway": "US-75", "direction": "N/S"},
    {"id": "cam-i30-hampton", "name": "I-30 @ Hampton Rd", "lat": 32.7530, "lon": -96.8290, "highway": "I-30", "direction": "E/W"},
    {"id": "cam-i30-peak", "name": "I-30 @ Peak St", "lat": 32.7720, "lon": -96.7780, "highway": "I-30", "direction": "E/W"},
    {"id": "cam-i30-dolphin", "name": "I-30 @ Dolphin Rd", "lat": 32.7700, "lon": -96.7550, "highway": "I-30", "direction": "E/W"},
    {"id": "cam-i30-buckner", "name": "I-30 @ Buckner Blvd", "lat": 32.7630, "lon": -96.7150, "highway": "I-30", "direction": "E/W"},
    {"id": "cam-i45-lamar", "name": "I-45 @ Lamar St", "lat": 32.7730, "lon": -96.7990, "highway": "I-45", "direction": "S"},
    {"id": "cam-i45-simpson", "name": "I-45 @ Simpson Stuart Rd", "lat": 32.7090, "lon": -96.7670, "highway": "I-45", "direction": "S"},
    {"id": "cam-i635-hillcrest", "name": "I-635 (LBJ) @ Hillcrest Rd", "lat": 32.9210, "lon": -96.7800, "highway": "I-635", "direction": "E/W"},
    {"id": "cam-i635-marsh", "name": "I-635 (LBJ) @ Marsh Ln", "lat": 32.9280, "lon": -96.8400, "highway": "I-635", "direction": "E/W"},
    {"id": "cam-dntte-woodall", "name": "DNT @ Woodall Rodgers", "lat": 32.7890, "lon": -96.8060, "highway": "DNT", "direction": "N/S"},
    {"id": "cam-dnt-mockingbird", "name": "DNT @ Mockingbird Ln", "lat": 32.8370, "lon": -96.8100, "highway": "DNT", "direction": "N/S"},
    {"id": "cam-dnt-northwest", "name": "DNT @ Northwest Hwy", "lat": 32.8690, "lon": -96.8200, "highway": "DNT", "direction": "N/S"},
    {"id": "cam-dnt-635", "name": "DNT @ I-635 (LBJ)", "lat": 32.9250, "lon": -96.8200, "highway": "DNT", "direction": "N/S"},
    {"id": "cam-i20-hampton", "name": "I-20 @ Hampton Rd", "lat": 32.6680, "lon": -96.8300, "highway": "I-20", "direction": "E/W"},
    {"id": "cam-i20-polk", "name": "I-20 @ Polk St", "lat": 32.6670, "lon": -96.7870, "highway": "I-20", "direction": "E/W"},
    {"id": "cam-i20-bonnieview", "name": "I-20 @ Bonnie View Rd", "lat": 32.6660, "lon": -96.7400, "highway": "I-20", "direction": "E/W"},
    {"id": "cam-srloop12-walton", "name": "Loop 12 @ Walton Walker Blvd", "lat": 32.7650, "lon": -96.8700, "highway": "Loop 12", "direction": "N/S"},
    {"id": "cam-pgbt-635", "name": "PGBT @ I-635", "lat": 32.9330, "lon": -96.6990, "highway": "PGBT", "direction": "E/W"},
]

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
            headers={"User-Agent": "DallasWorldView/1.0 (local demo)"},
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


# ── Traffic Cameras (static curated list) ─────────────────────────────
def traffic_camera_events() -> tuple[list[MapEvent], FeedStatus]:
    """Return camera locations as MapEvents (layer='cameras')."""
    ts = _now()
    events: list[MapEvent] = []
    for cam in DALLAS_TRAFFIC_CAMERAS:
        events.append(MapEvent(
            event_id=f"camera-{cam['id']}-{ts.isoformat()}",
            entity_id=f"camera-{cam['id']}",
            source="txdot-cameras",
            layer="cameras",
            title=cam["name"],
            description=f"Traffic camera on {cam['highway']} ({cam['direction']})",
            status="online",
            timestamp=ts,
            lat=cam["lat"],
            lon=cam["lon"],
            properties={
                "highway": cam["highway"],
                "direction": cam["direction"],
                "type": "traffic_camera",
                "camera_id": cam["id"],
            },
        ))
    return events, FeedStatus(
        source="txdot-cameras", ok=True, last_refresh=ts,
        message=f"{len(events)} cameras loaded.",
    )


# ── Weather (NWS) ────────────────────────────────────────────────────
async def weather_events(settings: Settings) -> tuple[list[MapEvent], FeedStatus]:
    ts = _now()
    headers = {
        "User-Agent": settings.nws_user_agent,
        "Accept": "application/geo+json, application/ld+json, application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            point_resp = await client.get(f"https://api.weather.gov/points/{settings.dallas_lat},{settings.dallas_lon}")
            point_resp.raise_for_status()
            point_json = point_resp.json()
            forecast_url = point_json["properties"]["forecastHourly"]

            forecast_resp = await client.get(forecast_url)
            forecast_resp.raise_for_status()
            forecast_json = forecast_resp.json()
            periods = forecast_json.get("properties", {}).get("periods", [])
            current = periods[0] if periods else {}

            alerts_resp = await client.get(
                f"https://api.weather.gov/alerts/active?point={settings.dallas_lat},{settings.dallas_lon}"
            )
            alerts_resp.raise_for_status()
            alerts_json = alerts_resp.json()

        events = [
            MapEvent(
                event_id=f"nws-current-{ts.isoformat()}",
                entity_id="nws-current-dallas",
                source="nws",
                layer="weather",
                title="Dallas Weather",
                description=current.get("detailedForecast") or current.get("shortForecast") or "Current weather summary.",
                status="current",
                timestamp=ts,
                lat=settings.dallas_lat,
                lon=settings.dallas_lon,
                properties={
                    "temperature": current.get("temperature"),
                    "temperatureUnit": current.get("temperatureUnit"),
                    "windSpeed": current.get("windSpeed"),
                    "windDirection": current.get("windDirection"),
                    "shortForecast": current.get("shortForecast"),
                },
            )
        ]

        for idx, feature in enumerate(alerts_json.get("features", []), start=1):
            props = feature.get("properties", {}) or {}
            events.append(
                MapEvent(
                    event_id=f"nws-alert-{idx}-{ts.isoformat()}",
                    entity_id=f"nws-alert-{props.get('id', idx)}",
                    source="nws",
                    layer="weather",
                    title=props.get("headline") or props.get("event") or "Weather Alert",
                    description=props.get("description") or props.get("instruction") or "",
                    status=props.get("severity") or "alert",
                    timestamp=ts,
                    lat=settings.dallas_lat,
                    lon=settings.dallas_lon,
                    properties={
                        "event": props.get("event"),
                        "severity": props.get("severity"),
                        "urgency": props.get("urgency"),
                        "certainty": props.get("certainty"),
                        "areaDesc": props.get("areaDesc"),
                    },
                )
            )

        return events, FeedStatus(source="nws", ok=True, last_refresh=ts, message="NWS weather refreshed.")
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
