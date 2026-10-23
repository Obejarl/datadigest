from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from datadigest.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str, **kwargs) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True, **kwargs)

    engine = create_engine(url, connect_args={"check_same_thread": False}, **kwargs)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        # SQLite ignores FOREIGN KEY / ON DELETE CASCADE unless asked; PostgreSQL always enforces them.
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session_factory() -> sessionmaker:
    """Background jobs need to open their own sessions, so routes depend on the factory."""
    return SessionLocal


def get_db(factory: sessionmaker = Depends(get_session_factory)) -> Iterator[Session]:
    with factory() as db:
        yield db
