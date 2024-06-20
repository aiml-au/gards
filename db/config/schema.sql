CREATE EXTENSION IF NOT EXISTS "postgis";

CREATE SCHEMA app;

CREATE TABLE app.raster
(
    id     VARCHAR(36) PRIMARY KEY NOT NULL,
    name   VARCHAR(255)            NOT NULL,
    file   VARCHAR(255)            NOT NULL,
    folder VARCHAR(255)            NOT NULL,
    folder_id VARCHAR(36)          NOT NULL,
    created TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP, -- e.g: 2024-01-25 15:12:11
    questionset_id VARCHAR(36),
    UNIQUE (file)
);

CREATE TABLE app.raster_valid
(
    raster    VARCHAR(36) PRIMARY KEY REFERENCES app.raster (id) ON DELETE CASCADE,
    hash      BIGINT      NOT NULL,
    size      INTEGER     NOT NULL,
    width     INTEGER     NOT NULL,
    height    INTEGER     NOT NULL,
    bands     INTEGER     NOT NULL,
    crs       VARCHAR(50),
    transform DOUBLE PRECISION[],
    latlon    DOUBLE PRECISION[],
    bounds    GEOGRAPHY(POLYGON, 4326),
    grid      TEXT               NOT NULL,
    effectset varchar[]          NOT NULL,
    area      DOUBLE PRECISION,
    num_tiles_x     INTEGER              NOT NULL,
    num_tiles_y     INTEGER              NOT NULL
);


CREATE INDEX bounds ON app.raster_valid USING GIST (bounds);

CREATE TABLE app.raster_invalid
(
    raster VARCHAR(36) PRIMARY KEY REFERENCES app.raster (id) ON DELETE CASCADE,
    reason VARCHAR(255) NOT NULL
);

CREATE TABLE app.raster_tiled
(
    raster VARCHAR(36) PRIMARY KEY REFERENCES app.raster_valid (raster) ON DELETE CASCADE,
    file    VARCHAR(255) NOT NULL
);

CREATE TABLE app.chunk
(
    id     VARCHAR(36) PRIMARY KEY NOT NULL,
    raster VARCHAR(36) REFERENCES app.raster_valid (raster) ON DELETE CASCADE,
    x      INTEGER                 NOT NULL,
    y      INTEGER                 NOT NULL,
    UNIQUE (raster, x, y)
);

CREATE TABLE app.chunk_result
(
    chunk VARCHAR(36)  NOT NULL REFERENCES app.chunk (id) ON DELETE CASCADE,
    label VARCHAR(255) NOT NULL,
    file   VARCHAR(255) NOT NULL,
    PRIMARY KEY (chunk, label)
);

CREATE TABLE app.chunk_failed
(
    chunk  VARCHAR(36) PRIMARY KEY NOT NULL REFERENCES app.chunk (id) ON DELETE CASCADE,
    reason VARCHAR(255)            NOT NULL
);

CREATE TABLE app.result
(
    id     VARCHAR(36) PRIMARY KEY NOT NULL,
    raster VARCHAR(36) REFERENCES app.raster_valid (raster) ON DELETE CASCADE,
    label  VARCHAR(255)            NOT NULL,
    file    VARCHAR(255)            NOT NULL,
    UNIQUE (raster, label)
);

CREATE TABLE app.result_tiled
(
    result VARCHAR(36) PRIMARY KEY REFERENCES app.result (id) ON DELETE CASCADE,
    file    VARCHAR(255) NOT NULL
);

CREATE TABLE app.questionsets
(
    id     VARCHAR(36) PRIMARY KEY NOT NULL,
    name   VARCHAR(255)            NOT NULL,
    effectset     varchar[]          NOT NULL,
    data   jsonb           NOT NULL
);

CREATE ROLE web LOGIN PASSWORD 's7n7Q5wPk8peGGSXfPk8pewXkA';
GRANT CONNECT ON DATABASE postgres TO web;
GRANT USAGE ON SCHEMA app TO web;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app TO web;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA app TO web;


-- VIEW for API to get metrics
CREATE VIEW app.raster_metric_monthly AS 
    SELECT     
        --SUBSTRING(r.id, 1, 4) AS year, -- for test with dummy data
        --SUBSTRING(r.id, 5, 2) AS month, -- for test with dummy data
        EXTRACT(YEAR FROM r.created) AS year, 
        EXTRACT(MONTH FROM r.created) AS month, 
        COUNT(r.*) AS count,
        MIN(v.num_tiles_x * v.num_tiles_y) AS min_num_tiles, 
        MAX(v.num_tiles_x * v.num_tiles_y) AS max_num_tiles, 
        AVG(v.num_tiles_x * v.num_tiles_y) AS avg_num_tiles, 
        SUM(v.num_tiles_x * v.num_tiles_y) AS total_num_tiles, 
        MIN(v.area) AS min_area, 
        MAX(v.area) AS max_area,
        AVG(v.area) AS mean_area,
        SUM(v.area) AS total_area,
        COUNT(i.*) AS invalid_cnt
    FROM app.raster r 
    LEFT JOIN app.raster_valid v ON r.id = v.raster 
    LEFT JOIN app.raster_invalid i ON r.id = i.raster  
    GROUP BY year, month;

