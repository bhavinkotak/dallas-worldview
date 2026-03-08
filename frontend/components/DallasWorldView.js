"use client";

import { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const CESIUM_JS = "https://unpkg.com/cesium@1.114.0/Build/Cesium/Cesium.js";
const CESIUM_CSS = "https://unpkg.com/cesium@1.114.0/Build/Cesium/Widgets/widgets.css";

const DALLAS_PLACES = [
  { label: "Downtown Dallas", lat: 32.7767, lon: -96.797, height: 2200 },
  { label: "Dallas City Hall", lat: 32.7763, lon: -96.7969, height: 1800 },
  { label: "Deep Ellum", lat: 32.7843, lon: -96.781, height: 1800 },
  { label: "Fair Park", lat: 32.7792, lon: -96.7597, height: 2200 },
  { label: "Love Field", lat: 32.8471, lon: -96.8517, height: 4200 },
  { label: "DFW Airport", lat: 32.8998, lon: -97.0403, height: 6500 },
  { label: "Bishop Arts", lat: 32.7493, lon: -96.8278, height: 2200 },
  { label: "White Rock Lake", lat: 32.8269, lon: -96.7246, height: 3600 },
];

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
    script.onerror = () => reject(new Error("Failed to load Cesium"));
    document.body.appendChild(script);
  });

  return window.__cesiumPromise;
}

function colorForLayer(Cesium, layer) {
  switch (layer) {
    case "weather":
      return Cesium.Color.fromCssColorString("#38bdf8");
    case "traffic":
      return Cesium.Color.fromCssColorString("#f59e0b");
    case "incidents":
      return Cesium.Color.fromCssColorString("#ef4444");
    case "crime":
      return Cesium.Color.fromCssColorString("#a855f7");
    default:
      return Cesium.Color.WHITE;
  }
}

function heightForLayer(layer) {
  switch (layer) {
    case "weather":
      return 80;
    case "traffic":
      return 30;
    case "incidents":
      return 50;
    case "crime":
      return 40;
    default:
      return 20;
  }
}

function readCesiumProperty(value, Cesium) {
  if (!value) return undefined;
  if (typeof value.getValue === "function") return value.getValue(Cesium.JulianDate.now());
  return value;
}

function buildEventUrl(mode, minutesAgo, layers) {
  const params = new URLSearchParams();
  if (layers) params.set("layers", layers);

  if (mode === "live" || minutesAgo === 0) {
    return `${API_BASE}/api/events/current?${params.toString()}`;
  }

  params.set("minutes_ago", String(minutesAgo));
  return `${API_BASE}/api/events/replay?${params.toString()}`;
}

