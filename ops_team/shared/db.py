"""Sync DB session factory for ops agents.

Wraps app.database sync session for read-only agent queries.
Returns None if DATABASE_URL is unset (graceful degradation).
"""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_session() -> Session | None:
    """Return a sync SQLAlchemy session, or None if DB is unavailable.

    Tries DATABASE_URL first (Railway internal via app.database), then
    DATABASE_PUBLIC_URL (TCP proxy for local/external access with its own engine).
    """
    db_url = os.environ.get("DATABASE_URL", "")

    # Path 1: Use app.database engine (Railway internal — fast, pooled)
    if db_url:
        try:
            from app.database import _get_sync_engine
            from sqlalchemy.orm import sessionmaker

            engine = _get_sync_engine()
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            return factory()
        except Exception as exc:
            logger.warning("ops db: could not create session via app.database: %s", exc)
            return None

    # Path 2: Use DATABASE_PUBLIC_URL directly (local/external — TCP proxy)
    public_url = os.environ.get("DATABASE_PUBLIC_URL", "")
    if public_url:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            url = public_url
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://") :]
            url = url.replace("postgresql+asyncpg://", "postgresql://")

            engine = create_engine(url, echo=False)
            factory = sessionmaker(bind=engine, expire_on_commit=False)
            return factory()
        except Exception as exc:
            logger.warning(
                "ops db: could not create session via DATABASE_PUBLIC_URL: %s", exc
            )
            return None

    logger.info("ops db: no DATABASE_URL or DATABASE_PUBLIC_URL — live checks disabled")
    return None
