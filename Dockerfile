FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/jobtracker

COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
COPY bot ./bot
COPY worker ./worker
COPY scripts ./scripts
RUN pip install --no-cache-dir --no-deps . \
    && useradd --create-home tracker \
    && mkdir -p /srv/jobtracker/data \
    && chown tracker:tracker /srv/jobtracker/data

USER tracker
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