export default function DallasWorldView() {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const eventSourceRef = useRef(null);
  const pickHandlerRef = useRef(null);
  const entityMapRef = useRef(new Map());
  const fetchTimerRef = useRef(null);

  const [layers, setLayers] = useState([]);
  const [selectedLayers, setSelectedLayers] = useState(["weather", "traffic", "incidents", "crime"]);
  const [events, setEvents] = useState([]);
  const [feeds, setFeeds] = useState([]);
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [mode, setMode] = useState("live");
  const [minutesAgo, setMinutesAgo] = useState(0);
  const [query, setQuery] = useState("Downtown Dallas");
  const [asOf, setAsOf] = useState(new Date().toISOString());
  const [status, setStatus] = useState("Loading map…");

  const selectedLayerString = useMemo(() => selectedLayers.join(","), [selectedLayers]);
  const visibleEvents = useMemo(
    () => events.filter((event) => selectedLayers.includes(event.layer)),
    [events, selectedLayers]
  );

  useEffect(() => {
    let ignore = false;

    async function bootstrap() {
      try {
        const [layerRes, feedRes] = await Promise.all([
          fetch(`${API_BASE}/api/layers`),
          fetch(`${API_BASE}/api/feed-status`),
        ]);
        const layerJson = await layerRes.json();
        const feedJson = await feedRes.json();
        if (!ignore) {
          setLayers(layerJson.layers || []);
          setFeeds(feedJson.feeds || []);
        }
      } catch (error) {
        if (!ignore) setStatus(`Metadata load failed: ${error.message}`);
      }
    }

    bootstrap();
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    async function initViewer() {
      try {
        const Cesium = await loadCesium();
        if (disposed || !containerRef.current || viewerRef.current) return;

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
          imageryProvider: new Cesium.OpenStreetMapImageryProvider({
            url: "https://tile.openstreetmap.org/",
          }),
        });

        viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#0f172a");
        viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#334155");
        viewer.scene.globe.showGroundAtmosphere = true;
        viewer.scene.globe.enableLighting = true;
        viewer.scene.globe.depthTestAgainstTerrain = false;
        viewer.scene.skyAtmosphere.show = true;
        viewer.scene.fog.enabled = true;

        const eventSource = new Cesium.CustomDataSource("events");
        eventSource.clustering.enabled = true;
        eventSource.clustering.pixelRange = 40;
        eventSource.clustering.minimumClusterSize = 4;
        eventSource.clustering.clusterEvent.addEventListener((clusteredEntities, cluster) => {
          cluster.label.show = true;
          cluster.label.text = String(clusteredEntities.length);
          cluster.label.fillColor = Cesium.Color.WHITE;
          cluster.label.outlineColor = Cesium.Color.BLACK;
          cluster.label.outlineWidth = 2;
          cluster.label.showBackground = true;
          cluster.label.backgroundColor = Cesium.Color.fromCssColorString("#0f172a").withAlpha(0.9);
          cluster.billboard.show = false;
          cluster.point.show = true;
          cluster.point.pixelSize = Math.min(36, 14 + clusteredEntities.length * 0.35);
          cluster.point.color = Cesium.Color.fromCssColorString("#38bdf8").withAlpha(0.85);
          cluster.point.outlineColor = Cesium.Color.WHITE;
          cluster.point.outlineWidth = 1;
        });
        viewer.dataSources.add(eventSource);

        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(-96.797, 32.7767, 3200),
          orientation: {
            heading: Cesium.Math.toRadians(15),
            pitch: Cesium.Math.toRadians(-55),
            roll: 0,
          },
          duration: 1.8,
        });

        const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler.setInputAction((click) => {
          const picked = viewer.scene.pick(click.position);
          if (!picked || !picked.id || !picked.id.properties) return;
          const props = picked.id.properties;
          setSelectedEvent({
            event_id: readCesiumProperty(props.event_id, Cesium),
            entity_id: readCesiumProperty(props.entity_id, Cesium),
            title: readCesiumProperty(props.title, Cesium),
            description: readCesiumProperty(props.description, Cesium),
            layer: readCesiumProperty(props.layer, Cesium),
            source: readCesiumProperty(props.source, Cesium),
            status: readCesiumProperty(props.status, Cesium),
            lat: readCesiumProperty(props.lat, Cesium),
            lon: readCesiumProperty(props.lon, Cesium),
            timestamp: readCesiumProperty(props.timestamp, Cesium),
            properties: readCesiumProperty(props.properties, Cesium),
          });
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        viewerRef.current = viewer;
        eventSourceRef.current = eventSource;
        pickHandlerRef.current = handler;
        setStatus("Dallas WorldView ready");
      } catch (error) {
        setStatus(`Viewer init failed: ${error.message}`);
      }
    }

    initViewer();

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

  useEffect(() => {
    let ignore = false;

    async function refreshEvents() {
      try {
        const url = buildEventUrl(mode, minutesAgo, selectedLayerString);

        const [eventsRes, feedRes] = await Promise.all([
          fetch(url, { cache: "no-store" }),
          fetch(`${API_BASE}/api/feed-status`, { cache: "no-store" }),
        ]);

        const eventsJson = await eventsRes.json();
        const feedJson = await feedRes.json();

        if (!ignore) {
          setEvents(eventsJson.events || []);
          setAsOf(eventsJson.as_of || new Date().toISOString());
          setFeeds(feedJson.feeds || []);
          setStatus(`${eventsJson.count || 0} entities visible`);
        }
      } catch (error) {
        if (!ignore) setStatus(`Data refresh failed: ${error.message}`);
      }
    }

    if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);
    fetchTimerRef.current = setTimeout(refreshEvents, 120);
    const timer = setInterval(refreshEvents, mode === "live" && minutesAgo === 0 ? 15000 : 30000);

    return () => {
      ignore = true;
      if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current);
      clearInterval(timer);
    };
  }, [mode, minutesAgo, selectedLayerString]);

  useEffect(() => {
    async function syncEntities() {
      const Cesium = window.Cesium;
      if (!Cesium || !eventSourceRef.current) return;

      const eventSource = eventSourceRef.current;
      const entityMap = entityMapRef.current;
      const incomingIds = new Set();

      visibleEvents.forEach((event) => {
        incomingIds.add(event.entity_id);
        const color = colorForLayer(Cesium, event.layer);
        const altitude = heightForLayer(event.layer);
        let entity = entityMap.get(event.entity_id);

        if (!entity) {
          entity = eventSource.entities.add({
            id: event.entity_id,
            position: Cesium.Cartesian3.fromDegrees(event.lon, event.lat, altitude / 2),
            point: {
              pixelSize: event.layer === "weather" ? 14 : 11,
              color,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 1,
              scaleByDistance: new Cesium.NearFarScalar(2000, 1.2, 120000, 0.55),
              translucencyByDistance: new Cesium.NearFarScalar(2000, 1.0, 160000, 0.15),
              distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 250000),
              heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
            },
            cylinder: {
              length: altitude,
              topRadius: 40,
              bottomRadius: 40,
              material: color.withAlpha(0.6),
              outline: true,
              outlineColor: color.withAlpha(0.9),
              outlineWidth: 1,
              distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 30000),
            },
            label: {
              text: event.title,
              scale: 0.45,
              show: true,
              pixelOffset: new Cesium.Cartesian2(0, -22),
              fillColor: color,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
              distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 18000),
            },
            properties: event,
          });
          entityMap.set(event.entity_id, entity);
        } else {
          entity.position = Cesium.Cartesian3.fromDegrees(event.lon, event.lat, altitude / 2);
          entity.properties = event;
          if (entity.point) entity.point.color = color;
          if (entity.cylinder) {
            entity.cylinder.material = color.withAlpha(0.6);
            entity.cylinder.outlineColor = color.withAlpha(0.9);
          }
          if (entity.label) {
            entity.label.text = event.title;
            entity.label.fillColor = color;
          }
        }
      });

      for (const [entityId, entity] of entityMap.entries()) {
        if (!incomingIds.has(entityId)) {
          eventSource.entities.remove(entity);
          entityMap.delete(entityId);
        }
      }

      if (viewerRef.current) viewerRef.current.scene.requestRender();
    }

    syncEntities();
  }, [visibleEvents]);

  function toggleLayer(layerId) {
    setSelectedLayers((current) => {
      if (current.includes(layerId)) return current.filter((item) => item !== layerId);
      return [...current, layerId];
    });
  }

  function flyToPreset() {
    const Cesium = window.Cesium;
    const viewer = viewerRef.current;
    if (!Cesium || !viewer) return;

    const preset =
      DALLAS_PLACES.find((place) => place.label.toLowerCase().includes(query.toLowerCase())) || DALLAS_PLACES[0];

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(preset.lon, preset.lat, preset.height),
      orientation: {
        heading: Cesium.Math.toRadians(10),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0,
      },
      duration: 1.6,
    });
  }

  const totalFeedsHealthy = feeds.filter((feed) => feed.ok).length;
  const layerFallback = [
    { id: "weather", label: "Weather", count: 0 },
    { id: "traffic", label: "Traffic / Active Calls", count: 0 },
    { id: "incidents", label: "Incidents", count: 0 },
    { id: "crime", label: "Crime", count: 0 },
  ];

  return (
    <div className="app-shell">
      <div ref={containerRef} className="map-host" />

      <div className="topbar">
        <div className="brand">
          <h1>Dallas WorldView</h1>
          <p>3D city operations view with live layers, crime overlays, replay, and Dallas presets.</p>
        </div>

        <div className="controls">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search Dallas preset"
            list="dallas-presets"
          />
          <datalist id="dallas-presets">
            {DALLAS_PLACES.map((place) => (
              <option key={place.label} value={place.label} />
            ))}
          </datalist>

          <button onClick={flyToPreset}>Fly to place</button>

          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="live">Live</option>
            <option value="replay">Replay</option>
          </select>

          <button
            onClick={() => {
              setMode("live");
              setMinutesAgo(0);
            }}
          >
            Go live
          </button>

          <span className="badge">{status}</span>
        </div>
      </div>

      <aside className="side-panel">
        <h2 className="section-title">Layer controls</h2>

        <div className="kpi-grid">
          <div className="kpi">
            <span className="muted">Entities</span>
            <strong>{visibleEvents.length}</strong>
          </div>
          <div className="kpi">
            <span className="muted">Healthy feeds</span>
            <strong>
              {totalFeedsHealthy}/{feeds.length || 1}
            </strong>
          </div>
        </div>

        {(layers.length ? layers : layerFallback).map((layer) => (
          <div key={layer.id} className="layer-item">
            <div className="row">
              <div>
                <div>{layer.label}</div>
                <div className="muted">{layer.count} current entities</div>
              </div>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={selectedLayers.includes(layer.id)}
                  onChange={() => toggleLayer(layer.id)}
                />
                <span className="small">Visible</span>
              </label>
            </div>
          </div>
        ))}

        <h2 className="section-title">Feed health</h2>
        {feeds.length === 0 ? (
          <div className="empty-state">Waiting for backend feed status.</div>
        ) : (
          feeds.map((feed) => (
            <div key={feed.source} className="feed-item">
              <div className="row">
                <strong>{feed.source}</strong>
                <span className="badge">{feed.ok ? "ok" : "degraded"}</span>
              </div>
              <div className="muted">{feed.message || "No message"}</div>
            </div>
          ))
        )}

        <h2 className="section-title">Visible entities</h2>
        {visibleEvents.length === 0 ? (
          <div className="empty-state">No entities for the selected filters.</div>
        ) : (
          visibleEvents.slice(0, 30).map((event) => (
            <div key={event.event_id} className="event-row" onClick={() => setSelectedEvent(event)}>
              <div className="row">
                <strong>{event.title}</strong>
                <span className="badge">{event.layer}</span>
              </div>
              <div className="muted">{event.description || "No description"}</div>
            </div>
          ))
        )}
      </aside>

      <aside className="inspector">
        <h2 className="section-title">Inspector</h2>
        {!selectedEvent ? (
          <div className="empty-state">Select a marker or list item to inspect layer details.</div>
        ) : (
          <>
            <div className="event-row">
              <div className="row">
                <strong>{selectedEvent.title}</strong>
                <span className="badge">{selectedEvent.layer}</span>
              </div>
              <p className="small">{selectedEvent.description || "No description"}</p>
              <div className="muted">Source: {selectedEvent.source}</div>
              <div className="muted">Status: {selectedEvent.status}</div>
              <div className="muted">Time: {String(selectedEvent.timestamp)}</div>
              <div className="muted">
                Lat/Lon: {Number(selectedEvent.lat).toFixed(4)}, {Number(selectedEvent.lon).toFixed(4)}
              </div>
            </div>

            <h2 className="section-title">Properties</h2>
            <div className="event-row small">
              <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {JSON.stringify(selectedEvent.properties || {}, null, 2)}
              </pre>
            </div>
          </>
        )}
      </aside>

      <div className="timeline">
        <div className="row" style={{ marginBottom: 10 }}>
          <div>
            <div className="section-title" style={{ margin: 0 }}>
              Timeline
            </div>
            <div className="muted">As of {new Date(asOf).toLocaleString()}</div>
          </div>
          <div className="badge">{mode === "live" && minutesAgo === 0 ? "Live now" : `${minutesAgo} min ago`}</div>
        </div>

        <input
          type="range"
          min="0"
          max="180"
          step="5"
          value={minutesAgo}
          onChange={(event) => {
            const value = Number(event.target.value);
            setMinutesAgo(value);
            setMode(value === 0 ? "live" : "replay");
          }}
        />

        <div className="row muted">
          <span>Now</span>
          <span>3 hours ago</span>
        </div>
      </div>
    </div>
  );
}
