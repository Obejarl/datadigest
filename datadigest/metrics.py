"""Prometheus metrics shared by the API and the workers.

The API serves them at /metrics; each worker serves its own on WORKER_METRICS_PORT
(Prometheus scrapes every replica, then sums). Names follow Prometheus conventions:
a datadigest_ prefix, base units (seconds), _total for counters.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

JOB_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)

HTTP_REQUESTS = Counter(
    "datadigest_http_requests_total", "HTTP requests handled by the API", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "datadigest_http_request_duration_seconds",
    "Time to answer an HTTP request",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
JOBS = Counter("datadigest_jobs_total", "Jobs processed", ["kind", "status"])
JOB_DURATION = Histogram(
    "datadigest_job_duration_seconds", "Time spent processing one job", ["kind"], buckets=JOB_BUCKETS
)
JOB_WAIT = Histogram(
    "datadigest_job_queue_wait_seconds",
    "Time a job waited in the queue before a worker took it",
    ["kind"],
    buckets=JOB_BUCKETS,
)
REQUEUED = Counter(
    "datadigest_jobs_requeued_total", "Jobs given back to the queue after their worker vanished"
)
DEAD = Counter("datadigest_jobs_dead_total", "Jobs parked in the dead-letter list after too many attempts")
CRASHES = Counter("datadigest_job_crashes_total", "Jobs whose handler raised; they will be retried")
BACKOFFS = Counter("datadigest_worker_backoffs_total", "Times a worker waited for Redis or PostgreSQL")

QUEUE = Gauge("datadigest_queue_jobs", "Jobs in the Redis queue", ["state"])  # pending / in_flight / dead
DATASETS = Gauge("datadigest_datasets", "Datasets by status", ["status"])
OPTIMIZATIONS = Gauge("datadigest_optimizations", "Optimization runs by status", ["status"])
