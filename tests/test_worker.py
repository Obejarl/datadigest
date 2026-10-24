import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from datadigest import jobqueue
from datadigest.cleanup import delete_older_than
from datadigest.jobs import process_dataset
from datadigest.models import Dataset, DatasetFile, Status, utcnow
from datadigest.worker import Worker
from tests.conftest import upload

QUEUE = "datadigest:jobs"


def test_queue_is_fifo_and_carries_the_job_kind(redis):
    a, b = uuid.uuid4(), uuid.uuid4()
    jobqueue.enqueue(redis, QUEUE, a)
    jobqueue.enqueue(redis, QUEUE, b, kind="optimization")
    assert jobqueue.depth(redis, QUEUE) == 2
    first, second = jobqueue.dequeue(redis, QUEUE, timeout=1), jobqueue.dequeue(redis, QUEUE, timeout=1)
    assert (first.kind, first.id) == ("dataset", a)
    assert (second.kind, second.id) == ("optimization", b)


def test_queue_reads_bare_ids_from_older_versions(redis):
    a = uuid.uuid4()
    redis.lpush(QUEUE, str(a))
    job = jobqueue.dequeue(redis, QUEUE, timeout=1)
    assert (job.kind, job.id) == ("dataset", a)


def test_worker_processes_queued_upload(queued_client, redis, factory):
    dataset_id = upload(queued_client).json()["id"]
    worker = Worker(redis, factory, QUEUE)

    assert worker.run_once(timeout=1) is True
    assert queued_client.get(f"/api/datasets/{dataset_id}").json()["status"] == "done"
    assert worker.run_once(timeout=1) is False  # queue is empty now


def test_worker_marks_bad_file_failed(queued_client, redis, factory):
    dataset_id = upload(queued_client, "bad.csv", b"\x00\x01;;\n").json()["id"]
    Worker(redis, factory, QUEUE).run_once(timeout=1)
    dataset = queued_client.get(f"/api/datasets/{dataset_id}").json()
    assert dataset["status"] == "failed"
    assert dataset["error"]


def test_job_for_deleted_dataset_is_skipped(factory):
    assert process_dataset(uuid.uuid4(), factory) is None


def test_stop_ends_run_forever(redis, factory):
    worker = Worker(redis, factory, QUEUE)
    worker.stop()
    worker.run_forever()  # returns immediately instead of blocking


def _add(factory, age_days: int) -> uuid.UUID:
    with factory() as db:
        dataset = Dataset(
            name="x",
            filename="x.csv",
            size_bytes=1,
            status=Status.DONE,
            created_at=utcnow() - timedelta(days=age_days),
        )
        dataset.file = DatasetFile(content=b"a\n1\n")
        db.add(dataset)
        db.commit()
        return dataset.id


def test_cleanup_deletes_only_old_datasets(factory):
    old, fresh = _add(factory, age_days=10), _add(factory, age_days=1)
    assert delete_older_than(factory, days=7) == 1
    with factory() as db:
        assert db.get(Dataset, old) is None
        assert db.get(Dataset, fresh) is not None
        assert db.scalar(select(func.count()).select_from(DatasetFile)) == 1


def test_fail_stuck_marks_old_pending_jobs(factory):
    from datadigest.cleanup import STUCK_MESSAGE, fail_stuck

    def add(status, minutes_ago):
        with factory() as db:
            ds = Dataset(
                name="x",
                filename="x.csv",
                size_bytes=1,
                status=status,
                queued_at=utcnow() - timedelta(minutes=minutes_ago),
            )
            ds.file = DatasetFile(content=b"a\n1\n")
            db.add(ds)
            db.commit()
            return ds.id

    stuck_processing = add(Status.PROCESSING, 60)
    stuck_queued = add(Status.QUEUED, 60)
    fresh = add(Status.PROCESSING, 1)
    old_done = add(Status.DONE, 600)

    assert fail_stuck(factory, minutes=15) == 2
    with factory() as db:
        for dataset_id in (stuck_processing, stuck_queued):
            ds = db.get(Dataset, dataset_id)
            assert (ds.status, ds.error) == (Status.FAILED, STUCK_MESSAGE)
        assert db.get(Dataset, fresh).status == Status.PROCESSING
        assert db.get(Dataset, old_done).status == Status.DONE


def test_worker_waits_out_outages_with_backoff_instead_of_crashing(factory):
    from redis.exceptions import ConnectionError as RedisConnectionError

    class FlakyRedis:
        """Fails three times (Redis still starting), then the test stops the worker."""

        def __init__(self):
            self.calls = 0

        def blmove(self, src, dst, timeout, wherefrom, whereto):
            self.calls += 1
            if self.calls <= 3:
                raise RedisConnectionError("connection refused")
            worker.stop()
            return None

    waits = []
    worker = Worker(FlakyRedis(), factory, QUEUE, housekeeping_seconds=None)
    worker.run_forever(sleep=waits.append)
    assert waits == [1.0, 2.0, 4.0]  # exponential backoff, and the loop survived


