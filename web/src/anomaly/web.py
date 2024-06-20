import asyncio
import os
import json
import re
import shutil
from contextlib import asynccontextmanager
from io import BytesIO
import random
import sys
from types import SimpleNamespace

from fastapi import FastAPI, UploadFile, Form, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from msgpack import packb
from dataclasses import asdict, dataclass

from rio_tiler.io import Reader
from rio_tiler.colormap import cmap
from starlette.requests import Request
from starlette.responses import StreamingResponse, RedirectResponse, Response
from PIL import Image
import zipfile

import signal

from starlette.staticfiles import StaticFiles

from .background import Raster, worker, remote_fs, remote_fs_url, cache_dir, container, \
                        open_db_cursor, generate_id, extract_values, publish_new_raster, \
                        delete_temp, log_dir 


from .logger import CustomLogger

log = CustomLogger.setup_logger(__name__, save_to_disk=True, log_dir=log_dir)


schema_names = {}

id_regex = re.compile(r"^[a-zA-Z0-9_-]+$")

src =  "src.tif"
json_headers = {"Accept": "application/json"}
dst = "dst.tif"
image_media_type="image/png"

# there must be some way to control this
cmap = cmap.register(
    {
        "heatmap": {
          0.0: (0, 0, 0, 0), # transparent. when no effect. source layer will be shown
          0.1: (51, 51, 51, 100), #dark gray
          0.2: (150, 150, 150, 100), #bright bray
          0.3: (0, 51, 102, 100), #dark blue
          0.4: (0, 0, 255, 110), # blue
          0.5: (0, 255, 0, 130), # green
          0.6: (0, 255, 255, 150), #cyan
          0.7: (255, 255, 0, 140), #yellow
          0.8: (102, 0, 102, 160), #purple
          0.9: (255, 0, 255, 180), #magenta
          1.0: (255, 0, 0, 200) #red
        }
    }
)


@asynccontextmanager
async def app_lifespan(app):

    loop = asyncio.get_running_loop()
    loop.set_debug(True)

    pid = os.getpid()

    log.debug(f"Running on process {pid}")

    def exit_on_error(task):
        try:
            ex = task.exception()
        except asyncio.CancelledError:
            ex = None

        if ex:
            log.exception("Worker failed", exc_info=ex)
            os.kill(pid, signal.SIGINT)
        else:
            log.info("Worker exited unexpectedly")
            os.kill(pid, signal.SIGINT)

    log.debug("Starting worker")

    task = await worker.start_as_task()
    task.add_done_callback(exit_on_error)

    app.worker_task = task

    yield

app = FastAPI(lifespan=app_lifespan)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # Wait for start command
        #start_message = await websocket.receive_text()
        log_file = os.path.join(log_dir, 'app.log')
        with open(log_file, "r") as file:
            while True:
                data = file.read()
                if data:
                    await websocket.send_text(data)
                await asyncio.sleep(1)  # Delay to prevent constant file reading
    except WebSocketDisconnect:
        print("Client disconnected")

@app.middleware("http")
async def forwarded_auth(request: Request, call_next):
    headers = request.headers

    if "x-forwarded-user" in headers:
        id = headers['x-forwarded-user']
        email = headers['x-forwarded-email']

        request.scope["user"] = SimpleNamespace(id=id, email=email)

    response = await call_next(request)
    return response

async def delete_temp(id:str):
    try:
        path = os.path.join(cache_dir, id)
        await asyncio.to_thread(shutil.rmtree, path)
        #log.info(f"Temp folder '{path}' deleted successfully after processing")
    except Exception as e:
        log.error(f"Failed to delete temp folder '{path}' after processing: {e}")

