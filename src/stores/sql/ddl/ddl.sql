create table if not exists resources
(
    resource_id            integer not null
        constraint resources_pk
            primary key,
    source_file            varchar(30),
    agency                 varchar(60),
    cal_file_unit          varchar(30),
    unit_id                varchar(30),
    resource_category      varchar(30),
    resource_type          varchar(60),
    nwcg_type              varchar(30),
    year                   varchar(10),
    male                   varchar(30),
    model                  varchar(10),
    capacity_water_gal     integer,
    pump_gpm               integer,
    personnel              integer,
    battalion              varchar(30),
    station_number         varchar(10),
    station_name           varchar(60),
    station_address        varchar(60),
    mutual_aid_agreement   varchar(30),
    lpf_interface_priority varchar(30),
    seasonal               varchar(10),
    lat                    double precision,
    long                   double precision,
    notes                  text,
    location               geography(Point, 4326)
);

create table if not exists spatial_ref_sys
(
    srid      integer not null
        primary key
        constraint spatial_ref_sys_srid_check
            check ((srid > 0) AND (srid <= 998999)),
    auth_name varchar(256),
    auth_srid integer,
    srtext    varchar(2048),
    proj4text varchar(2048)
);

create table if not exists terrain
(
    grid_column         integer,
    grid_row            integer,
    layer               integer,
    cell_key            varchar(30),
    terrain             varchar(30),
    vegetation          double precision,
    fuel_moisture       double precision,
    slope               real,
    cell_size_ft        integer,
    time_step_min       real,
    burn_duration_ticks integer,
    lat                 double precision,
    long                double precision,
    location            geography(Point, 4326),
    region              varchar(60),
    constraint terrain_pk
        unique (grid_column, grid_row)
);

create table if not exists sensors
(
    grid_row    integer,
    grid_column integer,
    elevation   integer,
    sensor_id   varchar(60) not null
        constraint sensors_pk
            primary key,
    sensor_type varchar(30),
    cluster_id  varchar(60),
    noise_std   double precision,
    lat         double precision,
    long        double precision,
    location    geography(Point, 4326),
    region      varchar(60)
);

create table if not exists wildfire_activity
(
    imsr_date            date,
    gacc                 varchar(30),
    gacc_priority        integer,
    fire_priority        integer,
    new_large_fire_mark  varchar(10) not null,
    fire_name            varchar(120),
    unit                 varchar(30),
    fire_size_acres      integer,
    fire_size_change     varchar(20),
    percent_containment  integer,
    contained_completed  varchar(30),
    est_containment_date varchar(30),
    personnel            integer,
    personnel_change     varchar(30),
    crews                integer,
    engines              integer,
    helicopters          integer,
    structures_lost      integer,
    cost_to_date         varchar(20),
    origin_ownership     varchar(60)
);

-- Indexes for wildfire resource estimation queries
-- Range queries on fire_size_acres sorted by date need this composite index
create index if not exists idx_wildfire_size_date
    on wildfire_activity (fire_size_acres, imsr_date desc);

-- Case-insensitive fire name lookups
create index if not exists idx_wildfire_name
    on wildfire_activity using gin (fire_name gin_trgm_ops);

