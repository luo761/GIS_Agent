CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP SCHEMA IF EXISTS gis_lab CASCADE;
CREATE SCHEMA gis_lab;

CREATE TABLE gis_lab.construction_areas (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    area_type text NOT NULL,
    note text,
    geom geometry(Polygon, 3857) NOT NULL
);

CREATE TABLE gis_lab.gas_pipelines (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    pipe_type text NOT NULL,
    pressure_level text NOT NULL,
    note text,
    geom geometry(LineString, 3857) NOT NULL
);

CREATE TABLE gis_lab.gas_devices (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    device_type text NOT NULL,
    status text NOT NULL,
    note text,
    geom geometry(Point, 3857) NOT NULL
);

CREATE TABLE gis_lab.water_pipelines (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    pipe_type text NOT NULL,
    note text,
    geom geometry(LineString, 3857) NOT NULL
);

CREATE TABLE gis_lab.demo_roads (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    road_type text NOT NULL,
    note text,
    geom geometry(LineString, 3857) NOT NULL
);

CREATE TABLE gis_lab.invalid_geometry_cases (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    expected_problem text NOT NULL,
    geom geometry(Geometry, 3857) NOT NULL
);

CREATE TABLE gis_lab.srid_input_examples (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    source_srid integer NOT NULL,
    target_srid integer NOT NULL,
    geom geometry(Geometry) NOT NULL
);

CREATE TABLE gis_lab.import_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type text NOT NULL,
    source_name text NOT NULL,
    original_crs text,
    target_srid integer NOT NULL DEFAULT 3857,
    imported_count integer NOT NULL DEFAULT 0,
    invalid_geometry_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX construction_areas_geom_gix ON gis_lab.construction_areas USING gist (geom);
CREATE INDEX gas_pipelines_geom_gix ON gis_lab.gas_pipelines USING gist (geom);
CREATE INDEX gas_devices_geom_gix ON gis_lab.gas_devices USING gist (geom);
CREATE INDEX water_pipelines_geom_gix ON gis_lab.water_pipelines USING gist (geom);
CREATE INDEX demo_roads_geom_gix ON gis_lab.demo_roads USING gist (geom);
CREATE INDEX invalid_geometry_cases_geom_gix ON gis_lab.invalid_geometry_cases USING gist (geom);
CREATE INDEX srid_input_examples_geom_gix ON gis_lab.srid_input_examples USING gist (geom);
