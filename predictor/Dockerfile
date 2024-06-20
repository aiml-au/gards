FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

COPY pyproject.toml constraints.txt /app/
RUN mkdir /app/src
WORKDIR /app

RUN pip install --upgrade pip

RUN pip install -e . -c constraints.txt

COPY src/ /app/src/
RUN mkdir /app/data
COPY data/*.yml /app/data/

CMD python -m anomaly.predictor
