# US RealView 🌐

A real-time 3D geospatial operations center combining satellite tracking, live flight data, seismic monitoring, CCTV feeds, and OSINT layers on an interactive globe — built with **CesiumJS**, **Next.js**, and **FastAPI**.

![US RealView](https://img.shields.io/badge/status-live-brightgreen) ![Python](https://img.shields.io/badge/python-3.12-blue) ![Next.js](https://img.shields.io/badge/next.js-14-black)

## Features

### 🌍 3D Globe & Visualization
- **Interactive CesiumJS Globe** — Full Earth model with OpenStreetMap tiles, OSM 3D buildings, atmospheric effects, and smooth fly-to navigation
- **Visual Effects Modes** — Switch between Normal, Night Vision, CRT, FLIR (thermal), and Bloom post-processing filters
- **Cinematic Camera** — Globe-to-city zoom animation on startup with precise POI centering

### 🛰️ Real-Time Satellite Tracking
- **CelesTrak Integration** — Live orbital data for space stations (ISS, Tiangong), bright visual satellites, and geostationary objects
- **Orbit Classification** — LEO, MEO, GEO orbit type identification with NORAD IDs
- **Orbital Parameters** — Inclination, eccentricity, mean motion, RAAN displayed in inspector

### ✈️ Live Flight Data
- **Commercial Flight Tracking** — Real-time aircraft positions from [OpenSky Network](https://opensky-network.org) with callsign, altitude, speed, and heading
- **Military Flight Detection** — Heuristic identification of military aircraft by callsign prefixes and ICAO24 hex ranges
- **Flight Inspector** — Detailed flight data including altitude (ft), speed (kts), heading, and origin country

### 🌋 Seismic Activity
- **USGS Earthquake Feed** — Real-time M2.5+ earthquakes from the USGS Earthquake Hazards Program
- **Magnitude-Scaled Markers** — Visual size scales with earthquake magnitude; pulsing ring overlays
- **Severity Classification** — Major/Moderate/Minor/Light with alert level and tsunami warnings

### 📹 Live CCTV & Traffic
- **Live Traffic Cameras** — 900+ live HLS video streams from [DriveTexas](https://drivetexas.org) across the DFW metro
- **Active Police Calls** — Real-time Dallas Police active calls from [Dallas Open Data](https://www.dallasopendata.com) with geocoding
- **Crime Layer (DFW-wide)** — Data from both Dallas Open Data and [Community Crime Map](https://communitycrimemap.com) (LexisNexis) covering all DFW cities

### 🎛️ Operations Center
- **Timeline Replay** — Scrub back up to 3 hours to replay historical events
- **State & City Selection** — Auto-detected state from user geolocation with dropdown navigation
- **Layer Controls** — Toggle satellites, flights, weather, traffic, incidents, crime, cameras, seismic layers independently
- **KPI Dashboard** — Real-time counts for events, feeds, flights, and satellites
- **Feed Health** — Live status dashboard showing data source health and record counts
- **Grouped Event List** — Events organized by layer type with collapsible sections

## Architecture

```
┌─────────────────────┐       ┌──────────────────────────────┐
│   Next.js Frontend  │◄─────►│   FastAPI Backend             │
│   (CesiumJS 3D)     │  REST │                                │
│   Port 3000         │       │   Port 8000                    │
└─────────────────────┘       └──┬────┬────┬───┬────┬────┬────┘
                                 │    │    │   │    │    │
                    ┌────────────▼┐ ┌─▼──┐ │ ┌▼────▼┐ ┌─▼──────────┐
                    │ DriveTexas  │ │NWS │ │ │OpenSky│ │ CelesTrak  │
                    │ (cameras)   │ │API │ │ │Network│ │ (sats)     │
                    └─────────────┘ └────┘ │ └───────┘ └────────────┘
                    ┌─────────────┐ ┌──────▼──────┐ ┌──────────────┐
                    │ Dallas Open │ │  Community   │ │  USGS        │
                    │ Data        │ │  Crime Map   │ │  Earthquakes │
                    └─────────────┘ └─────────────┘ └──────────────┘
```

## Quick Start

### Docker (recommended)

```bash
# Optional: Add a Cesium Ion token for 3D terrain & buildings
echo "NEXT_PUBLIC_CESIUM_ION_TOKEN=your_token_here" > .env

# Build and run (always use --no-cache after code changes)
docker compose build --no-cache
docker compose up
```

Then open [http://localhost:3000](http://localhost:3000).

### Local Development

**Backend:**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

## Adding a New City or State

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for a step-by-step guide.

**TL;DR**: Edit `CITY_CONF| Weather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weather.gov) | Aather | [NWS API](https://api.weathll configured cities (auto-derived) |
| Traffic | [Dallas Active Calls](https://www.dallasopendata.com/resource/tqs9-xfzb) | Dallas city limits |
| Incidents | [Dallas Police Incidents](https://www.dallasopendata.com/resource/qv6i-rri7) | Dallas city limits |
| Crime | [Dallas Open Data](https://www.dallasopendata.com/resource/pumt-d92b) + [Community Crime Map](https://communitycrimemap.com) | Dallas (Open Data) + all DFW cities (CCM) |

## Configuration

Environment variables (see `backend/.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_CESIUM_ION_TOKEN` | (empty) | Cesium Ion token for 3D terrain & buildings |
| `USE_LIVE_FEEDS` | `true` | Enable/disable live data feeds |
| `REFRESH_INTERVAL_SECONDS` | `60` | How often to refresh data |

## Tech Stack

- **Frontend**: Next.js 14, React 18, CesiumJS 1.126, hls.js 1.5.17
- **Backend**: FastAPI, Pydantic, httpx, uvicorn
- **Data**: Dallas Open Data (Socrata), Community Crime Map (LexisNexis), DriveTexas (MapLarge), NWS
- **Geocoding**: OpenStreetMap Nominatim (free, rate-limited)
- **Deployment**: Docker Compose

## License

MIT
