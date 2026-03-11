"""
Global data providers for:
  - Real-time satellite tracking (CelesTrak TLE → SGP4 propagation)
  - Live commercial flight tracking (OpenSky Network)
  - Military flight tracking (ADS-B Exchange / OpenSky filters)
  - Seismic activity (USGS Earthquake API)
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import FeedStatus, MapEvent

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════
# SATELLITE TRACKING  (CelesTrak GP data — JSON format, no SGP4 needed)
# ═══════════════════════════════════════════════════════════════════════
# We fetch the "last 30 days" active satellite catalog from CelesTrak's
# GP (General Perturbations) endpoint which gives us current orbital
# elements already converted to a friendly JSON format.
# We sample a subset (visual / notable satellites) to keep the payload sane.

_CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"

# Notable satellite groups to fetch (small curated sets)
_SAT_GROUPS = [
    ("stations", "Space Stations"),       # ISS, Tiangong, etc.
    ("visual", "Bright Satellites"),       # ~150 visually bright objects
    ("active", "Active Geosynchronous"),   # GEO belt
]

_sat_cache: list[dict[str, Any]] = []
_sat_cache_ts: datetime | None = None
_SAT_CACHE_TTL = 300  # 5 min


async def _fetch_celestrak_group(client: httpx.AsyncClient, group: str) -> list[dict]:
    """Fetch one satellite group from CelesTrak GP JSON endpoint."""
    try:
        resp = await client.get(
            _CELESTRAK_URL,
            params={"GROUP": group, "FORMAT": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("CelesTrak fetch '%s' failed: %s", group, exc)
        return []


def _kepler_to_latlon(
    inclination_deg: float,
    raan_deg: float,
    mean_anomaly_deg: float,
    eccentricity: float,
    mean_motion: float,  # rev/day
    epoch_str: str,
) -> tuple[float, float, float]:
    """
    Approximate satellite sub-satellite point from Keplerian elements.
    This is a simplified ground-track projection — good enough for
    visualization on a globe without full SGP4.
    Returns (lat, lon, altitude_km).
    """
    try:
        inc = math.radians(inclination_deg)
        raan = math.radians(raan_deg)
        ma = math.radians(mean_anomaly_deg)

        # Approximate true anomaly ≈ mean anomaly for low eccentricity
        nu = ma + 2 * eccentricity * math.sin(ma)

        # Argument of latitude
        arg_lat = nu  # simplified: argument of perigee ≈ 0 for visualization

        # Sub-satellite latitude
        lat = math.degrees(math.asin(math.sin(inc) * math.sin(arg_lat)))

        # Parse epoch and compute elapsed time for longitude offset
        # Epoch format: "2024-01-15T12:00:00" or similar
        try:
            epoch = datetime.fromisoformat(epoch_str.replace("Z", "+00:00"))
            if epoch.tzinfo is None:
                epoch = epoch.replace(tzinfo=timezone.utc)
        except Exception:
            epoch = _now()

        elapsed_sec = (_now() - epoch).total_seconds()

        # Earth rotation rate: 7.2921159e-5 rad/s
        earth_rot = elapsed_sec * 7.2921159e-5

        # Ascending node longitude adjusted for Earth rotation
        lon = math.degrees(
            raan
            + math.atan2(
                math.cos(inc) * math.sin(arg_lat),
                math.cos(arg_lat),
            )
            - earth_rot
        )

        # Normalize longitude to -180..180
        lon = ((lon + 180) % 360) - 180

        # Approximate altitude from mean motion (rev/day)
        # a = (GM / (2π n)²)^(1/3), GM_earth = 3.986e14 m³/s²
        if mean_motion > 0:
            n = mean_motion / 86400.0 * 2 * math.pi  # rad/s
            a = (3.986004418e14 / (n * n)) ** (1.0 / 3.0)  # meters
            alt_km = (a - 6371000) / 1000.0
        else:
            alt_km = 400  # fallback

        return lat, lon, max(alt_km, 160)

    except Exception:
        return 0.0, 0.0, 400.0


async def satellite_events() -> tuple[list[MapEvent], FeedStatus]:
    """Fetch satellite positions from CelesTrak and return as MapEvents."""
    global _sat_cache, _sat_cache_ts
    ts = _now()

    if _sat_cache_ts and (ts - _sat_cache_ts).total_seconds() < _SAT_CACHE_TTL and _sat_cache:
        sats = _sat_cache
    else:
        sats = []
        try:
            async with httpx.AsyncClient(timeout=20.0, headers={
                "User-Agent": "USRealView/1.0"
            }) as client:
                tasks = [_fetch_celestrak_group(client, grp) for grp, _ in _SAT_GROUPS]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, list):
                        sats.extend(result)
            if sats:
                _sat_cache = sats
                _sat_cache_ts = ts
        except Exception as exc:
            logger.exception("Satellite fetch failed: %s", exc)
            sats = _sat_cache  # use stale

    events: list[MapEvent] = []
    seen_norad = set()

    for sat in sats:
        norad_id = str(sat.get("NORAD_CAT_ID", ""))
        if not norad_id or norad_id in seen_norad:
            continue
        seen_norad.add(norad_id)

        name = sat.get("OBJECT_NAME", f"SAT-{norad_id}")
        inc = float(sat.get("INCLINATION", 0))
        raan = float(sat.get("RA_OF_ASC_NODE", 0))
        ma = float(sat.get("MEAN_ANOMALY", 0))
        ecc = float(sat.get("ECCENTRICITY", 0))
        mm = float(sat.get("MEAN_MOTION", 15))
        epoch = sat.get("EPOCH", "")
        obj_type = sat.get("OBJECT_TYPE", "")
        country = sat.get("COUNTRY_CODE", "")

        lat, lon, alt_km = _kepler_to_latlon(inc, raan, ma, ecc, mm, epoch)

        # Classify orbit type
        if mm < 2:
            orbit_type = "GEO"
        elif mm < 6:
            orbit_type = "MEO"
        else:
            orbit_type = "LEO"

        events.append(MapEvent(
            event_id=f"sat-{norad_id}-{ts.isoformat()}",
            entity_id=f"sat-{norad_id}",
            source="celestrak",
            layer="satellites",
            title=name,
            description=f"NORAD {norad_id} | {orbit_type} | Alt {alt_km:.0f} km",
            status="tracking",
            timestamp=ts,
            lat=lat,
            lon=lon,
            altitude=alt_km,
            properties={
                "norad_id": norad_id,
                "object_name": name,
                "object_type": obj_type,
                "country_code": country,
                "orbit_type": orbit_type,
                "altitude_km": round(alt_km, 1),
                "inclination": round(inc, 2),
                "mean_motion": round(mm, 4),
                "eccentricity": round(ecc, 6),
                "epoch": epoch,
                "raan": round(raan, 2),
            },
        ))

    logger.info("Satellites: %d events from %d raw records", len(events), len(sats))
    return events, FeedStatus(
        source="celestrak",
        ok=bool(events),
        last_refresh=ts,
        message=f"{len(events)} satellites tracked from CelesTrak.",
    )


# ═══════════════════════════════════════════════════════════════════════
# LIVE FLIGHT TRACKING  (OpenSky Network REST API)
# ═══════════════════════════════════════════════════════════════════════
# OpenSky provides free unauthenticated access (rate limited).
# We fetch all states within a bounding box or globally.
# Military flights are identified by callsign patterns and special transponder codes.

_OPENSKY_URL = "https://opensky-network.org/api/states/all"

_flight_cache: list[dict[str, Any]] = []
_flight_cache_ts: datetime | None = None
_FLIGHT_CACHE_TTL = 15  # seconds

# Known military callsign prefixes (partial list)
_MILITARY_PREFIXES = {
    "RCH", "REACH", "DUKE", "VALOR", "DOOM", "VIPER", "HAWK",
    "FURY", "COBRA", "BLADE", "GHOST", "CHIEF", "NOBLE", "TOPCAT",
    "EVAC", "SAM", "EXEC", "NAVY", "ARMY", "USAF", "MCGA", "CG",
    "PAT", "TIGER", "WOLF", "RAPTOR", "EAGLE", "KNIGHT", "MAGIC",
    "TBIRD",
}

# Known military hex ranges (USA military ICAO24 blocks)
_MIL_HEX_RANGES = [
    ("ADF7C0", "ADF7FF"),  # USA mil
    ("AE0000", "AE7FFF"),  # USA mil
]


def _is_military(callsign: str, icao24: str) -> bool:
    """Heuristic check if an aircraft is military."""
    cs = (callsign or "").strip().upper()
    for prefix in _MILITARY_PREFIXES:
        if cs.startswith(prefix):
            return True
    # Check hex range
    try:
        h = int(icao24, 16)
        for lo, hi in _MIL_HEX_RANGES:
            if int(lo, 16) <= h <= int(hi, 16):
                return True
    except Exception:
        pass
    return False


async def flight_events(bbox: dict | None = None) -> tuple[list[MapEvent], FeedStatus]:
    """
    Fetch live flight data from OpenSky Network.
    bbox: optional {"lamin": ..., "lamax": ..., "lomin": ..., "lomax": ...}
    """
    global _flight_cache, _flight_cache_ts
    ts = _now()

    if _flight_cache_ts and (ts - _flight_cache_ts).total_seconds() < _FLIGHT_CACHE_TTL and _flight_cache:
        states = _flight_cache
    else:
        states = []
        try:
            params = {}
            if bbox:
                params.update(bbox)
            async with httpx.AsyncClient(timeout=25.0, headers={
                "User-Agent": "USRealView/1.0"
            }) as client:
                resp = await client.get(_OPENSKY_URL, params=params)
                if resp.status_code == 429:
                    logger.warning("OpenSky rate limited, using cache")
                    states = _flight_cache
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    states = data.get("states", []) or []
            if states:
                _flight_cache = states
                _flight_cache_ts = ts
        except Exception as exc:
            logger.warning("OpenSky fetch failed: %s", exc)
            states = _flight_cache

    events: list[MapEvent] = []
    mil_count = 0

    for s in states:
        if len(s) < 8:
            continue
        icao24 = s[0] or ""
        callsign = (s[1] or "").strip()
        country = s[2] or ""
        lon = s[5]
        lat = s[6]
        alt = s[7] or s[13]  # baro_altitude or geo_altitude
        velocity = s[9]
        heading = s[10]
        on_ground = s[8]

        if lat is None or lon is None:
            continue
        if on_ground:
            continue  # skip grounded aircraft

        is_mil = _is_military(callsign, icao24)
        if is_mil:
            mil_count += 1

        layer = "military_flights" if is_mil else "flights"
        display_name = callsign or icao24.upper()
        alt_ft = round(alt * 3.281) if alt else 0
        speed_kts = round(velocity * 1.944) if velocity else 0

        events.append(MapEvent(
            event_id=f"flight-{icao24}-{ts.isoformat()}",
            entity_id=f"flight-{icao24}",
            source="opensky",
            layer=layer,
            title=display_name,
            description=f"{country} | Alt {alt_ft:,} ft | {speed_kts} kts",
            status="airborne",
            timestamp=ts,
            lat=lat,
            lon=lon,
            altitude=alt or 0,
            speed=velocity,
            heading=heading,
            properties={
                "icao24": icao24,
                "callsign": callsign,
                "origin_country": country,
                "altitude_m": alt,
                "altitude_ft": alt_ft,
                "velocity_ms": velocity,
                "speed_kts": speed_kts,
                "heading": heading,
                "on_ground": on_ground,
                "is_military": is_mil,
                "layer_type": "military" if is_mil else "commercial",
            },
        ))

    logger.info(
        "Flights: %d total (%d military) from OpenSky",
        len(events), mil_count,
    )
    return events, FeedStatus(
        source="opensky",
        ok=bool(events),
        last_refresh=ts,
        message=f"{len(events)} flights ({mil_count} military) from OpenSky Network.",
    )


# ═══════════════════════════════════════════════════════════════════════
# SEISMIC ACTIVITY  (USGS Earthquake Hazards Program)
# ═══════════════════════════════════════════════════════════════════════
# USGS provides real-time earthquake data in GeoJSON format.

_USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"

_quake_cache: list[dict[str, Any]] = []
_quake_cache_ts: datetime | None = None
_QUAKE_CACHE_TTL = 120  # 2 min


async def seismic_events(timeframe: str = "day", min_magnitude: str = "2.5") -> tuple[list[MapEvent], FeedStatus]:
    """
    Fetch recent earthquakes from USGS.
    timeframe: "hour", "day", "week", "month"
    min_magnitude: "significant", "4.5", "2.5", "1.0", "all"
    """
    global _quake_cache, _quake_cache_ts
    ts = _now()

    if _quake_cache_ts and (ts - _quake_cache_ts).total_seconds() < _QUAKE_CACHE_TTL and _quake_cache:
        features = _quake_cache
    else:
        features = []
        url = f"{_USGS_URL}/{min_magnitude}_{timeframe}.geojson"
        try:
            async with httpx.AsyncClient(timeout=15.0, headers={
                "User-Agent": "USRealView/1.0"
            }) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                features = data.get("features", [])
            if features:
                _quake_cache = features
                _quake_cache_ts = ts
        except Exception as exc:
            logger.warning("USGS fetch failed: %s", exc)
            features = _quake_cache

    events: list[MapEvent] = []
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry", {})
        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            continue

        lon, lat = coords[0], coords[1]
        depth_km = coords[2] if len(coords) > 2 else 0
        mag = props.get("mag", 0) or 0
        place = props.get("place", "Unknown location")
        quake_time = props.get("time")
        quake_id = f.get("id", "")
        alert = props.get("alert", "")
        tsunami = props.get("tsunami", 0)
        felt = props.get("felt")
        sig = props.get("sig", 0)

        # Convert epoch ms to datetime
        if quake_time:
            try:
                q_ts = datetime.fromtimestamp(quake_time / 1000, tz=timezone.utc)
            except Exception:
                q_ts = ts
        else:
            q_ts = ts

        # Severity classification
        if mag >= 7:
            severity = "Major"
        elif mag >= 5:
            severity = "Moderate"
        elif mag >= 3:
            severity = "Minor"
        else:
            severity = "Light"

        events.append(MapEvent(
            event_id=f"quake-{quake_id}-{ts.isoformat()}",
            entity_id=f"quake-{quake_id}",
            source="usgs",
            layer="seismic",
            title=f"M{mag:.1f} — {place}",
            description=f"Depth {depth_km:.1f} km | {severity}",
            status=severity.lower(),
            timestamp=q_ts,
            lat=lat,
            lon=lon,
            properties={
                "magnitude": mag,
                "depth_km": depth_km,
                "place": place,
                "severity": severity,
                "alert": alert,
                "tsunami": tsunami,
                "felt": felt,
                "significance": sig,
                "url": props.get("url", ""),
                "type": props.get("type", "earthquake"),
            },
        ))

    logger.info("Seismic: %d earthquakes from USGS (%s, M%s+)", len(events), timeframe, min_magnitude)
    return events, FeedStatus(
        source="usgs",
        ok=bool(events),
        last_refresh=ts,
        message=f"{len(events)} earthquakes (M{min_magnitude}+, past {timeframe}) from USGS.",
    )
