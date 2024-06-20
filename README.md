# GARDS:  Geo-spatial Anomaly Recognition and Detection System

A system to assist in triaging large volumes of overhead imagery for volunteer analysts.

![](screenshot.png)

### How it works

The system scores different parts of an image on a scale from 0.0 to 1.0. Images with low scores should be ignored,
images with high scores should be prioritised for further analysis.

A large image is broken up into tiles of size 224 x 224. For each tile, we ask the system a hierarchical series of questions
that lead to an overall score. Each question is a simple multiple-choice or yes/no question about the contents of the tile.

The system relies on three large pre-trained neural networks, EVA, Flan-T5, and BLIP-2. EVA is a computer vision model
that can summarise the visual contents of an image. Flan-T5 is a large language model that can answer questions and has
a strong general-purpose understanding of every-day concepts. BLIP-2 is a bridge between the two, translating the output
of EVA into a set of tokens that can be understood by Flan-T5.

```mermaid
graph LR
    web <--> queue
    web <--> storage
    queue <--> predictor
    predictor <--> storage
    web <----> database
```

As a system, there are four main components: the web server, the predictor, the database, and the queue:
- The **web**-server is an always-on frontend for interacting with the user and compiling the results.
- The **predictor** is a GPU-accelerated service that performs the bulk of the computation, answering questions about
  each tile.
- The **queue** mediates between the services, buffering requests and allowing the system to scale out.
- The **database** indexes the results.

There may be multiple instances of the web server or the predictor.

### Using the UI

A UI is available at https://dra.az.aiml.team (or http://localhost:8000 when running locally).

The UI allows you to upload a GeoTIFF for processing and shows a list of all uploaded files.

Clicking on any file will show the results (if available) and allow you to download the .tif files.

### Using the API

An interactive API is available at http://localhost:8000/docs (or https://dra.aiml.team/docs).

The main end-point is `/submit`, which will allow you to upload a GeoTIFF for processing.

Your image will be queued until a predictor server is available to process it. Check the endpoint `/status/{id}` with
the id returned by `/submit` to see if your image has started processing yet.

Once processing is complete, you can retrieve the results from `/download/{id}`.

Result files are greyscale GeoTIFFs with a single band. The value of each pixel is the anomaly score for the corresponding
tile. This can be styled in ArcMap or QGIS to produce a heatmap.

## Getting Started

(Skip to the bottom for instructions on running the system locally.)

### Before you begin

The system relies on large, modern GPU-accelerated servers. The predictor component uses 25 GB of vRAM during operation, making it suitable only for NVidia A6000, A100, or H100 systems. This hardware can be expensive to provision, so the system is designed to allow the predictor to scale-to-zero when not in use.

| Hardware                       | Typical cost   |
|--------------------------------|----------------|
| 1x A100 GPU-accelerated server | $5.00 per hour |
| 1x Web server (40GB)           | $0.80 per hour |
| Storage                        | $0.10 per GB per month |

A large (1.5 GB) image will take about 2 hours. A single web server + predictor pair can process only one image at a time.


### Running on Kubernetes

If you don't already have a Kubernetes cluster, we recommend using a managed service such as Google Kubernetes Engine (with Autopilot) or Azure Kubernetes Service.

You will find an example spec of the resources required to run the system on Kubernetes in the
[`deploy.k8s.yml`](./-/blob/main/deploy.k8s.yml) file. The file will need to be updated to suit your environment.

First, build and publish the Docker images:

```bash
docker build -t my.repo/anomaly/web:latest web
docker built -t my.repo/anomaly/predictor:latest predictor
```

Update `deploy.k8s.yml` to use the new image names in your repository.

Add any configuration needed to ensure that the predictor service will be deployed on an A100 node.
On GKE, this is achieved with the `cloud.google.com/gke-accelerator` annotation.

Update the `REMOTE_FS` variables in `deploy.k8s.yml` to point to your storage bucket (e.g. `gs://my-bucket/data` or `azblobv2://me:key@my-container`)

Next, [install KEDA with Helm](https://keda.sh/docs/2.10/deploy/#helm).

Next, [install Nginx Ingress with Helm](https://kubernetes.github.io/ingress-nginx/deploy/#quick-start)

Configure your DNS to point to the Ingress controller, and update the hostnames in `deploy.k8s.yml` to match.

Finally, deploy the application. Before deploying, ensure you have a valid Azure paid subscription. 

This needs to be done in three stages. Before you start the deployment login to both gcloud and Azure CLI.

First, the Azure Cluster:

```bash
cd terraform/azure
terraform init
terraform plan -out plan
terraform apply plan
```

Then the Services:

```bash
cd terraform/app
terraform init
terraform plan -out plan
terraform apply plan
```

Then apply application configurations:

(But first, you will need to use kubefwd to create a route to the app namespace)

```shell
cd app
terraform init
terraform plan -out plan
terraform apply plan
```

### Running on DPC
To deploy the application to DPC, follow the steps below. More detailed information can be found in the deployment folder [here](./deployment/). 

Deploy application on DPC

```shell
cd deployment
chmod +x deploy_resources.sh
./deploy_resources.sh
```

### Running Locally (for development)

You will need a development machine with a large GPU, such as an A6000.

For each of the `web` and `predictor` directories, create a Python 3.10 environment (using `venv` or `conda`) and install the dependencies:

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```bash
cd predictor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You will need access to Google Cloud Storage to store the uploaded images and the results. You can set up access using the [gcloud](https://cloud.google.com/sdk/docs/install) command line tool.

    gcloud init --project aiml-dra-anomaly


To start the application, you will need to run four processes, the database, the web server, the queue, and the predictor.

Each of the processes can be run locally with their individual Docker Compose files:

```bash
cd queue
docker compose up
```

```bash
cd db
docker compose up
```

This is useful when running the web and predictor services in the debugger.

If you just want to run the system all together, you can use the main `docker-compose.yml` file in the root directory:

```bash
docker compose up
```

You can test the server's API endpoints at http://localhost:8000/docs.

## Development Tips

### Update Constraints

Update the `constraints.txt` file to match the currently installed packages so that your environment is reproducable:

```bash
pip freeze --exclude-editable > constraints.txt
```

## Future Work

As a service, more work is needed to introduce user and data management, security hardening, and resiliance to failure.

As a triage tool, more work is needed to refine the decision tree to ensure that images are being given appropriate scores, and to test its effectiveness on a broader range of images.

As a product, a review is needed of all of the third party components, the codebase needs to be clarified to allow for ongoing maintenance and improvements, and more work is needed to reduce the operating costs of the system.

As research, more work is needed to establish a system to fine tune the behaviour of the system and allow it to detect subtler evidence of damage, such as miscoloured roofing or misplaced livestock.


## Previous Work

Previously, we built an anomaly detection tool using visual similarity, as learned by a self-supervised Barlow Twins model. Unfortunately, anomalies detected by that model tended to be uninteresting (patterns in grass) or semantically inconsistent (water closer to grass than other water).  That work has been archived under the [`archive/visualanomaly`](./-/tree/archive/visualanomaly) tag.

## License

For Disaster Relief Australia use only. Subject to The Agreement.