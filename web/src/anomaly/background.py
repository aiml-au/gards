
import asyncio
import json
import string
import random
from datetime import datetime

from affine import Affine
from dataclasses import dataclass, asdict
from typing import Optional
import contextlib
import os
import shutil
import zlib

import numpy as np
import psycopg2
import rasterio
from fs import open_fs
from msgpack import unpackb, packb
from nats_worker import Worker
from psycopg2.extras import RealDictCursor
from rasterio import RasterioIOError
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from pyproj import Geod

TILE_SIZE = 224
TILE_OVERLAP = 56
TILE_CENTER = TILE_SIZE - 2 * TILE_OVERLAP

from .logger import CustomLogger



worker = Worker("web")

cache_dir = os.path.expanduser(os.environ.get("CACHE_DIR", "~/.cache/dra"))
log_dir = os.path.join(cache_dir, 'logs')
remote_fs_url = os.getenv("REMOTE_FS", default="/tmp/dra")
remote_fs = open_fs(remote_fs_url, create=True)
container = os.getenv("REMOTE_CONTAINER", default="app-data")
db_url = os.getenv("DB_URL",
                   default="postgresql://postgres:postgres@localhost:5432/postgres")

log = CustomLogger.setup_logger(__name__, save_to_disk=True, log_dir=log_dir)
def generate_id():
    return datetime.utcnow().strftime("%Y%m%d%H%M%S") + "".join(
        random.choices(string.ascii_letters + string.digits, k=16))


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

@dataclass
class Raster:
    id: str
    name: str
    file: str
    questionset_id: Optional[str] = None
    questionset: Optional[list] = None
    effectset: Optional[list] = None
    crs: Optional[list] = None

@dataclass
class Chunk:
    id: str
    file: str
    questionset: list
    effectset: list
    grid: dict
    chunk: list
  
async def publish_new_chunk(chunk:Chunk, subject:str, id:str):
    payload = json.dumps(asdict(chunk)).encode()
    await worker.publish_msg(
            packb(payload),
            subject=subject,
            id=id
    )


async def publish_new_raster(raster:Raster, subject:str, id:str):
    payload = json.dumps(asdict(raster)).encode()
    await worker.publish_msg(
            packb(payload),
            subject=subject,
            id=id
    )
            
            
def get_num_tiles(grid: Grid):
    centre_width = grid.tile_width - 2 * grid.tile_overlap_x
    centre_height = grid.tile_height - 2 * grid.tile_overlap_y

    num_tiles_x = (grid.raster_width + centre_width - 1) // centre_width
    num_tiles_y = (grid.raster_height + centre_height - 1) // centre_height

    return num_tiles_x, num_tiles_y


def get_num_chunks(grid: Grid):
    num_tiles_x, num_tiles_y = get_num_tiles(grid)

    num_chunks_x = (num_tiles_x + grid.tiles_x_per_chunk - 1) // grid.tiles_x_per_chunk
    num_chunks_y = (num_tiles_y + grid.tiles_y_per_chunk - 1) // grid.tiles_y_per_chunk

    return num_chunks_x, num_chunks_y


def calculate_crc32(file_path, chunk_size=1024 * 1024):
    crc = 0
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            crc = zlib.crc32(chunk, crc)
    return crc

async def delete_temp(id:str):
    try:
        path = os.path.join(cache_dir, id)
        await asyncio.to_thread(shutil.rmtree, path)
        # log.info(f"Temp folder '{path}' deleted successfully after processing")
    except Exception as e:
        log.error(f"Failed to delete temp folder '{path}' after processing: {e}")


# get square metre area
def cal_area(bounds):
    lons = [bounds[0], bounds[2], bounds[2], bounds[0]]
    lats = [bounds[1], bounds[1], bounds[3], bounds[3]]

    # https://en.wikipedia.org/?title=WGS84    
    # param '+a=6378137 +f=0.0033528106647475126': the shape and size of the WGS84 ellipsoid
    # +a=6378137: specifies the semi-major axis of the ellipsoid, which is the equatorial radius of the Earth in meters.   
    # +f=0.0033528106647475126: represents the flattening of the ellipsoid. 
    geod = Geod('+a=6378137 +f=0.0033528106647475126')
    poly_area, poly_perimeter = geod.polygon_area_perimeter(lons, lats)
    return poly_area


def rewrite_for_maps(src_file_path, dst_file):
    dst_profile = cog_profiles.get("deflate")
    cog_translate(src_file_path, dst_file, dst_profile, in_memory=True, web_optimized=True)