# Upload a file
@app.post("/rasters")
async def upload_raster(file: UploadFile, questionset_id: str = Form(...)):    

    file_list = None
    zip_file = False
    folder = file.filename
    return_id = ""
    if file.content_type == 'application/zip':
        id = generate_id()
        return_id = id
        log.info(f"Zip file received with id {id}")
        os.makedirs(os.path.join(cache_dir, id))
        src_folder = os.path.join(cache_dir, id, folder)
        with open(src_folder, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        try:
            with zipfile.ZipFile(src_folder, 'r') as zip_ref:
                log.info("Extracting zip file {id}")
                extract_dir = os.path.join(cache_dir, id)
                zip_ref.extractall(extract_dir)
                log.info(f"Extraction complete for {id}")
                file_list = [os.path.join(extract_dir,file_name) for file_name in zip_ref.namelist()[1:]]
                zip_file = True
        except Exception as e:
            log.error(f'Error in unzipping Zip: {e}')
            file_list = []
            zip_file = False
            return RedirectResponse(
                status_code=400,
                url=f"/folder/{return_id}",
            )
        
        os.remove(src_folder)
    else:
        file_list = [file]
    
    try:
        for ref_file in file_list:
            id = generate_id()
            os.makedirs(os.path.join(cache_dir, id))
            src_file = os.path.join(cache_dir, id, src)
            if zip_file:
                name = os.path.basename(ref_file)
                shutil.copy(ref_file, src_file)
            else:
                return_id = id
                name = ref_file.filename
                with open(src_file, "wb") as f:
                    shutil.copyfileobj(ref_file.file, f)
            
            remote_fs.makedirs(id)
            remote_src_file = os.path.join(id, src)
            log.info(f"Uploading file to {remote_src_file}")

            with remote_fs.open(remote_src_file, "wb") as remote_file, \
                    open(src_file, "rb") as cache_file:
                shutil.copyfileobj(cache_file, remote_file)
            
            log.debug(f"Saving raster entry {id} to database")

            with open_db_cursor() as cursor:
                cursor.execute(
                    "INSERT INTO raster (id, file, name, folder, folder_id, questionset_id) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (id, remote_src_file, name, folder, return_id, questionset_id))
            
            log.debug(f"Notifying workers of new raster {id}")

            raster = Raster(id=id, name=name, file=remote_src_file, questionset_id=questionset_id)
            await publish_new_raster(raster, subject="raster.new", id=f"raster.new.{id}")
            # await delete_temp(id)

    except Exception as e:
        log.error(f"Error in uploading file: {e}")
        log.warning("Some files may not have been uploaded")
    
    if zip_file:
        await delete_temp(return_id)

    return RedirectResponse(
        status_code=303,
        url=f"/folder/{return_id}",
    )

# Load templates from DB
@app.get("/raster/questions")
async def read_template(request: Request):
    log.info("Received request for questionset")
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, data
                FROM questionsets
                """
            )
            rows = cursor.fetchall()
        log.debug(f'Questionsets retrieved: {[row["name"] for row in rows]}')
        return JSONResponse(content=rows, headers=json_headers)
    except Exception as e:
        log.error(f'Error in retrieving questionset: {e}')
        return JSONResponse(status_code = 500, content = {"error": "Error retrieving questionset"})           

# Explore randomly answered path letting the user know how the template may be used by the model
@app.post("/raster/questions/validate")
async def validate(request: Request):
    try:
        data = await request.json()
        questionset = data.get("questionset")
        path = ""
        effectset = extract_values(questionset, [])
        effectset = sorted(list(set(effectset)))
        log.info(f"Validating questionset {data.get('name')} with Effectset: {effectset}")

        msg = None
        data = {}
        if not effectset:
            data["msg"] = "No effects found in this template"        
            return JSONResponse(content=data, headers=json_headers)

        effects_dict = {k:  {"score":0.0, "path":""} for k in effectset}
        samples = []
        subquestions = questionset

        for _ in range(3):
            effectset_ = effectset.copy() 
            effects_dict_ = effects_dict.copy()          
            msg, result = recursive(subquestions, path, effectset_, effects_dict_)
            if msg:
                data["msg"] = msg
                return JSONResponse(content=data, headers=json_headers)

            samples.append(result)

        data["msg"] = msg
        data["samples"] = samples
        data["effectset"] = effectset

        return JSONResponse(content=data, headers=json_headers)
    except Exception as e:
        log.error(f'Error in validating questionset: {e}')
        return JSONResponse(status_code = 500, content = {"error": "Error validating questionset"})


# Used in validate()
def recursive(subquestions, path, effectset, effects_dict):
    msg = None 

    for decision_tree_cursor in subquestions:
        question = decision_tree_cursor["text"]

        answers_list= [ each['text'] for each in decision_tree_cursor["answers"]]
        if not answers_list:
            return f"There are no answers for question: {question}", {}
        
        answer = random.choice(answers_list)
        answer_item = [each for each in decision_tree_cursor["answers"] if each["text"] == answer]

        path += f"{question}/{answer}/" # for checking whether correctly tracking scores.

        if answer_item:
            effects = answer_item[0]['effects']            
            subquestions = answer_item[0]['subquestions']
            try:
                for effect in effects:
                    name = effect['name']
                    score = effect['value']

                    def floating_valid(string):
                        try:
                            0 <= float(score) <= 1
                            return True
                        except ValueError:
                            return False

                    if not floating_valid(score):
                        return f"Enter valid value between [0.0-1.0] for effect: {name}.", {}

                    effect_path = path + name

                    if effectset and name in effectset:
                        effectset.remove(name)                   
                        effects_dict[name] = {'score':score, 'path':effect_path}

                    # if not effectset:
                    #     break
                
                if effectset and subquestions:              
                    msg, effects_dict = recursive(subquestions, path, effectset, effects_dict)
                    return msg, effects_dict

            except KeyError:
                break        

        # if not effectset: # break because effects_set is empty
        #     break

    return msg, effects_dict

 
# INSERT TEMPLATE INTO DB
@app.post("/raster/questions")
async def save_template(request: Request):

    data = await request.json()
    log.info(f'New template request_json: {data}')
    
    questionset_id = data.get("questionset_id")
    questionset = data.get("questionset")
    file_name = data.get("questionset_name")
    json_object = json.dumps(data) 

    effectset = extract_values(questionset, [])
    effectset = sorted(list(set(effectset)))
    log.info(f"Effectset: {effectset}")
    
    # Insert if no ID, otherwise UPDATE existing one
    if questionset_id: # Update        
        print('questionset_id:', questionset_id)
        print('questionset_id type:', type(questionset_id))
        log.debug(f"Updating template {questionset_id} to database")

        with open_db_cursor() as cursor:            
            cursor.execute(
                "UPDATE questionsets SET name=%s, effectset=%s, data=%s WHERE id=%s",
                (file_name, effectset, json_object, questionset_id))        

    elif questionset: # Insert new or Save as
        id = generate_id()  # questionset_id

        log.debug(f"Saving template {id} to database")        

        with open_db_cursor() as cursor:            
            cursor.execute("SELECT * FROM questionsets WHERE name = %s", (file_name,))
            exist = cursor.fetchall()

            if exist:
                file_name = file_name + f"({len(exist)})"
                data["questionset_name"] = file_name
                json_object = json.dumps(data) 

            cursor.execute(
                "INSERT INTO questionsets (id, name, effectset, data) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (id, file_name, effectset, json_object))           

        return Response(status_code=200)
    else:
        return JSONResponse(status_code = 422, content = {"error": "Error saving questionset: Invalid request"}) 


@app.get("/raster/delete_questionset/{id}")
async def delete_templates(id: str):
    log.info(f"Delete template {id} from database")        
    try:
        with open_db_cursor() as cursor:            
            cursor.execute("DELETE FROM questionsets WHERE id=%s", (id,))
        return Response(status_code=200)
    except Exception as e:
        log.error(f"Error deleting questionset template {id}: {e}")
        return JSONResponse(status_code = 404, content = {"error": "Error deleting questionset template"})


@app.delete("/delete_raster/{id}")
async def delete_raster(id:str):
    log.info(f"Delete file {id} from remote storage") 
    # delete from remote 
    try:
        with open_db_cursor() as cursor:            
            cursor.execute("SELECT id FROM app.raster WHERE folder_id=%s", (id,))
            rows = cursor.fetchall()
        if rows:
            directories = [row['id'] for row in rows]
            for directory in directories:
                if remote_fs.exists(directory):
                    remote_fs.removetree(directory)
                    with open_db_cursor() as cursor:            
                        cursor.execute("DELETE FROM app.raster WHERE id=%s", (directory,))
        return Response(status_code=200)
    except Exception as e:
        log.error(f"Error deleting file {id}: {e}") 
        return JSONResponse(status_code = 404, content = {"error": "Error deleting file"})


@app.get("/rasters/{id}.tif")
async def download_original(id: str):
    log.info(f"Downloading original file: {id}")

    remote_src_file = os.path.join(id, src)

    if remote_fs.exists(remote_src_file):

        def streaming_read(path):
            with remote_fs.open(path, "rb") as f:
                yield from f

        response = StreamingResponse(
            streaming_read(remote_src_file),
            media_type=image_media_type,
            headers={"Content-Disposition": f"attachment; filename={id}.tif"},
        )
        return response
    else:
        log.debug(f"Missing file: {id}")
        return JSONResponse(status_code = 404, content = {"error": "Error downloading file"})


@app.get("/rasters/{id}/results/anomaly")
async def download_result(id: str):
    log.info(f"Downloading result file: {id}")
    remote_dst_file = os.path.join(id, dst)

    if remote_fs.exists(remote_dst_file):

        def streaming_read(path):
            with remote_fs.open(path, "rb") as f:
                yield from f

        response = StreamingResponse(
            streaming_read(remote_dst_file),
            media_type=image_media_type,
            headers={"Content-Disposition": f"attachment; filename={id}-anomaly.tif"},
        )
        return response
    else:
        return JSONResponse(status_code = 404, content = {"error": "Error downloading file"})


@app.get("/rasters/{id}")
async def describe_raster(id: str):
    with open_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                r.id AS id,
                r.name AS name,
                CASE
                    WHEN EXISTS (SELECT 1 FROM result re WHERE r.id = re.raster) THEN 'Done'
                    WHEN EXISTS (SELECT 1 FROM chunk c INNER JOIN chunk_result cr ON c.id = cr.chunk WHERE r.id = c.raster) THEN 'Processing'
                    WHEN EXISTS (SELECT 1 FROM chunk c INNER JOIN chunk_failed cf ON c.id = cf.chunk WHERE r.id = c.raster) THEN 'Processing'
                    WHEN EXISTS (SELECT 1 FROM raster_valid rv WHERE r.id = rv.raster) THEN 'Queued'
                    WHEN EXISTS (SELECT 1 FROM raster_invalid ri WHERE r.id = ri.raster) THEN 'Invalid'
                    ELSE 'New'
                END AS status
            FROM raster r
            WHERE r.id = %s
            """,
            (id, )
        )

        if cursor.rowcount == 0:
            return Response(status_code=404)
        row = cursor.fetchone()
        return row

@app.get("/folder/{id}")
async def describe_folder(id: str):
    log.info(f'Getting folder details for {id}')
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.folder,
                    r.folder_id,
                    CASE
                        WHEN COUNT(DISTINCT c.id) - COUNT(DISTINCT res.id) > 0 AND COUNT(DISTINCT r.id) > (COUNT(DISTINCT res.id) + COUNT(DISTINCT i.raster)) THEN 'Processing'
                        WHEN COUNT(DISTINCT i.raster) = COUNT(DISTINCT r.id) THEN 'Invalid'
                        WHEN COUNT(DISTINCT res.id) + COUNT(DISTINCT i.raster) = COUNT(DISTINCT r.id) THEN 'Done'
                        WHEN COUNT(DISTINCT v.raster) = COUNT(DISTINCT r.id) AND COUNT(DISTINCT res.id) = 0 AND COUNT(DISTINCT c.id) = 0 THEN 'Queued'
                        ELSE 'New'
                    END AS status,
                    CASE
                        WHEN COUNT(v.area) = COUNT(*) THEN SUM(v.area)
                        ELSE NULL
                    END AS area
                FROM
                    app.raster r
                LEFT JOIN
                    app.chunk c ON r.id = c.id
                LEFT JOIN
                    app.result res ON r.id = res.id
                LEFT JOIN
                    app.raster_invalid i ON r.id = i.raster
                LEFT JOIN
                    app.raster_valid v ON r.id = v.raster
                WHERE 
                    r.folder_id = %s
                GROUP BY
                    r.folder_id, r.folder;
                """,
                (id, )
            )

            if cursor.rowcount == 0:
                log.info(f"No file matching {id} found")
                return JSONResponse(status_code = 404, content = {"error": "No file found"})
            row = cursor.fetchone()
            log.debug(f'Details for {id} :{row}')
            return row
    except Exception as e:
        log.error(f"Error getting folders: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error retrieving file"})


@app.get("/rasters")
async def list_rasters():
    log.info("Checking status of all jobs")
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.id AS id,
                    r.name AS name,
                    rv.latlon AS latlon,
                    rv.height AS height,
                    rv.width as width,
                    rv.effectset AS effectset,
                    rv.area AS area,
                    r.folder AS folder_name,
                    r.folder_id AS folder_id
                    CASE
                        WHEN EXISTS (SELECT 1 FROM result re WHERE r.id = re.raster) THEN 'Done'
                        WHEN EXISTS (SELECT 1 FROM chunk c INNER JOIN chunk_result cr ON c.id = cr.chunk WHERE r.id = c.raster) THEN 'Processing'
                        WHEN EXISTS (SELECT 1 FROM chunk c INNER JOIN chunk_failed cf ON c.id = cf.chunk WHERE r.id = c.raster) THEN 'Processing'
                        WHEN EXISTS (SELECT 1 FROM raster_valid rv WHERE r.id = rv.raster) THEN 'Queued'
                        WHEN EXISTS (SELECT 1 FROM raster_invalid ri WHERE r.id = ri.raster) THEN 'Invalid'
                        ELSE 'New'
                    END AS status
                FROM raster r
                INNER JOIN raster_valid rv ON r.id = rv.raster
                """
            )
            return cursor.fetchall()
    except Exception as e:
        log.error(f"Error getting rasters: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error retrieving rasters"})

