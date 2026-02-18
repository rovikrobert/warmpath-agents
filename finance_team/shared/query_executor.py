"""Finance query executor — thin wrapper around data_team QueryExecutor.

Provides finance-specific template lookup from FINANCE_TEMPLATES and
delegates all SQL execution + privacy validation to the data_team executor.

Gracefully degrades when DATABASE_URL is not set — returns empty lists so
agents can continue with code-only analysis.
"""

from __future__ import annotations

import logging
from typing import Any

from finance_team.shared.sql_templates import FINANCE_TEMPLATES

logger = logging.getLogger(__name__)


class FinanceQueryExecutor:
    """Execute finance SQL templates via the data_team QueryExecutor.

    Usage::

        qe = get_finance_executor()
        rows = qe.query_template("credit_balances", {"start_date": "2024-01-01"})
    """

    def __init__(self) -> None:
        self._delegate: Any = None
        self._init_delegate()

    def _init_delegate(self) -> None:
        """Lazy-init the data_team QueryExecutor."""
        try:
            from data_team.shared.query_executor import get_executor

            self._delegate = get_executor()
        except Exception as exc:
            logger.warning("Could not initialise data_team executor: %s", exc)
            self._delegate = None

    def is_available(self) -> bool:
        """Check if the underlying database connection is accessible."""
        if self._delegate is None:
            return False
        return self._delegate.is_available()

    def query_template(
        self, name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Look up a finance SQL template by name and execute it.

        Args:
            name: Template name from FINANCE_TEMPLATES.
            params: Query parameters (e.g. ``{"start_date": "2024-01-01"}``).

        Returns:
            List of result row dicts.  Empty list on failure, unknown template,
            or if the database is unavailable.
        """
        sql = FINANCE_TEMPLATES.get(name)
        if sql is None:
            logger.warning("Unknown finance template: %s", name)
            return []

        if self._delegate is None or not self._delegate.is_available():
            return []

        return self._delegate.execute_sql(
            sql, params, context=f"finance_template:{name}"
        )

    def execute_raw(
        self, sql: str, params: dict[str, Any] | None = None, *, context: str = ""
    ) -> list[dict[str, Any]]:
        """Execute arbitrary SQL through the data_team privacy layer.

        Use sparingly — prefer named templates for auditability.
        """
        if self._delegate is None or not self._delegate.is_available():
            return []

        return self._delegate.execute_sql(sql, params, context=context or "finance_raw")


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_executor: FinanceQueryExecutor | None = None


def get_finance_executor() -> FinanceQueryExecutor:
    """Return the module-level FinanceQueryExecutor (singleton)."""
    global _executor  # noqa: PLW0603
    if _executor is None:
        _executor = FinanceQueryExecutor()
    return _executor
