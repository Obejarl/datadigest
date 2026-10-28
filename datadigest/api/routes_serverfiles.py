"""Register a file that is already on the server (see datadigest/serverfiles.py)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from datadigest import serverfiles
from datadigest.api.deps import get_redis
from datadigest.api.routes_datasets import schedule
from datadigest.api.schemas import DatasetOut
from datadigest.config import Settings, get_settings
from datadigest.core.spark_profile import spark_available
from datadigest.db import get_db, get_session_factory
from datadigest.models import Dataset

router = APIRouter(prefix="/api/server-files", tags=["server files"])


class ServerFileOut(BaseModel):
    name: str
    size_bytes: int


class ServerFilesOut(BaseModel):
    enabled: bool
    spark: bool  # whether this process can run the Spark engine (workers may differ in Redis mode)
    files: list[ServerFileOut]


@router.get("", response_model=ServerFilesOut)
def list_server_files(settings: Settings = Depends(get_settings)):
    return ServerFilesOut(
        enabled=serverfiles.root(settings) is not None,
        spark=spark_available(),
        files=[ServerFileOut(name=n, size_bytes=s) for n, s in serverfiles.list_files(settings)],
    )


@router.post("/{name}", response_model=DatasetOut, status_code=status.HTTP_202_ACCEPTED)
def register_server_file(
    name: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    factory: sessionmaker = Depends(get_session_factory),
    redis: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    try:
        path = serverfiles.resolve(name, settings)
    except serverfiles.ServerFileError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    dataset = Dataset(
        name=path.stem[:255], filename=name[:255], size_bytes=serverfiles.size_of(path), source_path=name
    )
    db.add(dataset)
    db.commit()
    schedule(dataset.id, background, factory, redis, settings)
    return dataset
