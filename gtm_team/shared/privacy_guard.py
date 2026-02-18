"""GTM privacy guard — CoS-mandated enforcement layer for marketing/commercial outputs.

Validates that GTM team outputs never:
- Contain PII patterns (email, phone, LinkedIn URL)
- Execute forbidden marketing actions (false privacy claims, real user data usage)
- Reference PII column names from the vault
- Make unsubstantiated privacy/security claims in marketing

Violations raise PrivacyViolation — a hard fail, not a warning.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII patterns that must never appear in GTM team outputs
# ---------------------------------------------------------------------------

PII_PATTERNS: list[str] = [
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
    r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # Phone
    r"\blinkedin\.com/in/[A-Za-z0-9_-]+\b",  # LinkedIn profile
]

PII_COLUMN_NAMES: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "full_name",
        "email",
        "linkedin_url",
        "current_title",
        "current_company",
        "location",
        "notes",
        "how_you_know",
        "email_blind_index",
        "name_company_blind_index",
        "raw_csv_row",
    }
)

# GTM-specific forbidden actions
FORBIDDEN_ACTIONS: list[str] = [
    "expose_user_data_in_marketing",
    "share_vault_contents",
    "claim_false_privacy",
    "use_real_user_data",
    "target_minors",
    "purchased_email_list",
    "cross_vault_claim",
    "export_pii",
]


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PrivacyViolation(Exception):
    """Raised when a GTM output violates privacy constraints."""

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
# GTMPrivacyGuard
# ---------------------------------------------------------------------------


class GTMPrivacyGuard:
    """Validates GTM team outputs against privacy and marketing constraints."""

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

    def validate_action(self, action: str, *, context: str = "") -> bool:
        """Validate that a marketing action is permitted.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        normalized = action.lower().strip()
        for forbidden in FORBIDDEN_ACTIONS:
            if forbidden in normalized:
                raise PrivacyViolation(
                    f"Forbidden marketing action: {forbidden}",
                    violation_type="forbidden_action",
                    privy_category="marketing_violation",
                    detail=f"Action: {action}",
                )
        self._log(action, context or "validate_action")
        return True

    def validate_marketing_claim(self, claim: str, *, context: str = "") -> bool:
        """Reject marketing claims that misrepresent privacy architecture.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        lower = claim.lower()
        false_claim_patterns = [
            (r"we\s+(can\s+)?see\s+(your|users?)\s+network", "claim_false_privacy"),
            (
                r"we\s+know\s+who\s+(your|their)\s+connections\s+know",
                "cross_vault_claim",
            ),
            (r"we\s+share\s+(your|user)\s+data", "claim_false_privacy"),
            (
                r"names?\s+(are|is)\s+visible\s+to\s+(job\s+seekers?|strangers?)",
                "anonymization_violation",
            ),
        ]
        for pattern, privy_cat in false_claim_patterns:
            if re.search(pattern, lower):
                raise PrivacyViolation(
                    f"False marketing claim detected: matches pattern '{pattern}'",
                    violation_type="false_marketing_claim",
                    privy_category=privy_cat,
                    detail=f"Claim: {claim[:200]}",
                )
        self._log(claim, context or "validate_marketing_claim")
        return True

    def validate_output_columns(self, column_names: list[str]) -> bool:
        """Check that output column names don't contain PII columns."""
        violations = [c for c in column_names if c.lower() in PII_COLUMN_NAMES]
        if violations:
            raise PrivacyViolation(
                f"PII columns in GTM output: {violations}",
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
                    f"PII pattern detected in GTM output: {match.group()[:20]}...",
                    violation_type="pii_in_text",
                    privy_category="pii_leak",
                    detail=f"Pattern: {pattern}",
                )

    def _check_pii_column_references(self, text: str) -> None:
        """Reject text that references PII column data as values."""
        lower = text.lower()
        for col in PII_COLUMN_NAMES:
            pattern = rf"\buser['\"]?s?\s+{re.escape(col)}\b"
            if re.search(pattern, lower):
                raise PrivacyViolation(
                    f"PII column reference '{col}' in GTM output",
                    violation_type="pii_column_reference",
                    privy_category="pii_leak",
                    detail=f"Column: {col}",
                )

    def _log(self, text: str, context: str) -> None:
        """Audit trail for validated outputs."""
        self._audit_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "context": context,
                "text_preview": text[:120].replace("\n", " "),
            }
        )
        self._audit_log = self._audit_log[-500:]


# Singleton for convenience
guard = GTMPrivacyGuard()
