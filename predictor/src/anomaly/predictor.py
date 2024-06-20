import asyncio
import logging
import os
import random
import shutil
from dataclasses import dataclass, asdict
import json

import numpy as np
from affine import Affine
from msgpack import packb, unpackb
import yaml

from lavis.models import load_model_and_preprocess

from nats_worker import Worker
from PIL import Image
import rasterio
from rasterio.windows import Window

from fs import open_fs
from pathlib import Path
import tempfile
from .logger import CustomLogger

worker = Worker("predictor")

tmp_dir = tempfile.gettempdir()
local_path_fs = f"{tmp_dir}/dra"
remote_fs_url = os.getenv("REMOTE_FS", default=local_path_fs)
Path(local_path_fs).mkdir(parents=True, exist_ok=True)

cache_dir = os.path.expanduser(os.environ.get("CACHE_DIR", "~/.cache/dra"))
log_dir = os.path.join(cache_dir, 'logs')
log = CustomLogger.setup_logger(__name__, save_to_disk=True, log_dir=log_dir)

device = "cuda"

# xxl is the only model that works, but you may want to use a smaller model while developing other parts of the system
pretrained_model_size = "xxl"
model_size = os.getenv("MODEL_SIZE", default=pretrained_model_size)
# model_size = "dummy"

model, vis_processors, text_processors = load_model_and_preprocess(
    "blip2_t5", f"pretrain_flant5{model_size}", device=device, is_eval=True
) if model_size != "dummy" else (None, None, None)


@dataclass
class Chunk:
    id: str
    file: str
    questionset: list
    effectset: list
    grid: dict
    chunk: list

def explore_questionset(img_features, subquestions, path, effectset, effects_dict):

    for decision_tree_cursor in subquestions:
        question = decision_tree_cursor["text"]
        prompt = f"Question: {question} Answer: "

        answers_list= [ each['text'] for each in decision_tree_cursor["answers"]]

        if model is not None:
            answer = apply_model(img_features, prompt)
        else: 
            answer = random.choice(answers_list + ["none of the above"])


        answer_item = [each for each in decision_tree_cursor["answers"] if each['text'] == answer]

        # if the model gives unexpected answer, skip that path.
        if not answer_item:   
            log.info(f"model_answer: {answer} not in available answers. Skip this path.")      
            # return effects_dict
            continue

        path += f"{question}/{answer}/" # for checking whether correctly tracking scores.

        if answer_item:
            effects = answer_item[0]['effects']
            subquestions = answer_item[0]['subquestions']

            try:
                for effect in effects:
                    name = effect['name']
                    score = effect['value']
                    effect_path = path + name

                    if effectset and name in effectset:
                        effectset.remove(name)                   
                        effects_dict[name] = {'score':score, 'path':effect_path}

                    if not effectset:
                        break
                
                if effectset and subquestions:              
                    effects_dict = explore_questionset(img_features, subquestions, path, effectset, effects_dict)
                    return effects_dict
                    # print('next decision_tree_cursor:', decision_tree_cursor)
            except KeyError:
                break        

        if not effectset: # break because effects_set is empty
            break

    return effects_dict


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


def apply_model(img_features, prefix=""):
    if model is None:
        return "dummy"

    model_output = model.generate(
        {"image": img_features, "prompt": prefix},
        use_nucleus_sampling=True,
        temperature=1,
        length_penalty=1,
        repetition_penalty=1.5,
        max_length=30,
    )

    return model_output[0]


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


def get_tiles(grid, chunk_x, chunk_y):    

    centre_width = grid.tile_width - grid.tile_overlap_x * 2
    centre_height = grid.tile_height - grid.tile_overlap_y * 2

    num_tiles_x = (grid.raster_width + centre_width - 1) // centre_width
    num_tiles_y = (grid.raster_height + centre_height - 1) // centre_height

    num_tiles_x = min(grid.tiles_x_per_chunk, num_tiles_x - chunk_x * grid.tiles_x_per_chunk)
    num_tiles_y = min(grid.tiles_y_per_chunk, num_tiles_y - chunk_y * grid.tiles_y_per_chunk)

    x_offset = chunk_x * grid.tiles_x_per_chunk * centre_width
    y_offset = chunk_y * grid.tiles_y_per_chunk * centre_height

    for tile_y in range(num_tiles_y):
        for tile_x in range(num_tiles_x):
            yield Window(
                col_off=x_offset + tile_x * centre_width - grid.tile_overlap_x,
                row_off=y_offset + tile_y * centre_height - grid.tile_overlap_y, 
                width=grid.tile_width,
                height=grid.tile_height
            )

        
async def publish_chunk_result(chunk:Chunk, subject:str, id:str):
    payload = json.dumps(asdict(chunk)).encode()
    await worker.publish_msg(
            packb(payload),
            subject=subject,
            id=id
    )

