import json
import string
import random
from datetime import datetime
from dataclasses import dataclass, asdict
import contextlib
import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pyproj import Geod
from rasterio import Affine
from background import update_view

log = logging.getLogger(__name__)

db_url = os.getenv("DB_URL",
                   default="postgresql://postgres:postgres@localhost:5432/postgres")


@contextlib.contextmanager
def open_db_cursor(user_id=None):
    with psycopg2.connect(db_url) as db:
        with db.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.execute("SET SEARCH_PATH TO app")
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            if user_id:
                cursor.execute("SET LOCAL app.user_id = %s", (user_id,))
            yield cursor


@dataclass
class Grid:
    raster_width: int
    raster_height: int
    tile_width: int = 224
    tile_height: int = 224
    tiles_x_per_chunk: int = 256
    tiles_y_per_chunk: int = 256
    tile_overlap_x: int = 56
    tile_overlap_y: int = 56

            
def get_num_tiles(grid: Grid):
    centre_width = grid.tile_width - 2 * grid.tile_overlap_x
    centre_height = grid.tile_height - 2 * grid.tile_overlap_y

    num_tiles_x = (grid.raster_width + centre_width - 1) // centre_width
    num_tiles_y = (grid.raster_height + centre_height - 1) // centre_height

    return num_tiles_x, num_tiles_y


# get square metre area
def cal_area(bounds):
    lons = [bounds[0], bounds[2], bounds[2], bounds[0]]
    lats = [bounds[1], bounds[1], bounds[3], bounds[3]]
    geod = Geod('+a=6378137 +f=0.0033528106647475126')
    poly_area, poly_perimeter = geod.polygon_area_perimeter(lons, lats)
    return poly_area
    

def make_float(start, end):
    base = random.randrange(start, end)
    decimal = random.randrange(10000, 90000)
    number = float(f"{base}.{decimal}")
    return number


def generate_id():
    return datetime.utcnow().strftime("%Y%m%d%H%M%S") + "".join(
        random.choices(string.ascii_letters + string.digits, k=16))


def pseudo_timestamp():
    year = random.randrange(2019, 2025)
    mm = random.randrange(1, 13)
    date = random.randrange(1, 31)
    date_str = f"{year}{str(mm).zfill(2)}{str(date).zfill(2)}"
    time = datetime.utcnow().strftime("%H%M%S")
    timestamp = f"{date_str}{time}"
    return timestamp



def insert_dummy_data():
    random_name = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    id = pseudo_timestamp() + random_name
    file = os.path.join(f'.cache/dra/{id}', random_name)
    
    bounds = [] # left bottom right top   LAT [-90, 90]. LON [-180, 180).
    # Australia bounds: (-43.00311 to -12.46113) (113.6594 to 153.61194).

    left = make_float(114, 153)
    bottom = make_float(-43, -12)
    right = left  + random.choice([i*0.001 for i in range(1, 300)]) #500
    top = bottom  + random.choice([i*0.001 for i in range(1, 300)]) #500
    bounds = (left, bottom, right, top)
    latlon = list(bounds) 

    hash = 1
    size = 1
    bands = 1
    crs = "EPSG:4326"
    transform = list(Affine(300.0379266750948, 0.0, 101985.0, 0.0, -300.041782729805, 2826915.0))

    dimensions = [i*100 for i in range(6, 100)] + [i*1000 for i in range(10, 90, 5)] 
    width = random.choice(dimensions) + random.randrange(1, 100)
    height = random.randrange(width-400, width +400)

    bounds_wkt = f"POLYGON(({bounds[0]} {bounds[1]}, {bounds[2]} {bounds[1]}, {bounds[2]} {bounds[3]}, {bounds[0]} {bounds[3]}, {bounds[0]} {bounds[1]}))"
    effectset=[]
    grid = Grid(width, height)
    area = cal_area(bounds) # insert into raster_valid
    num_tiles_x, num_tiles_y  = get_num_tiles(grid) 


    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO app.raster (id, name, file, questionset_id ) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (id, random_name, file, None))
    except Exception as e:
        print(f"Error: {e}")


    # Cause invalid raster with 20% prob
    if random.random() > 0.8: # invalid
        with open_db_cursor() as cursor:
            reason = random.choice(["NO_CRS","NO_TRANSFORM", "NOT_RGBA"])
            cursor.execute(
                "INSERT INTO raster_invalid (raster, reason) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (id, reason))
    
    else: # valid
        with open_db_cursor() as cursor:
            cursor.execute(
                "INSERT INTO raster_valid (raster, hash, size, width, height, bands, crs, transform, latlon, bounds, grid, effectset, area, num_tiles_x, num_tiles_y) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (id, hash, size, width, height, bands, crs, transform, latlon , bounds_wkt, json.dumps(asdict(grid)), effectset, area, num_tiles_x, num_tiles_y ))
               

if __name__ == "__main__":
    print("metric has started")
    NUM_DATA_TO_INSERT = 30 # 1000

    for i in range(NUM_DATA_TO_INSERT):
        insert_dummy_data()

    print("metric ended")