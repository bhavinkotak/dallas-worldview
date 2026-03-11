-- US RealView — Supabase Schema Migration
-- Run against: postgresql://postgres:***@db.pgimkhzeqqflzdqvpkwp.supabase.co:5432/postgres

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Current events (one row per entity, upserted on each refresh)
CREATE TABLE IF NOT EXISTS map_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL,
    entity_id       TEXT NOT NULL UNIQUE,
    source          TEXT NOT NULL,
    layer           TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    altitude        DOUBLE PRECISION NOT NULL DEFAULT 0,
    speed           DOUBLE PRECISION,
    heading         DOUBLE PRECISION,
    properties      JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Time-series history for replay
CREATE TABLE IF NOT EXISTS event_history (
    id              BIGSERIAL PRIMARY KEY,
    event_id        TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    source          TEXT NOT NULL,
    layer           TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    altitude        DOUBLE PRECISION NOT NULL DEFAULT 0,
    speed           DOUBLE PRECISION,
    heading         DOUBLE PRECISION,
    properties      JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Feed health tracking
CREATE TABLE IF NOT EXISTS feed_status (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL UNIQUE,
    ok              BOOLEAN NOT NULL DEFAULT true,
    last_refresh    TIMESTAMPTZ,
    message         TEXT NOT NULL DEFAULT '',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Layer definitions
CREATE TABLE IF NOT EXISTS layers (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    sort_order      INT NOT NULL DEFAULT 0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_me_layer ON map_events (layer);
CREATE INDEX IF NOT EXISTS idx_me_ts ON map_events (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_me_src ON map_events (source);
CREATE INDEX IF NOT EXISTS idx_eh_ts ON event_history (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_eh_layer ON event_history (layer);
CREATE INDEX IF NOT EXISTS idx_eh_eid ON event_history (entity_id);

-- Seed layers
INSERT INTO layers (id, label, sort_order) VALUES
    ('weather', 'Weather', 1),
    ('traffic', 'Traffic / Active Calls', 2),
    ('incidents', 'Incidents', 3),
    ('crime', 'Crime (DFW-wide)', 4),
    ('cameras', 'Traffic Cameras', 5),
    ('satellites', 'Satellites', 6),
    ('flights', 'Commercial Flights', 7),
    ('military_flights', 'Military Flights', 8),
    ('seismic', 'Seismic Activity', 9)
ON CONFLICT (id) DO NOTHING;

-- RLS
ALTER TABLE map_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE feed_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE layers ENABLE ROW LEVEL SECURITY;
