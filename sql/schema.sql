CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS data_sources (
    source_id BIGSERIAL PRIMARY KEY,
    publisher TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    licence_url TEXT,
    UNIQUE (publisher, dataset_name, source_url)
);

CREATE TABLE IF NOT EXISTS geographies (
    geography_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    geography_type TEXT NOT NULL,
    parent_geography_id BIGINT REFERENCES geographies(geography_id),
    official_code TEXT,
    geometry GEOMETRY(MultiPolygon, 4326),
    UNIQUE (geography_type, official_code)
);

CREATE TABLE IF NOT EXISTS commodities (
    commodity_id BIGSERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    unit_system TEXT NOT NULL DEFAULT 'metric'
);

CREATE TABLE IF NOT EXISTS data_releases (
    release_id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES data_sources(source_id),
    release_date DATE NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_file_sha256 TEXT,
    revision_label TEXT,
    UNIQUE (source_id, release_date, revision_label)
);

CREATE TABLE IF NOT EXISTS crop_observations (
    observation_id BIGSERIAL PRIMARY KEY,
    release_id BIGINT NOT NULL REFERENCES data_releases(release_id),
    commodity_id BIGINT NOT NULL REFERENCES commodities(commodity_id),
    geography_id BIGINT NOT NULL REFERENCES geographies(geography_id),
    crop_year INTEGER NOT NULL CHECK (crop_year BETWEEN 1900 AND 2200),
    metric TEXT NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL,
    observation_status TEXT NOT NULL CHECK (
        observation_status IN ('official', 'estimate', 'forecast', 'modelled', 'synthetic')
    ),
    notes TEXT,
    UNIQUE (release_id, commodity_id, geography_id, crop_year, metric, unit)
);

CREATE INDEX IF NOT EXISTS crop_observations_lookup
    ON crop_observations (commodity_id, geography_id, crop_year, metric);

CREATE TABLE IF NOT EXISTS model_runs (
    model_run_id BIGSERIAL PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    as_of_date DATE NOT NULL,
    parameters JSONB NOT NULL,
    code_commit_sha TEXT
);

CREATE TABLE IF NOT EXISTS model_outputs (
    model_output_id BIGSERIAL PRIMARY KEY,
    model_run_id BIGINT NOT NULL REFERENCES model_runs(model_run_id),
    commodity_id BIGINT NOT NULL REFERENCES commodities(commodity_id),
    geography_id BIGINT NOT NULL REFERENCES geographies(geography_id),
    crop_year INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value NUMERIC NOT NULL,
    unit TEXT NOT NULL,
    confidence_lower NUMERIC,
    confidence_upper NUMERIC
);