@app.get("/folders")
async def list_folders():
    log.info("Checking status of all jobs")
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                    SELECT
                        r.folder AS name,
                        r.folder_id AS id,
                        q.name AS questionset,
                        CASE
                            WHEN COUNT(DISTINCT c.id) - COUNT(DISTINCT res.id) > 0 OR COUNT(DISTINCT r.id) > (COUNT(DISTINCT res.id) + COUNT(DISTINCT i.raster)) THEN 'Processing'
                            WHEN COUNT(DISTINCT i.raster) = COUNT(DISTINCT r.id) THEN 'Invalid'
                            WHEN COUNT(DISTINCT res.id) + COUNT(DISTINCT i.raster) = COUNT(DISTINCT r.id) THEN 'Done'
                            WHEN COUNT(DISTINCT v.raster) = COUNT(DISTINCT r.id) AND COUNT(DISTINCT res.id) = 0 THEN 'Queued'
                            ELSE 'New'
                        END AS status,
                        CASE
                            WHEN COUNT(v.area) = COUNT(*) THEN SUM(v.area)
                            ELSE NULL
                        END AS area
                    FROM
                        app.raster r
                    LEFT JOIN
                        app.chunk c ON r.id = c.id
                    LEFT JOIN
                        app.result res ON r.id = res.id
                    LEFT JOIN
                        app.raster_invalid i ON r.id = i.raster
                    LEFT JOIN
                        app.raster_valid v ON r.id = v.raster
                    INNER JOIN
                        app.questionsets q on r.questionset_id = q.id
                    GROUP BY
                        r.folder_id, r.folder, q.name;
                """
            )
            return cursor.fetchall()
    except Exception as e:
        log.error(f"Error getting folders: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error retrieving file"})

@app.get("/folder/raster/{id}")
def get_raster_from_folder(id: str):
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    r.id AS id,
                    r.name AS name,
                    rv.latlon AS latlon,
                    rv.height AS height,
                    rv.width as width,
                    rv.effectset AS effectset,
                    rv.area AS area,
                    r.folder_id AS folder_id,
                    CASE
                        WHEN EXISTS (SELECT 1 FROM app.result re WHERE r.id = re.raster) THEN 'Done'
                        WHEN EXISTS (SELECT 1 FROM app.chunk c INNER JOIN app.chunk_result cr ON c.id = cr.chunk WHERE r.id = c.raster) THEN 'Processing'
                        WHEN EXISTS (SELECT 1 FROM app.chunk c INNER JOIN app.chunk_failed cf ON c.id = cf.chunk WHERE r.id = c.raster) THEN 'Processing'
                        WHEN EXISTS (SELECT 1 FROM app.raster_valid rv WHERE r.id = rv.raster) THEN 'Queued'
                        WHEN EXISTS (SELECT 1 FROM app.raster_invalid ri WHERE r.id = ri.raster) THEN 'Invalid'
                        ELSE 'New'
                    END AS status
                FROM app.raster r
                INNER JOIN raster_valid rv ON r.id = rv.raster
                WHERE r.folder_id = %s
                """,
                (id, )
            )
            return cursor.fetchall()
    except Exception as e:
        log.error(f"Error getting raster {id}: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error retrieving raster"})

