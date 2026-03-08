"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";

/* ───────── constants ───────── */
const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const CESIUM_VERSION = "1.126";
const CESIUM_CDN = `https://cesium.com/downloads/cesiumjs/releases/${CESIUM_VERSION}/Build/Cesium`;
const CESIUM_JS = `${CESIUM_CDN}/Cesium.js`;
const CESIUM_CSS = `${CESIUM_CDN}/Widgets/widgets.css`;

/* Cesium Ion token – supply via env var for terrain & 3D buildings.
   Without a valid token the viewer still works (OSM imagery + flat terrain). */
const CESIUM_ION_TOKEN = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN || "";

const DALLAS_CENTER = { lat: 32.7767, lon: -96.797 };

/* Each place has a bounding box (bbox) for filtering events to that area.
   bbox: [minLat, maxLat, minLon, maxLon] — roughly 0.03-0.06° radius for neighborhoods,
   wider for airports and distant cities. null = show all Dallas data. */
const DALLAS_PLACES = [
  { label: "All Dallas", lat: 32.7767, lon: -96.797, height: 25000, heading: 0, pitch: -60, bbox: null },
  { label: "Downtown Dallas", lat: 32.7767, lon: -96.797, height: 2200, heading: 15, pitch: -40, bbox: [32.755, 32.800, -96.820, -96.775] },
  { label: "Dallas City Hall", lat: 32.7763, lon: -96.7969, height: 1600, heading: 0, pitch: -35, bbox: [32.760, 32.790, -96.815, -96.780] },
  { label: "Deep Ellum", lat: 32.7843, lon: -96.781, height: 1600, heading: 45, pitch: -35, bbox: [32.770, 32.800, -96.800, -96.760] },
  { label: "Fair Park", lat: 32.7792, lon: -96.7597, height: 2200, heading: -30, pitch: -40, bbox: [32.760, 32.800, -96.780, -96.740] },
  { label: "Love Field", lat: 32.8471, lon: -96.8517, height: 4200, heading: 10, pitch: -50, bbox: [32.825, 32.870, -96.880, -96.825] },
  { label: "DFW Airport", lat: 32.8998, lon: -97.0403, height: 6500, heading: 0, pitch: -55, bbox: [32.860, 32.940, -97.100, -96.980] },
  { label: "Bishop Arts", lat: 32.7493, lon: -96.8278, height: 2200, heading: 20, pitch: -35, bbox: [32.730, 32.770, -96.850, -96.810] },
  { label: "White Rock Lake", lat: 32.8269, lon: -96.7246, height: 3600, heading: -15, pitch: -45, bbox: [32.800, 32.860, -96.760, -96.690] },
  { label: "Reunion Tower", lat: 32.7755, lon: -96.8088, height: 1400, heading: 30, pitch: -30, bbox: [32.760, 32.790, -96.825, -96.790] },
  { label: "Uptown", lat: 32.7990, lon: -96.8025, height: 2000, heading: -10, pitch: -35, bbox: [32.785, 32.815, -96.820, -96.785] },
  { label: "McKinney", lat: 33.1972, lon: -96.6397, height: 4500, heading: 0, pitch: -45, bbox: [33.150, 33.240, -96.700, -96.580] },
];

/* ───────── layer config ───────── */
const LAYER_META = {
  weather: { label: "Weather", icon: "\u{1F324}\uFE0F", color: "#38bdf8", height: 120, priority: 1 },
  traffic: { label: "Active Calls", icon: "\u{1F694}", color: "#f59e0b", height: 60, priority: 2 },
  incidents: { label: "Incidents", icon: "\u{1F534}", color: "#ef4444", height: 90, priority: 3 },
  crime: { label: "Crime", icon: "\u26A0\uFE0F", color: "#a855f7", height: 70, priority: 4 },
  cameras: { label: "Traffic Cameras", icon: "\u{1F4F7}", color: "#22d3ee", height: 100, priority: 5 },
};

