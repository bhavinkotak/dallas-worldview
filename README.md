# US RealView 🌐

A real-time 3D geospatial operations center for US cities — built with **CesiumJS**, **Next.js**, and **FastAPI**.

![US RealView](https://img.shields.io/badge/status-live-brightgreen) ![Python](https://img.shields.io/badge/python-3.12-blue) ![Next.js](https://img.shields.io/badge/next.js-14-black)

## Features

- **3D Globe** — Interactive CesiumJS viewer with OpenStreetMap tiles, OSM 3D buildings, atmospheric effects, and smooth fly-to navigation
- **Live Traffic Cameras** — 900+ live HLS video streams from [DriveTexas](https://drivetexas.org) across the DFW metro
- **Active Police Calls** — Real-time Dallas Police active calls from [Dallas Open Data](https://www.dallasopendata.com) with geocoding
- **Police Incidents** — Geocoded incident reports with coordinates from Dallas PD
- **Crime Layer (DFW-wide)** — Data from both Dallas Open Data and [Community Crime Map](https://communitycrimemap.com) (LexisNexis) covering all DFW cities including McKinney, Frisco, Plano
- **Weather** — Current conditions and active NWS alerts for multiple DFW locations
- **Timeline Replay** — Scrub back up to 3 hours to replay historical state
- **State & City Selection** — Auto-detected state from user geolocation, with easy city/area dropdown navigation
- **Layer Controls** — Toggle weather, traffic, incidents, crime, and cameras layers independently
- **Feed Health** — Live status dashboard showing data source health and record counts
- **Extensible City Config** — Backend-driven city configuration makes adding new areas easy

## Architecture

```
┌─────────────────────┐       ┌──────────────────────────────┐
│   Next.js Frontend  │◄─────►│   FastAPI Backend             │
│   (CesiumJS 3D)     │  REST │                                │
│   Port 3000         │       │   Port 8000                    │
└─────────────────────┘       └──────┬───────┬────────┬────────┘
                                     │       │        │
                        ┌────────────▼──┐ ┌──▼──────┐ │
                        │ DriveTexas    │ │  NWS    │ │
                        │ (934 cameras) │ │  API    │ │
                        └───────────────┘ └─────────┘ │
                        ┌────────────────┐ ┌──────────▼──────┐
                        │ Dallas Open    │ │ Community Crime  │
                        │ Data (Socrata) │ │ Map (LexisNexis) │
                        └────────────────┘ └─────────────────┘
```

## Quick Start

### Docker (recommended)

```bash
# Optional: Add a Cesium Ion token for 3D terrain & buildings
echo "NEXT_PUBLIC_CESIUM_ION_TOKEN=your_token_here" > .env

docker compose up --build
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

## Adding a New City

The city configuration is centralized in `backend/app/main.py` in the `CITY_CONFIG` dict. To add a new city:

1. Add a new city entry under the appropriate state in `CITY_CONFIG["states"]`
2. Include `places` (camera positions with bounding boxes) for the city
3. Add `data_sources` to indicate which feeds cover the city
4. If the city needs weather data, add its coordinates to `_WEATHER_LOCATIONS` in `providers.py`
5. The frontend automatically picks up new cities from the `/api/cities` endpoint

## Data Sources

| Layer | Source | Coverage |
|-------|--------|----------|
| Cameras | [DriveTexas / MapLarge](https://drivetexas.org) | 900+ live cameras across DFW metro |
| Weather | [NWS API](https://api.weather.gov) | Dallas, McKinney (expandable) |
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