async def download_and_cache(remote_file, dst_file):
    def download(remote_file, dst_file):
        if not os.path.exists(dst_file):
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            log.info(f"Downloading file {remote_file}")
            with open_fs(remote_fs_url) as fs:
                with fs.open(remote_file, "rb") as f:
                    with open(dst_file, "wb") as f2:
                        shutil.copyfileobj(f, f2)
    await asyncio.to_thread(download, remote_file, dst_file)


def get_questionset(id): 
    with open_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT data
            FROM questionsets
            WHERE id = %s 
            """,
            (id, )
        )
        row = cursor.fetchone()
        
        if row:
            questionset = row["data"]["questionset"]
            return questionset


# function to get list of effects from nested questionset 
def extract_values(dct, names):
    if isinstance(dct, list):
        for i in dct:
            extract_values(i, names)
    elif isinstance(dct, dict):
        for k, v in dct.items():
            if k == "effects":
                effects = [each['name'] for each in v]
                names.extend(effects)
                continue
            extract_values(v, names)
    
    return names


@worker.background_consumer(subject="raster.new")
async def index_new_raster(msg):
    log.info(f"Received message: {msg}")

    data = unpackb(msg.data, raw=False)
    raster = Raster(**json.loads(data))

    id = raster.id
    remote_src_file = raster.file
    questionset_id = raster.questionset_id
    questionset = get_questionset(questionset_id)
    effectset = extract_values(questionset, [])
    effectset = sorted(list(set(effectset)))
    log.info(f'# effectset: {effectset}')

    raster.questionset = questionset
    raster.effectset = effectset

    src_file = os.path.join(cache_dir, id, "src.tif")
    await download_and_cache(remote_src_file, src_file)

    log.info(f"Opening file {src_file} for {id}")

    try:
        src = rasterio.open(src_file, "r", driver="GTiff")
    except RasterioIOError:
        await worker.publish_msg(packb({"id": id, "reason": "INVALID_GEOTIFF"}),
                                 subject="raster.invalid", id=f"raster.invalid.{id}")
        log.debug(f"Failed to open file {src_file} for {id}.", exc_info=True)
        await delete_temp(id)
        return

    with src:

        # Validate the file

        if src.transform is None:
            await worker.publish_msg(packb({"id": id, "reason": "NO_TRANSFORM"}),
                                     subject="raster.invalid", id=f"raster.invalid.{id}")
            return

        if src.count != 4 and src.count != 3:
            await worker.publish_msg(packb({"id": id, "reason": "NOT_RGBA"}),
                                     subject="raster.invalid", id=f"raster.invalid.{id}")
            return

        
        
        hash = calculate_crc32(src_file)
        size = os.path.getsize(src_file)
        bands = src.count
        crs = json.dumps(src.crs.to_dict()) if src.crs is not None else None
        transform = list(src.transform.to_gdal()) if src.transform is not None else None
        width = src.width
        height = src.height
        grid = Grid(width, height)
        num_tiles_x, num_tiles_y = get_num_tiles(grid) 
        raster.crs = crs
        if src.crs is None:
            
            # await worker.publish_msg(packb({"id": id, "reason": "NO_CRS"}),
            #                          subject="raster.invalid", id=f"raster.invalid.{id}")
            # return
            latlon = None
            area = None
            bounds_wkt = None
            with open_db_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO raster_valid (raster, hash, size, width, height, bands, crs, transform, latlon, bounds, grid, effectset, area, num_tiles_x, num_tiles_y) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (id, hash, size, width, height, bands, crs, transform, latlon , bounds_wkt, json.dumps(asdict(grid)), effectset, area, num_tiles_x, num_tiles_y ))
        else:
            
            bounds = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
            if bounds[0] < -180 or bounds[1] < -90 or bounds[2] > 180 or bounds[3] > 90:
                await worker.publish_msg(packb({"id": id, "reason": "INVALID_BOUNDS"}),
                                        subject="raster.invalid", id=f"raster.invalid.{id}")
                return
            latlon = list(bounds)
            bounds_wkt = f"POLYGON(({bounds[0]} {bounds[1]}, {bounds[2]} {bounds[1]}, {bounds[2]} {bounds[3]}, {bounds[0]} {bounds[3]}, {bounds[0]} {bounds[1]}))"
            area = cal_area(bounds) 
            with open_db_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO raster_valid (raster, hash, size, width, height, bands, crs, transform, latlon, bounds, grid, effectset, area, num_tiles_x, num_tiles_y) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (id, hash, size, width, height, bands, crs, transform, latlon , bounds_wkt, json.dumps(asdict(grid)), effectset, area, num_tiles_x, num_tiles_y ))

        await publish_new_raster(raster, subject="raster.valid", id=f"raster.valid.{id}")



@worker.background_consumer(subject="raster.valid")
async def tile_raster(msg):

    data = unpackb(msg.data, raw=False)
    raster = Raster(**json.loads(data))
    id = raster.id
    src_file = os.path.join(cache_dir, id, "src.tif")
    src_url = os.path.join(id, "src.tif")
    tiles_file = os.path.join(cache_dir, id, "src-tiles.tif")
    tiles_url = os.path.join(id, "src-tiles.tif")
    await download_and_cache(src_url, src_file)
    log.info(f"Writing tiles for {id}")
    if raster.crs is not None:
        await asyncio.to_thread(rewrite_for_maps, src_file, tiles_file)
    else:
        tiles_file = src_file
   
    with open_fs(remote_fs_url) as fs:
        with fs.open(tiles_url, 'wb') as remote_file, open(
                tiles_file, "rb"
        ) as cache_file:
            shutil.copyfileobj(cache_file, remote_file)

    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO raster_tiled (raster, file) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id, tiles_url))

    await worker.publish_msg(packb(data), subject="raster.tiled", id=f"raster.tiled.{id}")
    log.info("Complete")



@worker.background_consumer(subject="raster.valid")
async def break_up_raster(msg):
    log.info("Breaking file into chunks and sending to workers")

    data = unpackb(msg.data, raw=False)
    raster = Raster(**json.loads(data))
    id = raster.id
    questionset = raster.questionset
    effectset = raster.effectset

    remote_src_file = os.path.join(id, "src.tif")

    src_file = os.path.join(cache_dir, id, "src.tif")
    await download_and_cache(remote_src_file, src_file)

    with rasterio.open(src_file, "r", driver="GTiff") as src:

        grid = Grid(src.width, src.height)

        num_chunks_x, num_chunks_y = get_num_chunks(grid)

        with open_db_cursor() as cursor:

            for chunk_x in range(num_chunks_x):
                for chunk_y in range(num_chunks_y):
                    chunk_id = f"{id}/{chunk_x},{chunk_y}"
                    cursor.execute(
                        "INSERT INTO chunk (id, raster, x, y) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (chunk_id, id, chunk_x, chunk_y))
                    
            
        for chunk_x in range(num_chunks_x):
            for chunk_y in range(num_chunks_y):
                chunk_id = f"{id}/{chunk_x},{chunk_y}"     
                chunk = Chunk(id=id, file=remote_src_file, questionset=questionset, 
                                effectset=effectset, grid=asdict(grid), chunk=[chunk_x, chunk_y])        
                await publish_new_chunk(chunk, subject=f"chunk.new", id=f"chunk.new.{chunk_id}")


@worker.background_consumer(subject="raster.invalid")
async def catch_invalid_rasters(msg):
    log.info("catch_invalid_rasters")

    data = unpackb(msg.data, raw=False)
    id = data["id"]
    reason = data["reason"]

    log.info(f"Received invalid for {id}")
    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO raster_invalid (raster, reason) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id, reason))


async def check_chunks_finished(cursor, id):
    cursor.execute(
        "SELECT grid FROM raster_valid WHERE raster = %s",
        (id,))
    grid = Grid(**json.loads(cursor.fetchone()["grid"]))

    num_chunks_x, num_chunks_y = get_num_chunks(grid)

    cursor.execute(
        """
        SELECT
            COUNT(*) AS count
        FROM chunk c
        WHERE
            c.raster = %s
            AND (EXISTS (SELECT 1 FROM chunk_result cr WHERE cr.chunk = c.id)
            OR EXISTS (SELECT 1 FROM chunk_failed cf WHERE cf.chunk = c.id))
        """,
        (id,))

    count = cursor.fetchone()["count"]

    log.info(f"Received {count} of {num_chunks_x * num_chunks_y}")
    log.info(f"num_chunks_x:{num_chunks_x}")
    log.info(f"num_chunks_y:{num_chunks_y}")
    if count >= num_chunks_x * num_chunks_y:
        await worker.publish_msg(
            packb({"id": id, "grid": asdict(grid)}),
            subject="result.new",
            id=f"result.new.{id}"
        )


@worker.background_consumer(subject="chunk.failed")
async def catch_failed_chunks(msg):
    data = unpackb(msg.data, raw=False)
    id = data["id"]
    chunk_x, chunk_y = data["chunk"]
    reason = data["reason"]

    log.info(f"Received failure for {id}/{chunk_x},{chunk_y}")

    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO chunk_failed (chunk, reason) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (f"{id}/{chunk_x},{chunk_y}", reason)
        )

        await check_chunks_finished(cursor, id)


@worker.background_consumer(subject="chunk.result", ack_wait=60)
async def record_chunk_result(msg):
    log.info("record_chunk_result")

    data = unpackb(msg.data, raw=False)
    data = Chunk(**json.loads(data))
    id = data.id
    chunk_x, chunk_y = data.chunk 
    file = data.file

    log.info(f"Received result for {id}/{chunk_x},{chunk_y}")

    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO chunk_result (chunk, label, file) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (f"{id}/{chunk_x},{chunk_y}", "anomaly", file)
        )

        await check_chunks_finished(cursor, id)


@worker.background_consumer(subject="result.new", ack_wait=60)
async def write_results(msg):
    data = unpackb(msg.data, raw=False)

    id = data["id"]

    with open_db_cursor() as cursor:
        cursor.execute("SELECT grid, crs, transform, effectset FROM raster_valid WHERE raster = %s", (id,))
        response = cursor.fetchone()
        grid = Grid(**json.loads(response["grid"]))
        if response["crs"] is not None:
            crs = rasterio.CRS.from_dict(json.loads(response["crs"]))
        else:
            crs = None
        
        transform = rasterio.Affine.from_gdal(*response["transform"])
        num_effects = len(response["effectset"])

    dst_file = os.path.join(cache_dir, id, "dst.tif")
    os.makedirs(os.path.dirname(dst_file), exist_ok=True)

    log.info(f"Writing to file {dst_file} for {id}")

    with open_db_cursor() as cursor:
        cursor.execute(
            "SELECT c.x AS chunk_x, c.y AS chunk_y, cr.file AS result_file FROM chunk c INNER JOIN app.chunk_result cr on c.id = cr.chunk WHERE c.raster = %s",
            (id,))

        results = cursor.fetchall()

    centre_width = grid.tile_width - 2 * grid.tile_overlap_x
    centre_height = grid.tile_height - 2 * grid.tile_overlap_y
    if crs is not None:
        dst_profile = {
            "driver": "GTiff",
            "width": grid.raster_width // centre_width + 1,
            "height": grid.raster_height // centre_height + 1,
            "count": num_effects,
            "dtype": np.float32,
            "crs": crs,
            "transform": transform * Affine.scale(centre_width, centre_height),
            "compress": "lzw"
        }

    else:
        dst_profile = {
            "driver": "GTiff",
            "width": grid.raster_width // centre_width + 1,
            "height": grid.raster_height // centre_height + 1,
            "count": num_effects,
            "dtype": np.float32,
            "transform": transform * Affine.scale(centre_width, centre_height),
            "compress": "lzw"
        }

    with rasterio.open(dst_file, "w", **dst_profile) as dst:
        for result in results:
            chunk_x = result["chunk_x"]
            chunk_y = result["chunk_y"]
            dst_chunk_file = os.path.join(cache_dir, id, f"dst-{chunk_x}-{chunk_y}.tif")
            await download_and_cache(result["result_file"], dst_chunk_file)
            
            with rasterio.open(dst_chunk_file, "r") as dst_chunk_raster:
                dst.write(
                    dst_chunk_raster.read(),
                    window=Window(
                        col_off=chunk_x * grid.tiles_x_per_chunk, 
                        row_off=chunk_y * grid.tiles_y_per_chunk, 
                        width=dst_chunk_raster.width,
                        height=dst_chunk_raster.height
                    )
                )

    remote_dst_file = os.path.join(id, "dst.tif")
    with remote_fs.open(remote_dst_file, "wb") as remote_file, open(
            dst_file, "rb"
    ) as cache_file:
        shutil.copyfileobj(cache_file, remote_file)

    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO result (id, raster, label, file) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (id, id, "anomaly", remote_dst_file)
        )

    tiles_file = os.path.join(cache_dir, id, "dst-tiles.tif")

    log.info(f"Writing tiles for to {tiles_file} for {id}")
    if crs is not None:
        await asyncio.to_thread(rewrite_for_maps, dst_file, tiles_file)
    else:
        tiles_file = dst_file
    remote_tiles_file = os.path.join(id, "dst-tiles.tif")
    with remote_fs.open(remote_tiles_file, "wb") as remote_file, \
                    open(tiles_file, "rb") as local_file:
        shutil.copyfileobj(local_file, remote_file)

    log.info(f"Saved tiles to {remote_tiles_file}")

    with open_db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO result_tiled (result, file) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (id, remote_tiles_file))

    await worker.publish_msg(
        packb({"id": id, "file": remote_tiles_file}),
        subject="result.tiled",
        id=f"result.tiled.{id}",
    )

@worker.background_consumer(subject="result.tiled", ack_wait=60)
async def delete_temp_file(msg):
    data = unpackb(msg.data, raw=False)
    id = data["id"]
    await delete_temp(id)

    
