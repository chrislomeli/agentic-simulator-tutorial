-- Runs once on first DB init (docker-entrypoint-initdb.d).
-- The DDL/seed (src/stores/.../ddl.sql, run by the data pipeline) assumes
-- these exist.
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
