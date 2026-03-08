"""Risk classification for agent findings.

Maps findings to risk levels that determine execution tier:
- TRIVIAL/LOW -> auto-do (execute immediately)
- MEDIUM -> auto-PR (open PR for review)
- HIGH/CRITICAL -> escalate (Telegram alert, don't touch)
"""

from __future__ import annotations

from enum import IntEnum

from agents.shared.report import Finding


class RiskLevel(IntEnum):
    TRIVIAL = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# Files that should never be auto-modified
PROTECTED_PATHS = {
    "app/api/auth.py",
    "app/services/credit_service.py",
    "app/services/stripe_service.py",
    "app/services/subscription_service.py",
    "app/middleware/security.py",
    "app/middleware/auth.py",
    "alembic/",
}

# Categories that are always low-risk when auto_fixable
SAFE_CATEGORIES = {"lint", "format", "a11y_mechanical", "design_token", "dep_patch"}


def _touches_protected_path(f: Finding) -> bool:
    if not f.file:
        return False
    return any(f.file.startswith(p) or f.file == p for p in PROTECTED_PATHS)


def classify_risk(finding: Finding) -> RiskLevel:
    """Classify a finding's risk level for execution triage."""
    # Critical severity is always critical risk
    if finding.severity == "critical":
        return RiskLevel.CRITICAL

    # Protected paths are always high+ risk
    if _touches_protected_path(finding):
        if finding.severity in ("high", "critical"):
            return RiskLevel.CRITICAL
        return RiskLevel.HIGH

    # Auto-fixable + safe category = trivial
    if finding.auto_fixable and finding.category in SAFE_CATEGORIES:
        return RiskLevel.TRIVIAL

    # Auto-fixable but not safe category = low
    if finding.auto_fixable:
        return RiskLevel.LOW

    # High severity = high risk
    if finding.severity == "high":
        return RiskLevel.HIGH

    # Info severity = trivial risk
    if finding.severity == "info":
        return RiskLevel.TRIVIAL

    # Default: medium
    return RiskLevel.MEDIUM