@worker.background_consumer(subject="chunk.new", ack_wait=3600)
async def process_chunks(msg):
    data = unpackb(msg.data)
    request = Chunk(**json.loads(data))

    id = request.id
    remote_file = request.file
    questionset = request.questionset
    effectset = request.effectset
    grid =  Grid(**request.grid) 
    chunk_x, chunk_y = request.chunk
    attempt = msg.metadata.num_delivered
    if attempt < 5:
        band_size = len(effectset)
        effects_dict = {k:  {'score':0.0} for k in effectset}  # will store score value and path (q1/a1/q2/a2/.../e4) 
        
        subquestions = questionset
        path = ""

        src_file = os.path.join(cache_dir, id, "src.tif")
        await download_and_cache(remote_file, src_file)

        log.info(f"processing batch for {remote_file}")

        with rasterio.open(src_file, "r") as src:
            crs = src.crs
            dst_file = f"{cache_dir}/{id}/dst-{chunk_x}-{chunk_y}-{attempt}.tif"

            centre_width = grid.tile_width - grid.tile_overlap_x * 2
            centre_height = grid.tile_height - grid.tile_overlap_y * 2

            x_offset = chunk_x * grid.tiles_x_per_chunk 
            y_offset = chunk_y * grid.tiles_y_per_chunk


            num_tiles_x = (grid.raster_width + centre_width - 1) // centre_width
            num_tiles_y = (grid.raster_height + centre_height - 1) // centre_height

            num_tiles_x = min(grid.tiles_x_per_chunk, num_tiles_x - chunk_x * grid.tiles_x_per_chunk)
            num_tiles_y = min(grid.tiles_y_per_chunk, num_tiles_y - chunk_y * grid.tiles_y_per_chunk)
            
            if crs is not None:
                dst_profile = {
                    "driver": "GTiff",
                    "width": min(num_tiles_x, (src.width - x_offset) // centre_width + 1), 
                    "height": min(num_tiles_y, (src.height - y_offset) // centre_height + 1),
                    "count": band_size,
                    "dtype": np.float32,
                    "crs": crs,
                    "transform": src.transform  * Affine.scale(centre_width,centre_height) * Affine.translation(x_offset, y_offset),
                    "compress": "lzw"
                }

            else:
                dst_profile = {
                    "driver": "GTiff",
                    "width": min(num_tiles_x, (src.width - x_offset) // centre_width + 1), 
                    "height": min(num_tiles_y, (src.height - y_offset) // centre_height + 1),
                    "count": band_size,
                    "dtype": np.float32,
                    "transform": src.transform  * Affine.scale(centre_width,centre_height) * Affine.translation(x_offset, y_offset),
                    "compress": "lzw"
                }

            with rasterio.open(
                    dst_file,
                    "w",
                    **dst_profile) as dst:
                for window in get_tiles(grid, chunk_x, chunk_y):
        
                    await asyncio.sleep(0)

                    img_data = src.read(
                        window=window,
                        boundless=True,
                        fill_value=src.nodata,
                    )[:3, :, :].transpose(1, 2, 0)

                    if np.all(img_data == src.nodata):
                        continue

                    img = Image.fromarray(
                        img_data
                    )

                    img_features = (
                        vis_processors["eval"](img)
                        .unsqueeze(0)
                        .to("cuda")
                    ) if model is not None else None

                    effectset_ = effectset.copy() # just to be sure not to be referenced inside recursive.
                    effects_dict_ = effects_dict.copy() 
                    result = explore_questionset(img_features, subquestions, path, effectset_, effects_dict_)
                    scores = [ v['score'] for k, v in result.items()]

                    x_tile = (window.col_off + grid.tile_overlap_x) // centre_width - grid.tiles_x_per_chunk * chunk_x
                    y_tile = (window.row_off + grid.tile_overlap_y) // centre_height - grid.tiles_y_per_chunk * chunk_y

                    for i in range(band_size):
                        if scores[i]==0:
                            continue
                        
                        dst.write(
                            np.array([[scores[i]]]),
                            i+1, # band_index from 1,
                            window=Window(
                                x_tile, 
                                y_tile,
                                1,
                                1,
                            ),
                        )

            # Upload to remote fs
            remote_dst_file = os.path.join(id, f"dst-{chunk_x}-{chunk_y}-{attempt}.tif")

            log.info(f"Uploading file {remote_dst_file}")
            with open(dst_file, "rb") as f:
                with open_fs(remote_fs_url) as fs:
                    with fs.open(remote_dst_file, "wb") as dst:
                        shutil.copyfileobj(f, dst)
            log.info(f"Sending message {remote_dst_file}")
            # Overwrite request chunk object's file (id/src.tif) with dst file
            request.file = remote_dst_file
            await publish_chunk_result(request, 
                                    subject="chunk.result", 
                                    id=f"chunk.result.{id}/{chunk_x},{chunk_y}")
            log.info(f"Message send {remote_dst_file}")

    else:
        # fail the process as it has attempted 5 times already
        log.error(f"Chunk {id}/{chunk_x},{chunk_y} processing failed after 5 attempts")
        await publish_chunk_result(request, 
                                subject="chunk.failed", 
                                id=f"chunk.failed.{id}/{chunk_x},{chunk_y}")


async def delete_temp(id:str):
    try:
        path = os.path.join(cache_dir, id)
        await asyncio.to_thread(shutil.rmtree, path)
        log.info(f"Temp folder '{path}' deleted successfully after processing")
    except Exception as e:
        log.error(f"Failed to delete temp folder '{path}' after processing: {e}")

# consumer to delete files from cache after processing of the full file
@worker.background_consumer(subject="result.tiled", ack_wait=60)
async def delete_temp_file(msg):
    data = unpackb(msg.data, raw=False)
    id = data["id"]
    await delete_temp(id)
        
if __name__ == "__main__":
    print("predictor has started")
    worker.start_as_app()
