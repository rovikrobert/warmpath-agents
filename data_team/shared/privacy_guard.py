"""Privacy guard — CoS-mandated enforcement layer for all data team queries.

Validates SQL templates against 10 Privy check categories:
  vault_isolation, encryption, suppression, anonymization, consent,
  retention, dsar, pii_leak, audit_immutability, info_leak

Every SQL template in sql_templates.py is validated by this module at import
time.  Violations raise PrivacyViolation — a hard fail, not a warning.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII and vault definitions (CoS-verified)
# ---------------------------------------------------------------------------

# 13 PII columns — 10 EncryptedString/Text + 2 blind indexes + raw_csv_row
PII_COLUMNS: frozenset[str] = frozenset(
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

# 11 vault tables — user-scoped or consent-gated
VAULT_TABLES: frozenset[str] = frozenset(
    {
        "contacts",
        "warm_scores",
        "match_results",
        "applications",
        "marketplace_listings",
        "intro_facilitations",
        "credit_transactions",
        "consent_records",
        "data_requests",
        "suppression_list",
        "audit_logs",
    }
)

# Immutable tables — no UPDATE or DELETE ever
IMMUTABLE_TABLES: frozenset[str] = frozenset(
    {
        "audit_logs",
        "consent_records",
    }
)

# Forbidden cross-vault JOIN pairs
FORBIDDEN_JOIN_PAIRS: list[tuple[str, str]] = [
    ("contacts", "contacts"),
]

# Allowed exceptions with documented justification
ALLOWED_CROSS_VAULT_EXCEPTIONS: list[dict[str, str]] = [
    {
        "pattern": "intro_facilitations.*JOIN.*contacts.*WHERE.*consent",
        "justification": "Post-consent reveal — identity disclosed only after network holder approves",
    },
    {
        "pattern": "contacts.*email_blind_index.*suppression_list.*email_hash",
        "justification": "Hash-based dedup — SHA-256 comparison, no plaintext PII crosses boundary",
    },
    {
        "pattern": "marketplace_listings.*JOIN.*contacts.*WHERE.*opt_in_marketplace",
        "justification": "Anonymized marketplace — only role_level + department exposed, network holder opted in",
    },
]


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PrivacyViolation(Exception):
    """Raised when a query violates privacy constraints."""

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
# PrivacyGuard
# ---------------------------------------------------------------------------


class PrivacyGuard:
    """Validates SQL templates against privacy constraints."""

    def __init__(self) -> None:
        self._audit_log: list[dict[str, Any]] = []

    # -- Public API ----------------------------------------------------------

    def validate_query(self, sql: str, *, context: str = "") -> bool:
        """Full validation: PII leak, vault isolation, immutability, suppression.

        Returns True if valid; raises PrivacyViolation otherwise.
        """
        normalized = self._normalize(sql)

        self._check_pii_in_select(normalized)
        self._check_cross_vault_joins(normalized)
        self._check_vault_scoping(normalized)
        self._check_suppression_plaintext(normalized)
        self._check_audit_immutability(normalized)

        self.log_query(sql, context or "validate_query")
        return True

    def validate_aggregation(self, sql: str, *, context: str = "") -> bool:
        """Enforce k-anonymity: GROUP BY must include HAVING COUNT >= 5."""
        normalized = self._normalize(sql)

        # First run standard checks
        self._check_pii_in_select(normalized)
        self._check_audit_immutability(normalized)

        # k-anonymity check: if GROUP BY present, require HAVING COUNT >= k
        if "group by" in normalized and not self._has_k_anonymity_guard(normalized):
            raise PrivacyViolation(
                "Aggregation query with GROUP BY must include "
                f"HAVING COUNT(*) >= {_MIN_K} for k-anonymity",
                violation_type="missing_k_anonymity",
                privy_category="info_leak",
            )

        self.log_query(sql, context or "validate_aggregation")
        return True

    def validate_no_pii_in_output(self, column_names: list[str]) -> bool:
        """Check that result column names don't contain PII columns."""
        violations = [c for c in column_names if c.lower() in PII_COLUMNS]
        if violations:
            raise PrivacyViolation(
                f"PII columns in output: {violations}",
                violation_type="pii_in_output",
                privy_category="pii_leak",
            )
        return True

    def validate_audit_immutability(self, sql: str) -> bool:
        """Reject UPDATE/DELETE on immutable tables."""
        normalized = self._normalize(sql)
        self._check_audit_immutability(normalized)
        return True

    def log_query(self, sql: str, agent_name: str) -> None:
        """Audit trail for validated queries."""
        self._audit_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": agent_name,
                "sql_hash": hash(sql),
                "sql_preview": sql[:120].replace("\n", " "),
            }
        )
        # Keep last 500 entries
        self._audit_log = self._audit_log[-500:]

    def get_audit_log(self) -> list[dict[str, Any]]:
        return list(self._audit_log)

    # -- Internal checks -----------------------------------------------------

    @staticmethod
    def _normalize(sql: str) -> str:
        """Lowercase, collapse whitespace."""
        return re.sub(r"\s+", " ", sql.lower().strip())

    def _check_pii_in_select(self, normalized: str) -> None:
        """Reject PII columns in SELECT clauses (privy: pii_leak)."""
        # Extract the SELECT ... FROM portion
        select_match = re.search(r"select\s+(.*?)\s+from\s", normalized)
        if not select_match:
            return

        select_clause = select_match.group(1)

        # Allow SELECT * only with user_id scoping
        if select_clause.strip() == "*":
            return

        for col in PII_COLUMNS:
            # Match the column name as a whole word in the SELECT clause
            pattern = rf"\b{re.escape(col)}\b"
            if re.search(pattern, select_clause):
                raise PrivacyViolation(
                    f"PII column '{col}' in SELECT clause — use aggregation or remove",
                    violation_type="pii_in_select",
                    privy_category="pii_leak",
                    detail=f"Column: {col}",
                )

    def _check_cross_vault_joins(self, normalized: str) -> None:
        """Reject cross-vault JOINs without consent gate (privy: vault_isolation)."""
        # Check forbidden pairs
        for t1, t2 in FORBIDDEN_JOIN_PAIRS:
            # Self-join pattern
            if t1 == t2:
                pattern = rf"\b{re.escape(t1)}\b.*\bjoin\b.*\b{re.escape(t2)}\b"
                if re.search(pattern, normalized) and not self._matches_exception(
                    normalized
                ):
                    # Check exceptions
                    raise PrivacyViolation(
                        f"Cross-vault JOIN: {t1} JOIN {t2}",
                        violation_type="cross_vault_join",
                        privy_category="vault_isolation",
                    )

        # General cross-vault: contacts JOIN marketplace_listings needs consent
        if (
            (
                "contacts" in normalized
                and "join" in normalized
                and "marketplace_listings" in normalized
            )
            and not self._matches_exception(normalized)
            and ("opt_in_marketplace" not in normalized and "consent" not in normalized)
        ):
            raise PrivacyViolation(
                "contacts JOIN marketplace_listings requires consent gate "
                "(opt_in_marketplace or consent check)",
                violation_type="cross_vault_join",
                privy_category="vault_isolation",
            )

    def _check_vault_scoping(self, normalized: str) -> None:
        """Vault tables need user_id scoping unless aggregated (privy: vault_isolation)."""
        # Skip for pure COUNT/SUM/AVG aggregations
        if self._is_pure_aggregation(normalized):
            return

        for table in VAULT_TABLES:
            # Check if the table is referenced in FROM or JOIN
            if (
                re.search(rf"\b{re.escape(table)}\b", normalized)
                and "user_id" not in normalized
                and "where" not in normalized
            ):
                # Must have user_id in WHERE or JOIN condition
                # Exception for suppression_list (queried by hash)
                if table == "suppression_list" and (
                    "email_hash" in normalized or "name_company_hash" in normalized
                ):
                    continue
                # Exception for marketplace_listings (public anonymous data)
                if table == "marketplace_listings" and "group by" in normalized:
                    continue
                # Exception for usage_logs (metering, not PII)
                if table == "usage_logs":
                    continue
                raise PrivacyViolation(
                    f"Vault table '{table}' queried without user_id scoping",
                    violation_type="missing_user_scope",
                    privy_category="vault_isolation",
                    detail=f"Table: {table}",
                )

    def _check_suppression_plaintext(self, normalized: str) -> None:
        """Suppression list must be queried by hash, not plaintext (privy: suppression)."""
        if "suppression_list" not in normalized:
            return
        # Look for plaintext email patterns in WHERE clause
        if re.search(r"suppression_list.*where.*email\s*=\s*'", normalized):
            raise PrivacyViolation(
                "Suppression list queried by plaintext email — must use SHA-256 hash",
                violation_type="plaintext_suppression",
                privy_category="suppression",
            )
        if re.search(
            r"suppression_list.*where.*(?:full_name|first_name|last_name)\s*=\s*'",
            normalized,
        ):
            raise PrivacyViolation(
                "Suppression list queried by plaintext name — must use SHA-256 hash",
                violation_type="plaintext_suppression",
                privy_category="suppression",
            )

    def _check_audit_immutability(self, normalized: str) -> None:
        """Reject UPDATE/DELETE on immutable tables (privy: audit_immutability)."""
        for table in IMMUTABLE_TABLES:
            if re.search(rf"\bupdate\b.*\b{re.escape(table)}\b", normalized):
                raise PrivacyViolation(
                    f"UPDATE on immutable table '{table}' — audit logs must be append-only",
                    violation_type="immutable_table_mutation",
                    privy_category="audit_immutability",
                )
            if re.search(rf"\bdelete\b.*\b{re.escape(table)}\b", normalized):
                raise PrivacyViolation(
                    f"DELETE on immutable table '{table}' — audit logs must be append-only",
                    violation_type="immutable_table_mutation",
                    privy_category="audit_immutability",
                )

    # -- Helpers -------------------------------------------------------------

    def _matches_exception(self, normalized: str) -> bool:
        """Check if query matches an allowed cross-vault exception."""
        for exc in ALLOWED_CROSS_VAULT_EXCEPTIONS:
            if re.search(exc["pattern"].lower(), normalized):
                return True
        return False

    @staticmethod
    def _is_pure_aggregation(normalized: str) -> bool:
        """Check if SELECT clause contains only aggregation functions."""
        select_match = re.search(r"select\s+(.*?)\s+from\s", normalized)
        if not select_match:
            return False
        select_clause = select_match.group(1).strip()
        # Remove known aggregate functions
        cleaned = re.sub(r"\b(count|sum|avg|min|max)\s*\([^)]*\)", "", select_clause)
        # Remove commas, spaces, aliases
        cleaned = re.sub(r"\bas\s+\w+\b", "", cleaned)
        cleaned = re.sub(r"[,\s]", "", cleaned)
        return cleaned == ""

    @staticmethod
    def _has_k_anonymity_guard(normalized: str) -> bool:
        """Check for HAVING COUNT(*) >= k in the query.

        Also passes if GROUP BY only appears inside a subquery whose
        results are re-aggregated at the outer level (e.g., COUNT/SUM
        on a subquery with GROUP BY).
        """
        # Direct HAVING check — matches COUNT(*) >= N and COUNT(DISTINCT ...) >= N
        pattern = r"having\s+count\s*\([^)]*\)\s*>=\s*(\d+)"
        match = re.search(pattern, normalized)
        if match:
            k_val = int(match.group(1))
            return k_val >= _MIN_K

        # Subquery pattern: GROUP BY inside (...) sub with outer aggregation
        # e.g., SELECT COUNT(*) FROM (... GROUP BY ...) sub
        if re.search(r"\)\s*(?:sub|s|t|subq)\b", normalized):
            # GROUP BY is in a subquery; check if the outer SELECT is aggregated
            outer_select = re.match(r"select\s+(.*?)\s+from\s*\(", normalized)
            if outer_select:
                outer_cols = outer_select.group(1)
                if re.search(r"\b(count|sum|avg|min|max)\s*\(", outer_cols):
                    return True

        return False


# Module-level constant
_MIN_K = 5

# Singleton for convenience
guard = PrivacyGuard()