/* ───────── Cesium loader ───────── */
function loadCesium() {
  if (typeof window === "undefined") return Promise.reject(new Error("Browser only"));
  if (window.Cesium) return Promise.resolve(window.Cesium);
  if (window.__cesiumPromise) return window.__cesiumPromise;

  window.__cesiumPromise = new Promise((resolve, reject) => {
    if (!document.querySelector(`link[href="${CESIUM_CSS}"]`)) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = CESIUM_CSS;
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.src = CESIUM_JS;
    script.async = true;
    script.onload = () => resolve(window.Cesium);
    script.onerror = () => reject(new Error("Failed to load CesiumJS"));
    document.body.appendChild(script);
  });
  return window.__cesiumPromise;
}

/* ───────── helpers ───────── */
function colorForLayer(Cesium, layer) {
  const hex = LAYER_META[layer]?.color || "#ffffff";
  return Cesium.Color.fromCssColorString(hex);
}

function heightForLayer(layer) {
  return LAYER_META[layer]?.height || 30;
}

function readCesiumProp(value, Cesium) {
  if (!value) return undefined;
  if (typeof value.getValue === "function") return value.getValue(Cesium.JulianDate.now());
  return value;
}

function buildEventUrl(mode, minutesAgo, layers, bbox) {
  const params = new URLSearchParams();
  if (layers) params.set("layers", layers);
  if (bbox) {
    params.set("min_lat", String(bbox[0]));
    params.set("max_lat", String(bbox[1]));
    params.set("min_lon", String(bbox[2]));
    params.set("max_lon", String(bbox[3]));
  }
  if (mode === "live" || minutesAgo === 0) return `${API_BASE}/api/events/current?${params}`;
  params.set("minutes_ago", String(minutesAgo));
  return `${API_BASE}/api/events/replay?${params}`;
}