def get_vfs_path(remote_fs, path):

    fs_class_name = type(remote_fs).__name__
    if fs_class_name == 'GCSFS':
        return f"{remote_fs_url}/{path}" 
    elif fs_class_name == 'AzureBlobFS':
        return f"{remote_fs_url}/{path}" 
    elif fs_class_name == 'BlobFSV2':
        return f"/vsiaz/{container}/{path}" 
    elif fs_class_name == 'OSFS':
        return f"{remote_fs.root_path}/{path}"
    else:
        raise ValueError(f"Unsupported filesystem type: {fs_class_name}")

@app.get("/rasters/{id}/tiles/{z}/{y}/{x}.{ext}")
async def download_source_tile(id: str, z: int, y: int, x: int, ext: str):
    if ext != "png":
        return JSONResponse(status_code = 422, content = {"error": "Invalid File"})

    log.debug(f"Looking for tile {z}/{y}/{x} for file: {id}")
    remote_src_file = os.path.join(id, "src-tiles.tif")
    log.info(f"Fetching file: {remote_src_file}")
    if remote_fs.exists(remote_src_file):
        try:
            with Reader(get_vfs_path(remote_fs, remote_src_file)) as src_cog: 
                exist = src_cog.tile_exists(x,y,z)
                if exist:    
                    src_tile = src_cog.tile(x, y, z, indexes=[1,2,3])
                    data = src_tile.render()
                    return Response(data, media_type=image_media_type)            
                else:
                    # return an empty png
                    png = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                    s = BytesIO()
                    png.save(s, format="PNG")
                    s.seek(0)
                    return StreamingResponse(s, media_type=image_media_type) 
        except Exception as e:
            log.error(f"Error fetching file: {remote_src_file}: {e}")
            return JSONResponse(status_code = 500, content = {"error": "Error fetching file"})          
    else:
        log.info(f"File {id} not found")
        return JSONResponse(status_code = 404, content = {"error": "File not found"})
        


