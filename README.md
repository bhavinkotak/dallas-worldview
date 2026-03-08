# Dallas WorldView 🌐

A real-time 3D geospatial command center for Dallas, TX — built with **CesiumJS**, **Next.js**, and **FastAPI**.

![Dallas WorldView](https://img.shields.io/badge/status-live-brightgreen) ![Python](https://img.shields.io/badge/python-3.12-blue) ![Next.js](https://img.shields.io/badge/next.js-14-black)

## Features

- **3D Globe** — Interactive CesiumJS viewer with OpenStreetMap tiles, atmospheric effects, and smooth fly-to navigation
- **Live Traffic** — Real-time Dallas Police active calls from [Dallas Open Data](https://www.dallasopendata.com) with geocoding
- **Police Incidents** — Geocoded incident reports with coordinates from Dallas PD
- **Crime Layer** — Offense records mapped via beat centroids across Dallas divisions
- **Weather** — Current conditions and active NWS alerts for Dallas
- **Timeline Replay** — Scrub back up to 3 hours to replay historical state
- **Layer Controls** — Toggle weather, traffic, incidents, and crime layers independently
- **Feed Health** — Live status dashboard showing data source health and record counts

## Architecture

```
┌─────────────────────┐       ┌──────────────────────┐
│   Next.js Frontend  │◄─────►│   FastAPI Backend     │
│   (CesiumJS 3D)     │  REST │                        │
│   Port 3000         │       │   Port 8000            │
└─────────────────────┘       └──────┬───────┬─────────┘
                                     │       │
                              ┌──────▼──┐ ┌──▼────────────┐
                              │  NWS    │ │ Dallas Open    │
                              │  API    │ │ Data (Socrata) │
                              └─────────┘ └────────────────┘
```

## Quick Start

### Docker (recommended)

```bash
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

## Data Sources

| Layer | Source | Coordinates |
|-------|--------|-------------|
| Weather | [NWS API](https://api.weather.gov) | Dallas city center |
| Traffic | [Dallas Active Calls](https://www.dallasopendata.com/resource/tqs9-xfzb) | Geocoded via Nominatim + beat centroids |
| Incidents | [Dallas Police Incidents](https://www.dallasopendata.com/resource/qv6i-rri7) | Native `geocoded_column` |
| Crime | [Dallas Police Offenses](https://www.dallasopendata.com/resource/pumt-d92b) | Beat centroid mapping |

## Configuration

Environment variables (see `backend/.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_LIVE_FEEDS` | `true` | Enable/disable live data feeds |
| `REFRESH_INTERVAL_SECONDS` | `60` | How often to refresh data |
| `DALLAS_TRAFFIC_URL` | Socrata endpoint | Active police calls |
| `DALLAS_INCIDENTS_URL` | Socrata endpoint | Police incident reports |
| `DALLAS_CRIMES_URL` | Socrata endpoint | Crime offense records |

## Tech Stack

- **Frontend**: Next.js 14, React 18, CesiumJS 1.114
- **Backend**: FastAPI, Pydantic, httpx, uvicorn
- **Geocoding**: OpenStreetMap Nominatim (free, rate-limited)
- **Deployment**: Docker Compose

## License

MIT
