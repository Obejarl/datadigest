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
    assert jobqueue.dequeue(redis, QUEUE, timeout=1) == ("dataset", a)
    assert jobqueue.dequeue(redis, QUEUE, timeout=1) == ("optimization", b)


def test_queue_reads_bare_ids_from_older_versions(redis):
    a = uuid.uuid4()
    redis.lpush(QUEUE, str(a))
    assert jobqueue.dequeue(redis, QUEUE, timeout=1) == ("dataset", a)


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