# keeping these independent of geo referenced ones for allow modifications            
@app.get("/rasters/source/{id}.{ext}")
async def download_source_image(id: str, ext: str):
    remote_src_file = os.path.join(id, src)
    log.info(f"Looking for {remote_src_file}")
    if remote_fs.exists(remote_src_file):
        try:
            with Reader(get_vfs_path(remote_fs,remote_src_file)) as tif:
                img = tif.read(indexes=[1,2,3])
                data = img.render(height=256, width=256)
                return Response(data, media_type=image_media_type)
        except Exception as e:
            log.error(f"Error fetching file: {remote_src_file}: {e}")
            return JSONResponse(status_code = 500, content = {"error": "Error fetching file"})  
    else:
        return JSONResponse(status_code = 404, content = {"error": "File not found"})

            
@app.get("/rasters/dest/{id}/{band}/result.{ext}")
async def download_result_image(id: str, band: int, ext: str):
    remote_dst_file = os.path.join(id, dst)
    log.info(f"Looking for {remote_dst_file}")
    if remote_fs.exists(remote_dst_file):
        log.info(f"Opening {remote_dst_file}")
        try:
            with Reader(get_vfs_path(remote_fs,remote_dst_file)) as tif:
                cm = cmap.get('heatmap') 
                img = tif.read(indexes=band, height=256, width=256) #fixed size to reduce loading time
                data = img.render(colormap=cm)
                return Response(data, media_type=image_media_type)
        except Exception as e:
            log.error(f"Error fetching file: {remote_dst_file}: {e}")
            return JSONResponse(status_code = 500, content = {"error": "Error fetching file"}) 
    else:
        return JSONResponse(status_code = 404, content = {"error": "File not found"})

