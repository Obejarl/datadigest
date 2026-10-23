# ---- build stage: compile wheels with the full toolchain available ----------
FROM python:3.13-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ---- runtime stage: only the installed packages and our code ---------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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
