FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/neuro-inc/app-bifrost"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && useradd -m -d /app app

WORKDIR /app

COPY README.md poetry.lock pyproject.toml .
RUN pip --no-cache-dir install poetry && poetry install --no-root --no-cache

COPY .apolo .apolo
RUN poetry install --only-root --no-cache \
    && chown -R app:app /app

USER app

ENTRYPOINT ["app-types"]
