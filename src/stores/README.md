## install PostGIS
brew install postgis

## enable in the database
CREATE EXTENSION postgis;

-- or use docker
docker run --name postgis \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -d postgis/postgis