function timeAgo(iso) {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

function countByLayer(events) {
  const counts = {};
  events.forEach((e) => (counts[e.layer] = (counts[e.layer] || 0) + 1));
  return counts;
}

/* ================================================================
   MAIN COMPONENT
   ================================================================ */
export default function DallasWorldView() {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const pickHandlerRef = useRef(null);
  const entityMapRef = useRef(new Map());
  const fetchTimerRef = useRef(null);
  const buildingsRef = useRef(null);

  const [layers, setLayers] = useState([]);
  const [selectedLayers, setSelectedLayers] = useState(["weather", "traffic", "incidents", "crime", "cameras"]);
  const [events, setEvents] = useState([]);
  const [feeds, setFeeds] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [mode, setMode] = useState("live");
  const [minutesAgo, setMinutesAgo] = useState(0);
  const [query, setQuery] = useState("");
  const [activeBbox, setActiveBbox] = useState(null); // [minLat, maxLat, minLon, maxLon] or null for all
  const [asOf, setAsOf] = useState(new Date().toISOString());
  const [status, setStatus] = useState("Initializing\u2026");
  const [panelOpen, setPanelOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [buildingsVisible, setBuildingsVisible] = useState(true);

  const selectedLayerStr = useMemo(() => selectedLayers.join(","), [selectedLayers]);

  const visibleEvents = useMemo(
    () => events.filter((e) => selectedLayers.includes(e.layer)),
    [events, selectedLayers]
  );

  const layerCounts = useMemo(() => countByLayer(visibleEvents), [visibleEvents]);

  /* -- bootstrap: fetch layers + feeds -- */
  useEffect(() => {
    let ignore = false;
    (async () => {
      try {
        const [lr, fr] = await Promise.all([
          fetch(`${API_BASE}/api/layers`),
          fetch(`${API_BASE}/api/feed-status`),
        ]);
        const lj = await lr.json();
        const fj = await fr.json();
        if (!ignore) {
          setLayers(lj.layers || []);
          setFeeds(fj.feeds || []);
        }
      } catch (err) {
        if (!ignore) setStatus(`Metadata error: ${err.message}`);
      }
    })();
    return () => { ignore = true; };
  }, []);

  /* -- init CesiumJS viewer -- */
  useEffect(() => {
    let disposed = false;

    async function init() {
      try {
        const Cesium = await loadCesium();
        if (disposed || !containerRef.current || viewerRef.current) return;

        /* Set Ion token only if provided */
        if (CESIUM_ION_TOKEN) {
          Cesium.Ion.defaultAccessToken = CESIUM_ION_TOKEN;
        }

        /* Base imagery – use OpenStreetMap (no token needed) */
        const osmImagery = new Cesium.OpenStreetMapImageryProvider({
          url: "https://tile.openstreetmap.org/",
        });

        const viewer = new Cesium.Viewer(containerRef.current, {
          animation: false,
          timeline: false,
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          infoBox: false,
          selectionIndicator: false,
          fullscreenButton: false,
          shouldAnimate: true,
          requestRenderMode: false,
          baseLayer: new Cesium.ImageryLayer(osmImagery),
        });

        /* Scene settings */
        const scene = viewer.scene;
        scene.backgroundColor = Cesium.Color.fromCssColorString("#070d1a");
        scene.globe.baseColor = Cesium.Color.fromCssColorString("#1e293b");
        scene.globe.showGroundAtmosphere = true;
        scene.globe.enableLighting = false;
        scene.globe.depthTestAgainstTerrain = false;
        scene.skyAtmosphere.show = true;
        scene.fog.enabled = true;
        scene.fog.density = 0.0003;
        scene.fog.minimumBrightness = 0.03;
        scene.screenSpaceCameraController.enableCollisionDetection = true;
        scene.highDynamicRange = false;
        scene.postProcessStages.fxaa.enabled = true;

        /* If we have a valid Ion token, try to add world terrain + 3D buildings */
        if (CESIUM_ION_TOKEN) {
          try {
            const terrain = await Cesium.CesiumTerrainProvider.fromIonAssetId(1);
            viewer.terrainProvider = terrain;
            scene.globe.depthTestAgainstTerrain = true;
          } catch (err) {
            console.warn("Ion terrain unavailable:", err.message);
          }

          try {
            const buildings = await Cesium.createOsmBuildingsAsync();
            buildings.style = new Cesium.Cesium3DTileStyle({
              color: {
                conditions: [
                  ["${feature['cesium#estimatedHeight']} >= 100", "color('#60a5fa', 0.65)"],
                  ["${feature['cesium#estimatedHeight']} >= 50", "color('#3b82f6', 0.55)"],
                  ["true", "color('#2563eb', 0.42)"],
                ],
              },
              show: true,
            });
            scene.primitives.add(buildings);
            buildingsRef.current = buildings;
          } catch (err) {
            console.warn("OSM Buildings unavailable:", err.message);
          }
        }

        /* Custom data source for event markers */
        const eventSource = new Cesium.CustomDataSource("events");
        eventSource.clustering.enabled = true;
        eventSource.clustering.pixelRange = 45;
        eventSource.clustering.minimumClusterSize = 4;
        eventSource.clustering.clusterEvent.addEventListener((clustered, cluster) => {
          cluster.label.show = true;
          cluster.label.text = String(clustered.length);
          cluster.label.font = "600 13px Inter, sans-serif";
          cluster.label.fillColor = Cesium.Color.WHITE;
          cluster.label.outlineColor = Cesium.Color.BLACK;
          cluster.label.outlineWidth = 3;
          cluster.label.style = Cesium.LabelStyle.FILL_AND_OUTLINE;
          cluster.label.showBackground = true;
          cluster.label.backgroundColor = Cesium.Color.fromCssColorString("#0f172a").withAlpha(0.9);
          cluster.label.backgroundPadding = new Cesium.Cartesian2(8, 5);
          cluster.billboard.show = false;
          cluster.point.show = true;
          cluster.point.pixelSize = Math.min(40, 16 + clustered.length * 0.4);
          cluster.point.color = Cesium.Color.fromCssColorString("#38bdf8").withAlpha(0.8);
          cluster.point.outlineColor = Cesium.Color.WHITE.withAlpha(0.6);
          cluster.point.outlineWidth = 2;
        });
        viewer.dataSources.add(eventSource);

        /* Fly to Dallas */
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(DALLAS_CENTER.lon, DALLAS_CENTER.lat, 3500),
          orientation: {
            heading: Cesium.Math.toRadians(15),
            pitch: Cesium.Math.toRadians(-42),
            roll: 0,
          },
          duration: 2.5,
        });

        /* Click handler */
        const handler = new Cesium.ScreenSpaceEventHandler(scene.canvas);
        handler.setInputAction((click) => {
          const picked = scene.pick(click.position);
          if (!picked || !picked.id || !picked.id.properties) return;
          const p = picked.id.properties;
          setSelectedEvent({
            event_id: readCesiumProp(p.event_id, Cesium),
            entity_id: readCesiumProp(p.entity_id, Cesium),
            title: readCesiumProp(p.title, Cesium),
            description: readCesiumProp(p.description, Cesium),
            layer: readCesiumProp(p.layer, Cesium),
            source: readCesiumProp(p.source, Cesium),
            status: readCesiumProp(p.status, Cesium),
            lat: readCesiumProp(p.lat, Cesium),
            lon: readCesiumProp(p.lon, Cesium),
            timestamp: readCesiumProp(p.timestamp, Cesium),
            properties: readCesiumProp(p.properties, Cesium),
          });
          setInspectorOpen(true);
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        viewerRef.current = viewer;
        eventSourceRef.current = eventSource;
        pickHandlerRef.current = handler;
        setStatus("Ready");
      } catch (err) {
        setStatus(`Init failed: ${err.message}`);
      }
    }

    init();
    return () => {
      disposed = true;
      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);
      if (pickHandlerRef.current) pickHandlerRef.current.destroy();
      if (viewerRef.current) viewerRef.current.destroy();
      viewerRef.current = null;
      eventSourceRef.current = null;
      pickHandlerRef.current = null;
      entityMapRef.current = new Map();
    };
  }, []);

  /* -- poll events -- */
  useEffect(() => {
    let ignore = false;

    async function refresh() {
      try {
        const url = buildEventUrl(mode, minutesAgo, selectedLayerStr, activeBbox);
        const [er, fr] = await Promise.all([
          fetch(url, { cache: "no-store" }),
          fetch(`${API_BASE}/api/feed-status`, { cache: "no-store" }),
        ]);
        const ej = await er.json();
        const fj = await fr.json();
        if (!ignore) {
          setEvents(ej.events || []);
          setAsOf(ej.as_of || new Date().toISOString());
          setFeeds(fj.feeds || []);
          const area = activeBbox ? " (area)" : "";
          setStatus(`${ej.count || 0} events${area}`);
        }
      } catch (err) {
        if (!ignore) setStatus(`Refresh error: ${err.message}`);
      }
    }

    if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);
    fetchTimerRef.current = setTimeout(refresh, 150);
    const iv = setInterval(refresh, mode === "live" && minutesAgo === 0 ? 15000 : 30000);
    return () => { ignore = true; clearTimeout(fetchTimerRef.current); clearInterval(iv); };
  }, [mode, minutesAgo, selectedLayerStr, activeBbox]);

  /* -- sync entities on map -- */
  useEffect(() => {
    const Cesium = window.Cesium;
    if (!Cesium || !eventSourceRef.current) return;

    const ds = eventSourceRef.current;
    const map = entityMapRef.current;
    const live = new Set();

    visibleEvents.forEach((ev) => {
      live.add(ev.entity_id);
      const c = colorForLayer(Cesium, ev.layer);
      const alt = heightForLayer(ev.layer);
      const isCamera = ev.layer === "cameras";
      let ent = map.get(ev.entity_id);

      if (!ent) {
        ent = ds.entities.add({
          id: ev.entity_id,
          position: Cesium.Cartesian3.fromDegrees(ev.lon, ev.lat, alt / 2),
          point: {
            pixelSize: isCamera ? 12 : ev.layer === "weather" ? 14 : 10,
            color: c,
            outlineColor: isCamera ? Cesium.Color.WHITE.withAlpha(0.9) : Cesium.Color.BLACK.withAlpha(0.7),
            outlineWidth: isCamera ? 2.5 : 1.5,
            scaleByDistance: new Cesium.NearFarScalar(1500, 1.3, 150000, 0.5),
            translucencyByDistance: new Cesium.NearFarScalar(1500, 1.0, 180000, 0.1),
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 300000),
            heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
          },
          cylinder: isCamera ? undefined : {
            length: alt,
            topRadius: 35,
            bottomRadius: 35,
            material: c.withAlpha(0.5),
            outline: true,
            outlineColor: c.withAlpha(0.85),
            outlineWidth: 1,
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 25000),
          },
          label: {
            text: isCamera
              ? "\uD83D\uDCF7 " + ev.title
              : ev.title && ev.title.length > 42 ? ev.title.slice(0, 40) + "\u2026" : ev.title,
            font: isCamera ? "600 12px Inter, sans-serif" : "600 11px Inter, sans-serif",
            scale: 1.0,
            show: true,
            pixelOffset: new Cesium.Cartesian2(0, -20),
            fillColor: isCamera ? Cesium.Color.fromCssColorString("#22d3ee") : Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 3,
            horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, isCamera ? 20000 : 15000),
            showBackground: true,
            backgroundColor: Cesium.Color.fromCssColorString("#0f172a").withAlpha(0.75),
            backgroundPadding: new Cesium.Cartesian2(6, 4),
          },
          properties: ev,
        });
        map.set(ev.entity_id, ent);
      } else {
        ent.position = Cesium.Cartesian3.fromDegrees(ev.lon, ev.lat, alt / 2);
        ent.properties = ev;
        if (ent.point) ent.point.color = c;
        if (ent.cylinder) {
          ent.cylinder.material = c.withAlpha(0.5);
          ent.cylinder.outlineColor = c.withAlpha(0.85);
        }
        if (ent.label) {
          ent.label.text = ev.title && ev.title.length > 42 ? ev.title.slice(0, 40) + "\u2026" : ev.title;
        }
      }
    });

    for (const [id, e] of map.entries()) {
      if (!live.has(id)) { ds.entities.remove(e); map.delete(id); }
    }

    if (viewerRef.current) viewerRef.current.scene.requestRender();
  }, [visibleEvents]);

  /* -- buildings toggle -- */
  useEffect(() => {
    if (buildingsRef.current) buildingsRef.current.show = buildingsVisible;
    if (viewerRef.current) viewerRef.current.scene.requestRender();
  }, [buildingsVisible]);

  /* -- actions -- */
  const toggleLayer = useCallback((lid) => {
    setSelectedLayers((cur) =>
      cur.includes(lid) ? cur.filter((l) => l !== lid) : [...cur, lid]
    );
  }, []);

  const flyToPreset = useCallback((placeLabel) => {
    const Cesium = window.Cesium;
    const viewer = viewerRef.current;
    if (!Cesium || !viewer) return;
    const target = placeLabel || query;
    const p = DALLAS_PLACES.find((pl) => pl.label === target) || DALLAS_PLACES[0];
    setQuery(p.label);
    setActiveBbox(p.bbox || null); // update bbox filter → triggers API re-fetch
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(p.lon, p.lat, p.height),
      orientation: {
        heading: Cesium.Math.toRadians(p.heading || 15),
        pitch: Cesium.Math.toRadians(p.pitch || -40),
        roll: 0,
      },
      duration: 1.8,
    });
  }, [query]);

  const flyToEvent = useCallback((ev) => {
    const Cesium = window.Cesium;
    const viewer = viewerRef.current;
    if (!Cesium || !viewer) return;
    setSelectedEvent(ev);
    setInspectorOpen(true);
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(ev.lon, ev.lat, 1200),
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-35),
        roll: 0,
      },
      duration: 1.2,
    });
  }, []);

  const totalHealthy = feeds.filter((f) => f.ok).length;
  const layerList = layers.length ? layers : Object.entries(LAYER_META).map(([id, m]) => ({ id, label: m.label, count: 0 }));

  /* ================================================================
     JSX
     ================================================================ */
  return (
    <div className="app-shell">
      {/* -- 3D Map -- */}
      <div ref={containerRef} className="map-host" />

      {/* -- Top Bar -- */}
      <header className="topbar">
        <div className="brand">
          <div className="brand-icon">{"\u25C6"}</div>
          <div>
            <h1>Dallas WorldView</h1>
            <span className="brand-sub">Real-time 3D City Operations</span>
          </div>
        </div>

        <nav className="top-controls">
          <div className="search-group">
            <select
              value={query}
              onChange={(e) => {
                const val = e.target.value;
                setQuery(val);
                if (val) {
                  flyToPreset(val);
                } else {
                  // Reset to show all Dallas data
                  setActiveBbox(null);
                }
              }}
              className="search-input"
            >
              <option value="">All Dallas (no filter)</option>
              {DALLAS_PLACES.map((p) => (
                <option key={p.label} value={p.label}>{p.label}</option>
              ))}
            </select>
            <button onClick={() => flyToPreset()} className="btn btn-primary" title="Fly">{"\u2708"}</button>
          </div>

          <div className="btn-group">
            <button
              className={`btn ${mode === "live" && minutesAgo === 0 ? "btn-live" : "btn-ghost"}`}
              onClick={() => { setMode("live"); setMinutesAgo(0); }}
            >
              <span className="live-dot" /> Live
            </button>
            <button
              className={`btn ${buildingsVisible ? "btn-active" : "btn-ghost"}`}
              onClick={() => setBuildingsVisible(!buildingsVisible)}
              title="Toggle 3D buildings"
            >
              {"\uD83C\uDFD9\uFE0F"}
            </button>
          </div>

          <div className="status-pill">
            <span className={`status-dot ${status === "Ready" || status.includes("events") ? "ok" : ""}`} />
            {status}
          </div>
        </nav>
      </header>

      {/* -- Left Panel Toggle -- */}
      <button
        className="panel-toggle left-toggle"
        onClick={() => setPanelOpen(!panelOpen)}
        title={panelOpen ? "Collapse" : "Expand"}
      >
        {panelOpen ? "\u25C2" : "\u25B8"}
      </button>

      {/* -- Left Panel -- */}
      <aside className={`side-panel ${panelOpen ? "open" : "closed"}`}>
        {/* KPI Row */}
        <div className="kpi-row">
          <div className="kpi">
            <span className="kpi-value">{visibleEvents.length}</span>
            <span className="kpi-label">Entities</span>
          </div>
          <div className="kpi">
            <span className="kpi-value">{totalHealthy}/{feeds.length || "\u2013"}</span>
            <span className="kpi-label">Feeds OK</span>
          </div>
        </div>

        {/* Layer toggles */}
        <div className="section-header">
          <h2>Layers</h2>
        </div>
        <div className="layer-list">
          {layerList.map((l) => {
            const meta = LAYER_META[l.id] || {};
            const active = selectedLayers.includes(l.id);
            return (
              <button
                key={l.id}
                className={`layer-chip ${active ? "active" : ""}`}
                style={{ "--layer-color": meta.color || "#7dd3fc" }}
                onClick={() => toggleLayer(l.id)}
              >
                <span className="layer-dot" />
                <span className="layer-chip-label">{meta.icon} {meta.label || l.label}</span>
                <span className="layer-chip-count">{layerCounts[l.id] || 0}</span>
              </button>
            );
          })}
        </div>

        {/* Feed health */}
        <div className="section-header">
          <h2>Feed Status</h2>
        </div>
        {feeds.length === 0 ? (
          <p className="empty">Waiting for backend\u2026</p>
        ) : (
          <div className="feed-list">
            {feeds.map((f) => (
              <div key={f.source} className={`feed-row ${f.ok ? "ok" : "err"}`}>
                <span className="feed-indicator" />
                <div className="feed-info">
                  <strong>{f.source}</strong>
                  <span className="feed-msg">{f.message || "Active"}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Event list */}
        <div className="section-header">
          <h2>Events <span className="header-count">{visibleEvents.length}</span></h2>
        </div>
        <div className="event-list">
          {visibleEvents.length === 0 ? (
            <p className="empty">No events matching filters.</p>
          ) : (
            visibleEvents.slice(0, 50).map((ev) => {
              const meta = LAYER_META[ev.layer] || {};
              return (
                <button
                  key={ev.event_id}
                  className={`event-card ${selectedEvent?.event_id === ev.event_id ? "selected" : ""}`}
                  onClick={() => flyToEvent(ev)}
                >
                  <div className="event-card-top">
                    <span className="event-badge" style={{ background: meta.color || "#555" }}>
                      {meta.icon}
                    </span>
                    <span className="event-title">{ev.title}</span>
                  </div>
                  <div className="event-card-bottom">
                    <span className="event-desc">{ev.description || "No detail"}</span>
                    <span className="event-time">{timeAgo(ev.timestamp)}</span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* -- Right Inspector Panel -- */}
      {inspectorOpen && selectedEvent && (
        <aside className="inspector">
          <div className="inspector-header">
            <h2>Inspector</h2>
            <button className="btn-close" onClick={() => setInspectorOpen(false)}>{"\u2715"}</button>
          </div>

          <div className="inspector-body">
            <div className="insp-badge-row">
              <span className="event-badge lg" style={{ background: LAYER_META[selectedEvent.layer]?.color || "#555" }}>
                {LAYER_META[selectedEvent.layer]?.icon}
              </span>
              <div>
                <h3 className="insp-title">{selectedEvent.title}</h3>
                <span className="insp-layer">{LAYER_META[selectedEvent.layer]?.label || selectedEvent.layer}</span>
              </div>
            </div>

            <p className="insp-desc">{selectedEvent.description || "No description available."}</p>

            <div className="insp-grid">
              <div className="insp-field">
                <span className="insp-key">Source</span>
                <span className="insp-val">{selectedEvent.source || "\u2013"}</span>
              </div>
              <div className="insp-field">
                <span className="insp-key">Status</span>
                <span className="insp-val">{selectedEvent.status || "\u2013"}</span>
              </div>
              <div className="insp-field">
                <span className="insp-key">Latitude</span>
                <span className="insp-val mono">{Number(selectedEvent.lat).toFixed(5)}</span>
              </div>
              <div className="insp-field">
                <span className="insp-key">Longitude</span>
                <span className="insp-val mono">{Number(selectedEvent.lon).toFixed(5)}</span>
              </div>
              <div className="insp-field full">
                <span className="insp-key">Timestamp</span>
                <span className="insp-val">{new Date(selectedEvent.timestamp).toLocaleString()}</span>
              </div>
            </div>

            <div className="section-header"><h2>Raw Properties</h2></div>
            <pre className="insp-json">{JSON.stringify(selectedEvent.properties || {}, null, 2)}</pre>
          </div>
        </aside>
      )}

      {/* -- Bottom Timeline -- */}
      <div className="timeline-bar">
        <div className="timeline-top">
          <div className="timeline-label">
            <span className="timeline-title">Timeline</span>
            <span className="timeline-asof">{new Date(asOf).toLocaleTimeString()}</span>
          </div>
          <span className={`timeline-mode ${mode === "live" && minutesAgo === 0 ? "live" : ""}`}>
            {mode === "live" && minutesAgo === 0 ? "\u25CF LIVE" : `${minutesAgo}m ago`}
          </span>
        </div>

        <input
          type="range"
          className="timeline-slider"
          min="0"
          max="180"
          step="5"
          value={minutesAgo}
          onChange={(e) => {
            const v = Number(e.target.value);
            setMinutesAgo(v);
            setMode(v === 0 ? "live" : "replay");
          }}
        />
        <div className="timeline-labels">
          <span>Now</span>
          <span>3h ago</span>
        </div>
      </div>
    </div>
  );
}
