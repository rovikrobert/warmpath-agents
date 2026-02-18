"""Query executor — SQL template execution engine for data team agents.

Provides sync database access for agent scan steps. All queries are
privacy-validated through PrivacyGuard before execution.

Gracefully degrades when DATABASE_URL is not set or the database is
unreachable — agents continue with code-only analysis.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cache entry: (expiry_timestamp, results)
_CacheEntry = tuple[float, list[dict[str, Any]]]

# Default cache TTL: 5 minutes (covers a single scan cycle)
DEFAULT_CACHE_TTL = 300


class QueryExecutor:
    """Execute privacy-validated SQL against the database.

    Usage::

        qe = get_executor()
        if qe.is_available():
            rows = qe.execute_template(
                "daily_signups",
                {"start_date": "2024-01-01", "end_date": "2024-02-01"},
            )
    """

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL) -> None:
        self._engine: Any = None
        self._available = False
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._query_count = 0
        self._setup()

    # -- Initialisation ------------------------------------------------------

    def _setup(self) -> None:
        """Initialize database connection from DATABASE_URL."""
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            logger.info("DATABASE_URL not set — query executor disabled")
            return

        try:
            from sqlalchemy import create_engine, text

            # Normalise URL: Railway may use postgres:// (old style)
            if db_url.startswith("postgres://"):
                db_url = "postgresql://" + db_url[len("postgres://") :]
            # Strip async driver prefix if present
            db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

            self._engine = create_engine(
                db_url,
                pool_size=2,
                max_overflow=0,
                pool_timeout=10,
                pool_recycle=300,
                echo=False,
            )
            # Test connection
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._available = True
            logger.info("Query executor connected to database")
        except Exception as exc:
            logger.warning("Query executor setup failed: %s", exc)
            self._engine = None
            self._available = False

    # -- Public API ----------------------------------------------------------

    def is_available(self) -> bool:
        """Check if database is accessible."""
        return self._available

    def execute_template(
        self, name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a named SQL template with privacy validation.

        Args:
            name: Template name from sql_templates.ALL_TEMPLATES.
            params: Query parameters (e.g. ``{"start_date": "2024-01-01"}``).

        Returns:
            List of result row dicts. Empty list on failure or if DB unavailable.
        """
        if not self._available:
            return []

        from data_team.shared.sql_templates import ALL_TEMPLATES

        sql = ALL_TEMPLATES.get(name)
        if sql is None:
            logger.warning("Unknown template: %s", name)
            return []

        return self.execute_sql(sql, params, context=f"template:{name}")

    def execute_sql(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        context: str = "",
    ) -> list[dict[str, Any]]:
        """Execute raw SQL with privacy validation.

        Every query is validated through PrivacyGuard before execution.
        Results are cached in-memory with TTL.
        """
        if not self._available:
            return []

        from data_team.shared.privacy_guard import guard

        params = params or {}

        # Privacy validation (raises PrivacyViolation on failure)
        if "group by" in sql.lower():
            guard.validate_aggregation(sql, context=context or "query_executor")
        else:
            guard.validate_query(sql, context=context or "query_executor")

        # Check cache
        cache_key = self._cache_key(sql, params)
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.time():
            return cached[1]

        # Execute
        try:
            from sqlalchemy import text

            with self._engine.connect() as conn:
                result = conn.execute(text(sql), params)
                rows = [dict(row._mapping) for row in result]

            # Validate output columns don't contain PII
            if rows:
                guard.validate_no_pii_in_output(list(rows[0].keys()))

            guard.log_query(sql, context or "query_executor")
            self._query_count += 1

            # Cache results
            self._cache[cache_key] = (time.time() + self._cache_ttl, rows)
            return rows

        except Exception as exc:
            logger.warning("Query execution failed (%s): %s", context, exc)
            return []

    @property
    def query_count(self) -> int:
        """Total queries executed (excluding cache hits)."""
        return self._query_count

    def clear_cache(self) -> None:
        """Clear the result cache."""
        self._cache.clear()

    # -- Internals -----------------------------------------------------------

    @staticmethod
    def _cache_key(sql: str, params: dict) -> str:
        raw = sql + "|" + str(sorted(params.items()))
        return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_executor: QueryExecutor | None = None


def get_executor() -> QueryExecutor:
    """Return the module-level QueryExecutor, creating it on first call."""
    global _executor
    if _executor is None:
        _executor = QueryExecutor()
    return _executor
