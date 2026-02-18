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

    Tries DATABASE_URL first (Railway internal), then DATABASE_PUBLIC_URL
    (TCP proxy for local/external access).
    """
    db_url = os.environ.get("DATABASE_URL", "") or os.environ.get(
        "DATABASE_PUBLIC_URL", ""
    )
    if not db_url:
        logger.info("ops db: no DATABASE_URL or DATABASE_PUBLIC_URL — live checks disabled")
        return None
    try:
        from app.database import _get_sync_engine
        from sqlalchemy.orm import sessionmaker

        engine = _get_sync_engine()
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        return factory()
    except Exception as exc:
        logger.warning("ops db: could not create session: %s", exc)
        return None