def test_backoff_is_capped(factory):
    from redis.exceptions import ConnectionError as RedisConnectionError

    from datadigest.worker import MAX_BACKOFF_SECONDS

    class DownRedis:
        def __init__(self):
            self.calls = 0

        def blmove(self, src, dst, timeout, wherefrom, whereto):
            self.calls += 1
            if self.calls > 8:
                worker.stop()
                return None
            raise RedisConnectionError("down")

    waits = []
    worker = Worker(DownRedis(), factory, QUEUE, housekeeping_seconds=None)
    worker.run_forever(sleep=waits.append)
    assert max(waits) == MAX_BACKOFF_SECONDS


# --- reliable queue: ack, visibility timeout, retries, dead letter -----------------


def test_taken_job_moves_to_processing_until_acked(redis):
    job_id = uuid.uuid4()
    jobqueue.enqueue(redis, QUEUE, job_id)
    job = jobqueue.dequeue(redis, QUEUE, timeout=1)
    assert jobqueue.stats(redis, QUEUE) == {"pending": 0, "in_flight": 1, "dead": 0}
    jobqueue.ack(redis, QUEUE, job)
    assert jobqueue.stats(redis, QUEUE) == {"pending": 0, "in_flight": 0, "dead": 0}


def test_job_of_a_vanished_worker_comes_back_after_the_visibility_timeout(redis):
    job_id = uuid.uuid4()
    jobqueue.enqueue(redis, QUEUE, job_id)
    jobqueue.dequeue(redis, QUEUE, timeout=1, now=1000.0)  # the worker dies without acking

    assert jobqueue.requeue_stale(redis, QUEUE, 120, 3, now=1100.0) == ([], [])  # still within 120 s
    requeued, dead = jobqueue.requeue_stale(redis, QUEUE, 120, 3, now=1200.0)
    assert [j.id for j in requeued] == [job_id] and dead == []
    again = jobqueue.dequeue(redis, QUEUE, timeout=1)
    assert again.id == job_id and again.attempts == 2


def test_two_workers_cannot_requeue_the_same_job_twice(redis):
    jobqueue.enqueue(redis, QUEUE, uuid.uuid4())
    jobqueue.dequeue(redis, QUEUE, timeout=1, now=0.0)
    first = jobqueue.requeue_stale(redis, QUEUE, 10, 3, now=100.0)
    second = jobqueue.requeue_stale(redis, QUEUE, 10, 3, now=100.0)
    assert len(first[0]) == 1 and second == ([], [])
    assert jobqueue.depth(redis, QUEUE) == 1


def test_a_job_that_keeps_dying_goes_to_the_dead_letter_list(redis):
    job_id = uuid.uuid4()
    jobqueue.enqueue(redis, QUEUE, job_id)
    for attempt in range(3):
        jobqueue.dequeue(redis, QUEUE, timeout=1, now=float(attempt * 1000))
        requeued, dead = jobqueue.requeue_stale(redis, QUEUE, 10, 3, now=float(attempt * 1000 + 100))
    assert requeued == [] and [j.id for j in dead] == [job_id]
    assert jobqueue.stats(redis, QUEUE) == {"pending": 0, "in_flight": 0, "dead": 1}


def test_crashing_handler_is_retried_then_succeeds(queued_client, redis, factory, monkeypatch):
    import datadigest.worker as worker_module

    dataset_id = upload(queued_client).json()["id"]
    real = worker_module.HANDLERS["dataset"]
    calls = []

    def flaky(job_id, f):
        calls.append(job_id)
        if len(calls) == 1:
            raise RuntimeError("worker hit a bug")  # not acked
        return real(job_id, f)

    monkeypatch.setitem(worker_module.HANDLERS, "dataset", flaky)
    worker = Worker(redis, factory, QUEUE, visibility_seconds=0)
    assert worker.run_once(timeout=1)
    assert jobqueue.stats(redis, QUEUE)["in_flight"] == 1  # still owned, not lost
    time.sleep(0.01)
    requeued, _ = worker.housekeeping()
    assert len(requeued) == 1
    assert worker.run_once(timeout=1)
    assert queued_client.get(f"/api/datasets/{dataset_id}").json()["status"] == "done"
    assert jobqueue.stats(redis, QUEUE) == {"pending": 0, "in_flight": 0, "dead": 0}


def test_dead_job_is_marked_failed_for_the_user(queued_client, redis, factory, monkeypatch):
    import datadigest.worker as worker_module

    dataset_id = upload(queued_client).json()["id"]
    monkeypatch.setitem(
        worker_module.HANDLERS, "dataset", lambda *_: (_ for _ in ()).throw(RuntimeError("bug"))
    )
    worker = Worker(redis, factory, QUEUE, visibility_seconds=0, max_attempts=2)
    for _ in range(2):
        worker.run_once(timeout=1)
        time.sleep(0.01)
        worker.housekeeping()
    dataset = queued_client.get(f"/api/datasets/{dataset_id}").json()
    assert dataset["status"] == "failed"
    assert "failed 2 times" in dataset["error"]
    assert jobqueue.stats(redis, QUEUE)["dead"] == 1