@app.get("/rasters/{id}/results/{band}/tiles/{z}/{y}/{x}.{ext}")
async def download_result_tile(id: str, band: int, z: int, y: int, x: int, ext: str):
    if ext != "png":
        return Response(status_code=404)

    remote_dst_file = os.path.join(id, "dst-tiles.tif")
    log.info(f"Fetching file: {remote_dst_file}")
    
    if remote_fs.exists(remote_dst_file):
        try:
            with Reader(get_vfs_path(remote_fs, remote_dst_file)) as dst_cog: 
                exist = dst_cog.tile_exists(x,y,z)

                if exist:    
                    dst_tile = dst_cog.tile(x, y, z, indexes=band) 
                    cm=cmap.get('heatmap') 
                    data = dst_tile.render(colormap=cm)
                    return Response(data, media_type=image_media_type)
                else:
                    # # return an empty png
                    png = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
                    s = BytesIO()
                    png.save(s, format="PNG")
                    s.seek(0)
                    return StreamingResponse(s, media_type=image_media_type)
        except Exception as e:
            log.error(f"Error fetching file: {remote_dst_file}: {e}")
            return JSONResponse(status_code = 500, content = {"error": "Error fetching file"}) 
    else:
        return JSONResponse(status_code = 404, content = {"error": "File not found"})
    