GRANT SELECT ON app.raster_metric_monthly TO web;

CREATE VIEW app.raster_metric_yearly AS
    SELECT
        --SUBSTRING(r.id, 1, 4) AS year,   -- for test with dummy data   
        EXTRACT(YEAR FROM r.created) AS year, 
        COUNT(r.*) AS count,
        MIN(v.num_tiles_x * v.num_tiles_y) AS min_num_tiles, 
        MAX(v.num_tiles_x * v.num_tiles_y) AS max_num_tiles, 
        AVG(v.num_tiles_x * v.num_tiles_y) AS avg_num_tiles, 
        SUM(v.num_tiles_x * v.num_tiles_y) AS total_num_tiles, 
        MIN(v.area) AS min_area, 
        MAX(v.area) AS max_area,
        AVG(v.area) AS mean_area,
        SUM(v.area) AS total_area,
        COUNT(i.*) AS invalid_cnt
    FROM app.raster r 
    LEFT JOIN app.raster_valid v ON r.id = v.raster 
    LEFT JOIN app.raster_invalid i ON r.id = i.raster  
    GROUP BY year;

GRANT SELECT ON app.raster_metric_yearly TO web;

CREATE VIEW app.raster_metric AS
    SELECT 
        COUNT(r.*) AS count,
        MIN(v.num_tiles_x * v.num_tiles_y) AS min_num_tiles, 
        MAX(v.num_tiles_x * v.num_tiles_y) AS max_num_tiles, 
        AVG(v.num_tiles_x * v.num_tiles_y) AS avg_num_tiles, 
        SUM(v.num_tiles_x * v.num_tiles_y) AS total_num_tiles, 
        MIN(v.area) AS min_area, 
        MAX(v.area) AS max_area,
        AVG(v.area) AS mean_area,
        SUM(v.area) AS total_area,
        COUNT(i.*) AS invalid_cnt
    FROM app.raster r 
    LEFT JOIN app.raster_valid v ON r.id = v.raster 
    LEFT JOIN app.raster_invalid i ON r.id = i.raster;

GRANT SELECT ON app.raster_metric TO web;

-- mimic generate_id in web
CREATE OR REPLACE FUNCTION generate_id()
RETURNS VARCHAR(32) AS $$
DECLARE
    random_part VARCHAR(16) := '';
BEGIN
    random_part := array_to_string(ARRAY(SELECT chr(ascii('A') + floor(random() * 52)::integer) 
                                          FROM generate_series(1, 16)), '');    
    RETURN TO_CHAR(NOW(), 'YYYYMMDDHH24MISS') || random_part;
END;
$$ LANGUAGE plpgsql;

-- insert default original questionset when creating db
DO $$ 
DECLARE
    UUID VARCHAR(36);
    questionset_name varchar(255);
    effectset varchar[];
    data jsonb;
BEGIN
    UUID := generate_id();
    questionset_name := 'original_questionset';
    effectset := ARRAY['score']::varchar[];
    data := '{"questionset":[{"text":"Is this an aerial image of an area that has been affected by bushfire, flood, storms, or none of the above?","answers":[{"text":"bushfire","effects":[],"subquestions":[{"text":"Is this an aerial image of some manmade property that has been damaged or destroyed by the bushfire?","answers":[{"text":"yes","effects":[{"name":"score","value":"1.0"}],"subquestions":[]},{"text":"no","effects":[{"name":"score","value":0.5}],"subquestions":[]}]}]},{"text":"flood","effects":[],"subquestions":[{"text":"Is this an aerial image of some manmade property that has been damaged by the flood?","answers":[{"text":"yes","effects":[{"name":"score","value":"1.0"}],"subquestions":[]},{"text":"no","effects":[],"subquestions":[{"text":"Is this an aerial image of an object that has been been displaced by the flood?","answers":[{"text":"yes","effects":[{"name":"score","value":"0.8"}],"subquestions":[]},{"text":"no","effects":[{"name":"score","value":0.5}],"subquestions":[]}]}]}]}]},{"text":"storms","effects":[],"subquestions":[{"text":"Is this an aerial image of some manmade property that has been damaged or destroyed by the storms?","answers":[{"text":"yes","effects":[{"name":"score","value":"1.0"}],"subquestions":[]},{"text":"no","effects":[],"subquestions":[{"text":"Is this an aerial image of scattered debris?","answers":[{"text":"yes","effects":[{"name":"score","value":"0.8"}],"subquestions":[]},{"text":"no","effects":[{"name":"score","value":0.5}],"subquestions":[]}]}]}]}]},{"text":"none of the above","effects":[],"subquestions":[{"text":"Is this an aerial image of some manmade property?","answers":[{"text":"yes","effects":[{"name":"score","value":"0.2"}],"subquestions":[]},{"text":"no","effects":[{"name":"score","value":"0.0"}],"subquestions":[]}]}]}]}],"questionset_id":null,"questionset_name":"decision_tree.yml"}';    
    data := jsonb_set(data, '{questionset_id}', to_jsonb(UUID));

    INSERT INTO app.questionsets (id, name, effectset, data) 
        VALUES (
            UUID,
            questionset_name, 
            effectset,
            data 
        );
END $$;