# ---- build stage: compile wheels with the full toolchain available ----------
FROM python:3.13-slim AS builder
# pip runs as root only while building the image; the app itself runs as a non-root user.
ENV PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- runtime stage: only the installed packages and our code ---------------
FROM python:3.13-slim AS runtime
# Links the published image to this repository on ghcr.io.
LABEL org.opencontainers.image.source="https://github.com/Obejarl/datadigest"       org.opencontainers.image.description="Upload a CSV: data-quality profile, plus operations-research optimizers"       org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY alembic.ini .
COPY migrations ./migrations
COPY datadigest ./datadigest
COPY samples/*.csv ./samples/

USER app
EXPOSE 8000

# One image, four roles. The default is the API; override the command for the others:
#   worker:  python -m datadigest.worker
#   migrate: alembic upgrade head
#   cleanup: python -m datadigest.cleanup
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1
CMD ["uvicorn", "datadigest.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- spark variant: the same image plus a Java runtime and pyspark ----------
# Build with `--target spark`. It is a separate target because the JRE and pyspark add several
# hundred MB that the API and the normal workers never need. Use it for workers that profile
# files from LARGE_DATA_DIR.
FROM runtime AS spark
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-spark.txt ./
RUN pip install --no-cache-dir -r requirements-spark.txt && rm requirements.txt requirements-spark.txt
USER app

# ---- default target: a plain `docker build .` builds the last stage, so keep this one last ----
FROM runtime
