FROM python:3.10

COPY pyproject.toml constraints.txt /app/
RUN mkdir /app/src
WORKDIR /app

RUN pip install -e . -c constraints.txt
RUN pip install uvicorn gunicorn -c constraints.txt

COPY public/ /app/public/
COPY src/ /app/src/

EXPOSE 8000

CMD gunicorn anomaly.web:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 0 --log-level debug
