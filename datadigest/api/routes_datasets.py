import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import HTMLResponse
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker, undefer

from datadigest import jobqueue
from datadigest.api.deps import get_redis
from datadigest.api.schemas import DatasetOut
from datadigest.config import Settings, get_settings
from datadigest.core.charts import build_charts
from datadigest.core.report import render_report
from datadigest.db import get_db, get_session_factory
from datadigest.jobs import process_dataset
from datadigest.models import Dataset, DatasetFile, Status

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

ALLOWED_EXTENSIONS = (".csv", ".tsv", ".txt")
CHUNK = 1024 * 1024


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read in chunks and stop as soon as the limit is crossed, instead of loading any size into memory."""
    data = bytearray()
    while chunk := await upload.read(CHUNK):
        data.extend(chunk)
        if len(data) > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {limit // CHUNK} MB"
            )
    return bytes(data)


def _get(db: Session, dataset_id: uuid.UUID, with_profile: bool = False) -> Dataset:
    query = select(Dataset).where(Dataset.id == dataset_id)
    if with_profile:
        query = query.options(undefer(Dataset.profile))
    dataset = db.scalars(query).first()
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    return dataset


def _profile_or_409(dataset: Dataset) -> dict:
    if dataset.status != Status.DONE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Dataset is {dataset.status}, not done")
    return dataset.profile


@router.post("", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_dataset(
    file: UploadFile,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    factory: sessionmaker = Depends(get_session_factory),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    filename = file.filename or "upload.csv"
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a .csv, .tsv or .txt file")
    content = await _read_limited(file, settings.max_upload_bytes)
    if not content.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")

    dataset = Dataset(name=filename.rsplit(".", 1)[0][:255], filename=filename[:255], size_bytes=len(content))
    dataset.file = DatasetFile(content=content)
    db.add(dataset)
    db.commit()

    # 202 Accepted: the work happens after the response, the client polls GET /{id}.
    if redis is not None:
        jobqueue.enqueue(redis, settings.queue_name, dataset.id)
    else:
        background.add_task(process_dataset, dataset.id, factory)
    return dataset


@router.get("", response_model=list[DatasetOut])
def list_datasets(limit: int = 50, db: Session = Depends(get_db)):
    query = select(Dataset).order_by(Dataset.created_at.desc()).limit(min(max(limit, 1), 200))
    return db.scalars(query).all()


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(dataset_id: uuid.UUID, db: Session = Depends(get_db)):
    return _get(db, dataset_id)


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    return _profile_or_409(_get(db, dataset_id, with_profile=True))


@router.get("/{dataset_id}/charts")
def get_charts(dataset_id: uuid.UUID, db: Session = Depends(get_db)) -> list[dict]:
    return build_charts(_profile_or_409(_get(db, dataset_id, with_profile=True)))


@router.get("/{dataset_id}/report", response_class=HTMLResponse)
def get_report(dataset_id: uuid.UUID, download: bool = False, db: Session = Depends(get_db)):
    dataset = _get(db, dataset_id, with_profile=True)
    html = render_report(_profile_or_409(dataset), title=dataset.filename)
    headers = {}
    if download:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", dataset.name) or "dataset"
        headers["Content-Disposition"] = f'attachment; filename="{safe}-report.html"'
    return HTMLResponse(html, headers=headers)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: uuid.UUID, db: Session = Depends(get_db)):
    db.delete(_get(db, dataset_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
