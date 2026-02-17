"""Financial privacy guard — CoS-mandated enforcement layer for finance team outputs.

Validates finance team outputs against privacy and financial data constraints:
- No Stripe keys, payment method details, or customer IDs in findings
- No individual credit balances or transaction details
- PII pattern detection (emails, phones, LinkedIn URLs)
- Aggregate threshold enforcement (minimum 5 users)
- Forbidden financial actions enforcement

Violations raise PrivacyViolation — a hard fail, not a warning.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII patterns that must never appear in finance team outputs
# ---------------------------------------------------------------------------

PII_PATTERNS: list[str] = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",                          # Phone
    r"\blinkedin\.com/in/[A-Za-z0-9_-]+\b",                    # LinkedIn profile
]

# Financial-specific PII patterns
FINANCIAL_PII_PATTERNS: list[str] = [
    r"\bsk_(?:live|test)_[A-Za-z0-9]+\b",                      # Stripe secret key
    r"\bpk_(?:live|test)_[A-Za-z0-9]+\b",                      # Stripe publishable key
    r"\bwhsec_[A-Za-z0-9]+\b",                                 # Stripe webhook secret
    r"\bcus_[A-Za-z0-9]+\b",                                   # Stripe customer ID
    r"\bpm_[A-Za-z0-9]+\b",                                    # Stripe payment method ID
    r"\bpi_[A-Za-z0-9]+\b",                                    # Stripe payment intent ID
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",           # Credit card number
]

PII_COLUMN_NAMES: frozenset[str] = frozenset({
    "first_name", "last_name", "full_name", "email",
    "linkedin_url", "current_title", "current_company",
    "location", "notes", "how_you_know",
    "email_blind_index", "name_company_blind_index", "raw_csv_row",
    "stripe_customer_id", "payment_method_id",
})

# Finance-specific forbidden actions
FORBIDDEN_ACTIONS: list[str] = [
    "expose_individual_balance",
    "share_payment_details",
    "leak_stripe_keys",
    "identify_paying_users",
    "export_transaction_history",
    "expose_user_activity",
    "contact_users_directly",
]

# Minimum user count for aggregate findings
AGGREGATE_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PrivacyViolation(Exception):
    """Raised when a finance output violates privacy constraints."""

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
# FinancePrivacyGuard
# ---------------------------------------------------------------------------


class FinancePrivacyGuard:
    """Validates finance team outputs against privacy and financial data constraints."""

    def __init__(self) -> None:
        self._audit_log: list[dict[str, Any]] = []

    # -- Public API ----------------------------------------------------------

    def validate_finding(self, text: str, *, context: str = "") -> bool:
        """Validate that a finding/report text contains no PII or financial secrets.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        self._check_pii_patterns(text)
        self._check_financial_pii_patterns(text)
        self._check_pii_column_references(text)
        self._log(text, context or "validate_finding")
        return True

    def validate_action(self, action: str, *, context: str = "") -> bool:
        """Validate that a finance action is permitted.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        normalized = action.lower().strip()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in normalized:
                raise PrivacyViolation(
                    f"Forbidden finance action: {forbidden}",
                    violation_type="forbidden_action",
                    privy_category="financial_data_leak",
                    detail=f"Action: {action}",
                )
        self._log(action, context or "validate_action")
        return True

    def validate_aggregate_threshold(
        self, user_count: int, *, context: str = ""
    ) -> bool:
        """Reject findings that reference fewer than AGGREGATE_THRESHOLD users.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        if user_count < AGGREGATE_THRESHOLD:
            raise PrivacyViolation(
                f"Aggregate threshold violated: {user_count} users (minimum {AGGREGATE_THRESHOLD})",
                violation_type="aggregate_too_small",
                privy_category="individual_identification",
                detail=f"User count: {user_count}, threshold: {AGGREGATE_THRESHOLD}",
            )
        self._log(
            f"Aggregate check passed: {user_count} users",
            context or "validate_aggregate_threshold",
        )
        return True

    def validate_output_columns(self, column_names: list[str]) -> bool:
        """Check that output column names don't contain PII columns."""
        violations = [c for c in column_names if c.lower() in PII_COLUMN_NAMES]
        if violations:
            raise PrivacyViolation(
                f"PII columns in finance output: {violations}",
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
                    f"PII pattern detected in finance output: {match.group()[:20]}...",
                    violation_type="pii_in_text",
                    privy_category="pii_leak",
                    detail=f"Pattern: {pattern}",
                )

    def _check_financial_pii_patterns(self, text: str) -> None:
        """Reject text containing Stripe keys, card numbers, or customer IDs."""
        for pattern in FINANCIAL_PII_PATTERNS:
            match = re.search(pattern, text)
            if match:
                raise PrivacyViolation(
                    f"Financial PII detected in output: {match.group()[:10]}...",
                    violation_type="financial_pii_in_text",
                    privy_category="financial_data_leak",
                    detail=f"Pattern: {pattern}",
                )

    def _check_pii_column_references(self, text: str) -> None:
        """Reject text that references PII column data as values."""
        lower = text.lower()
        for col in PII_COLUMN_NAMES:
            pattern = rf"\buser['\"]?s?\s+{re.escape(col)}\b"
            if re.search(pattern, lower):
                raise PrivacyViolation(
                    f"PII column reference '{col}' in finance output",
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
guard = FinancePrivacyGuard()
