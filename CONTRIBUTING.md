# Contributing to US RealView

Thanks for your interest in making US RealView better! This guide covers the most common contribution: **adding a new city or state**.

---

## Adding a New City

All city/area configuration lives in **one place**: `backend/app/main.py` → `CITY_CONFIG`.

### Step 1 — Find the right state

Open `backend/app/main.py` and locate the `CITY_CONFIG` dictionary. Each state has a `code`, `name`, and a list of `cities`.

If your state already exists, skip to Step 2. Otherwise, add a new state block:

```python
{
    "code": "CA",
    "name": "California",
    "cities": [
        # cities go here
    ],
}
```

### Step 2 — Add the city entry

Under the state's `cities` list, add a new city object:

```python
{
    "id": "austin",                         # unique slug
    "name": "Austin",                       # display name
    "lat": 30.2672,                         # city center latitude
    "lon": -97.7431,                        # city center longitude
    "data_sources": ["ccm", "nws", "drivetexas"],  # see below
    "places": [
        # at least one "overview" place
        {
            "label": "Austin",
            "lat": 30.2672,
            "lon": -97.7431,
            "height": 4500,
            "heading": 0,
            "pitch": -45,
            "bbox": [30.200, 30.340, -97.830, -97.660],
        },
        # optional: zoom-in presets
        {
            "label": "Austin Downtown",
            "lat": 30.2672,
            "lon": -97.7431,
            "height": 2000,
            "heading": 10,
            "pitch": -35,
            "bbox": [30.255, 30.280, -97.760, -97.730],
        },
    ],
},
```

### Step 3 — Understand `data_sources`

The `data_sources` list tells the system which feeds cover this city. Current options:

| Source ID | Description | Coverage |
|-----------|-------------|----------|
| `dallas-opendata` | Dallas Police calls, incidents, and crime from Socrata | Dallas city limits only |
| `ccm` | Community Crime Map (LexisNexis) — crime data | Any city with a participating agency |
| `nws` | National Weather Service alerts + current conditions | Anywhere in the US (auto-geocoded) |
| `drivetexas` | Live traffic cameras via MapLarge | Texas statewide |

> **Weather is automatic!** When you add a city with `lat`/`lon`, the backend automatically queries NWS for that location. No manual coordinate setup needed.

### Step 4 — Configure `places` (camera positions)

Each place defines a 3D camera viewpoint:

| Field | Type | Description |
|-------|------|-------------|
| `label` | string | Dropdown label (e.g., "Downtown Austin") |
| `lat` | float | Camera target latitude |
| `lon` | float | Camera target longitude |
| `height` | int | Camera altitude in meters (1500–25000) |
| `heading` | int | Horizontal rotation in degrees (0 = north) |
| `pitch` | int | Vertical tilt in degrees (-90 = straight down, -35 = angled) |
| `bbox` | list or null | `[min_lat, max_lat, min_lon, max_lon]` for event filtering, or `null` for no filter |

**Tips for choosing values:**
- **Overview**: `height: 4500–6000`, `pitch: -45 to -55` — shows the whole city
- **Neighborhood**: `height: 1500–2500`, `pitch: -30 to -40` — focused view
- **Landmark**: `height: 1000–1600`, `pitch: -25 to -35` — close-up

Use [Google Maps](https://www.google.com/maps) to find lat/lon for locations.

### Step 5 — Test locally

```bash
cd us-realview

# Rebuild with no cache to pick up changes
docker compose build --no-cache
docker compose up

# Verify in browser at http://localhost:3000
# - New state should appear in the state dropdown
# - New city places should appear in the area dropdown
# - Weather should auto-fetch for the new city

# Verify API
curl http://localhost:8000/api/cities | python -m json.tool
```

### Step 6 — Submit a PR

1. Fork the repo
2. Create a branch: `git checkout -b add-city-austin`
3. Make your changes to `backend/app/main.py`
4. Test with Docker (see above)
5. Commit: `git commit -m "feat: add Austin, TX"`
6. Push and open a Pull Request

---

## Adding a New Data Source

If you want to integrate a completely new data provider (beyond the built-in ones):

1. **Add a provider function** in `backend/app/providers.py` that returns `(list[dict], dict)` — events list and feed status
2. **Call it** from `refresh_once()` in `backend/app/main.py`
3. **Add a layer** entry to `LAYER_META` in `frontend/components/USRealView.js`
4. **Add inspector panel** for the new layer type in the JSX

---

## Code Style

- **Python**: Follow PEP 8. Use type hints.
- **JavaScript**: Use `const`/`let`, functional React patterns, no semicolons are okay (we use them).
- **Commits**: Use [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `docs:`, etc.

---

## Docker Tips

- **Always use `--no-cache`** when rebuilding after code changes:
  ```bash
  docker compose build --no-cache
  ```
  BuildKit may cache layers even when source files change.

- **Check logs** for errors:
  ```bash
  docker compose logs -f backend
  docker compose logs -f frontend
  ```

---

## Questions?

Open an issue on GitHub — we're happy to help!
