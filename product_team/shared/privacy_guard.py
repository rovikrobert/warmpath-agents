"""Research privacy guard — CoS-mandated enforcement layer for product team outputs.

Unlike the data team's SQL-focused guard, this validates research outputs:
- No PII columns/values in research findings
- No actual user data referenced in reports
- No external URLs constructed from user data
- Ethical research rules enforcement

Violations raise PrivacyViolation — a hard fail, not a warning.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII patterns that must never appear in product team outputs
# ---------------------------------------------------------------------------

PII_PATTERNS: list[str] = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",                          # Phone
    r"\blinkedin\.com/in/[A-Za-z0-9_-]+\b",                    # LinkedIn profile
]

PII_COLUMN_NAMES: frozenset[str] = frozenset({
    "first_name", "last_name", "full_name", "email",
    "linkedin_url", "current_title", "current_company",
    "location", "notes", "how_you_know",
    "email_blind_index", "name_company_blind_index", "raw_csv_row",
})

# Research ethics — forbidden actions
FORBIDDEN_ACTIONS: list[str] = [
    "scrape_user_data",
    "export_pii",
    "contact_users_directly",
    "share_user_data_externally",
    "construct_external_url_from_user_data",
]


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PrivacyViolation(Exception):
    """Raised when a research output violates privacy constraints."""

    def __init__(
        self,
        message: str,
        violation_type: str = "unknown",
        privy_category: str = "unknown",
        detail: str = "",
    ):
        self.violation_type = violation_type
        self.privy_category = privy_category
        self.detail = detail
        super().__init__(message)


# ---------------------------------------------------------------------------
# ProductPrivacyGuard
# ---------------------------------------------------------------------------


class ProductPrivacyGuard:
    """Validates product team research outputs against privacy constraints."""

    def __init__(self) -> None:
        self._audit_log: list[dict[str, Any]] = []

    # -- Public API ----------------------------------------------------------

    def validate_finding(self, text: str, *, context: str = "") -> bool:
        """Validate that a finding/report text contains no PII.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        self._check_pii_patterns(text)
        self._check_pii_column_references(text)
        self._log(text, context or "validate_finding")
        return True

    def validate_research_action(self, action: str, *, context: str = "") -> bool:
        """Validate that a research action is ethically permitted.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        normalized = action.lower().strip()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in normalized:
                raise PrivacyViolation(
                    f"Forbidden research action: {forbidden}",
                    violation_type="forbidden_action",
                    privy_category="pii_leak",
                    detail=f"Action: {action}",
                )
        self._log(action, context or "validate_research_action")
        return True

    def validate_output_columns(self, column_names: list[str]) -> bool:
        """Check that output column names don't contain PII columns."""
        violations = [c for c in column_names if c.lower() in PII_COLUMN_NAMES]
        if violations:
            raise PrivacyViolation(
                f"PII columns in research output: {violations}",
                violation_type="pii_in_output",
                privy_category="pii_leak",
            )
        return True

    def get_audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    # -- Internal checks -----------------------------------------------------

    def _check_pii_patterns(self, text: str) -> None:
        """Reject text containing email addresses, phone numbers, or LinkedIn URLs."""
        for pattern in PII_PATTERNS:
            match = re.search(pattern, text)
            if match:
                raise PrivacyViolation(
                    f"PII pattern detected in research output: {match.group()[:20]}...",
                    violation_type="pii_in_text",
                    privy_category="pii_leak",
                    detail=f"Pattern: {pattern}",
                )

    def _check_pii_column_references(self, text: str) -> None:
        """Reject text that references PII column data as values."""
        # Check if text contains SELECT ... PII column patterns
        lower = text.lower()
        for col in PII_COLUMN_NAMES:
            pattern = rf"\buser['\"]?s?\s+{re.escape(col)}\b"
            if re.search(pattern, lower):
                raise PrivacyViolation(
                    f"PII column reference '{col}' in research output",
                    violation_type="pii_column_reference",
                    privy_category="pii_leak",
                    detail=f"Column: {col}",
                )

    def _log(self, text: str, context: str) -> None:
        """Audit trail for validated outputs."""
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "text_preview": text[:120].replace("\n", " "),
        })
        self._audit_log = self._audit_log[-500:]


# Singleton for convenience
guard = ProductPrivacyGuard()