# API endpoint for metrics with(out) breakdown per year and/or month.
# default: returns total 1 result
# X=True, group by **X
@app.get("/metrics")
async def get_metrics(yearly:bool=False, 
                      monthly:bool=Query(False, description="if set True, will also overwrite yearly to True")):
    
    
    with open_db_cursor() as cursor:
        if yearly:
            query = "SELECT * FROM raster_metric_yearly"
        if monthly:
            query = "SELECT * FROM raster_metric_monthly"
        if not yearly and not monthly:
            query = "SELECT * FROM raster_metric"

        cursor.execute(query)
        rows = cursor.fetchall()
        data = {"#rows returned": len(rows), "result": rows}

    return data   

@app.get("/result/zip/{id}")
def download_zip_result(id: str):
    # get all raster file names
    log.info(f"Fetching result folder {id}")
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM raster
                WHERE folder_id = %s 
                """,
                (id, )
            )
            rows = cursor.fetchall()
        if rows:
            rasters = {row['id']: row['name'] for row in rows}
            log.debug(f"Files from folder {id}: {rasters}")
            def zip_streamer(rasters):
                with BytesIO() as buffer:
                    # Write files to zip buffer
                    with zipfile.ZipFile(buffer,'w') as zipf:
                        for raster, raster_name in rasters.items():
                            remote_dst_file = os.path.join(raster, dst)
                            if remote_fs.exists(remote_dst_file):
                                with remote_fs.open(remote_dst_file, 'rb') as remote_file:
                                    file_data = remote_file.read()
                                    zipf.writestr(raster_name, file_data)

                    # Move the pointer to the beginning of the BytesIO buffer
                    buffer.seek(0)
                    while True:
                        chunk = buffer.read(4096)
                        if not chunk:
                            break
                        yield chunk
            return StreamingResponse(zip_streamer(rasters), media_type='application/x-zip-compressed', headers={'Content-Disposition': f'attachment; filename={id}-anomaly.zip'})
        else:
            return JSONResponse(status_code = 404, content = {"error": "File not found"})
    except Exception as e:
        log.error(f"Error downloading result zip file {id}: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error downloading result zip file"})

@app.get("/source/zip/{id}")
def download_src_zip(id: str):
    # get all raster file names
    log.info(f"Fetching source folder {id}")
    try:
        with open_db_cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name
                FROM raster
                WHERE folder_id = %s 
                """,
                (id, )
            )
            rows = cursor.fetchall()
        if rows:
            rasters = {row['id']: row['name'] for row in rows}
            log.debug(f"Files from folder {id}: {rasters}")
            def zip_streamer(rasters):
                with BytesIO() as buffer:
                    # Write files to zip buffer
                    with zipfile.ZipFile(buffer,'w') as zipf:
                        for raster, raster_name in rasters.items():
                            remote_dst_file = os.path.join(raster, src)
                            if remote_fs.exists(remote_dst_file):
                                with remote_fs.open(remote_dst_file, 'rb') as remote_file:
                                    file_data = remote_file.read()
                                    zipf.writestr(raster_name, file_data)

                    # Move the pointer to the beginning of the BytesIO buffer
                    buffer.seek(0)
                    while True:
                        chunk = buffer.read(4096)
                        if not chunk:
                            break
                        yield chunk
            return StreamingResponse(zip_streamer(rasters), media_type='application/x-zip-compressed', headers={'Content-Disposition': f'attachment; filename={id}.zip'})
        else:
            return JSONResponse(status_code = 404, content = {"error": "File not found"})
    except Exception as e:
        log.error(f"Error downloading source zip file {id}: {e}")
        return JSONResponse(status_code = 500, content = {"error": "Error downloading source zip file"})



@app.get("/health")
async def service_directory():
    # TODO: Check that the worker is running and the database is available
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="public", html=True), name="public")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
