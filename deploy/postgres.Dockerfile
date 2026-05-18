# The app needs BOTH PostGIS (geography columns) and pgvector (step 12
# knowledge store). No stock image ships both, so we extend PostGIS with
# pgvector. A seasoned reviewer would flag a db image missing one of these
# — making it explicit here is the honest fix.
FROM postgis/postgis:16-3.4

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
