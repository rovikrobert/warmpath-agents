from collections.abc import AsyncGenerator, Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def _pool_kwargs(url: str) -> dict:
    """Return connection-pool settings for PostgreSQL; empty dict for SQLite."""
    if url.startswith("sqlite"):
        return {}
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_pre_ping": True,
    }


@lru_cache
def _get_engine():
    # Swap driver for async: postgresql:// → postgresql+asyncpg://
    url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    return create_async_engine(url, echo=False, **_pool_kwargs(url))


@lru_cache
def _get_session_factory():
    return async_sessionmaker(
        _get_engine(), class_=AsyncSession, expire_on_commit=False
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with _get_session_factory()() as session:
        yield session


# ---------------------------------------------------------------------------
# Sync engine + session — for Celery workers
# ---------------------------------------------------------------------------


@lru_cache
def _get_sync_engine():
    url = settings.DATABASE_URL
    # Ensure we use the psycopg2 sync driver
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, echo=False, **_pool_kwargs(url))


@lru_cache
def _get_sync_session_factory():
    return sessionmaker(bind=_get_sync_engine(), expire_on_commit=False)


def get_sync_db() -> Generator[Session, None, None]:
    """Yield a sync session for Celery workers."""
    session = _get_sync_session_factory()()
    try:
        yield session
    finally:
        session.close()
