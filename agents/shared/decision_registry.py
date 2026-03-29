"""Decision registry — maps Telegram brief decision numbers to findings.

Persists pending decisions from daily briefs so Telegram approvals
can look up the original finding and dispatch to the execution engine.
Storage: JSON file with fcntl file locking for concurrency safety.
"""

from __future__ import annotations

import fcntl
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DECISIONS_PATH = Path("agents/chief_of_staff/reports/pending_decisions.json")

# Max decisions to store (matches Telegram display cap in MessageFormatter)
MAX_DECISIONS = 3

# Auto-expire decisions older than this many days
DECISION_TTL_DAYS = 7


@dataclass
class PendingDecision:
    number: int
    finding_id: str
    finding: dict[str, Any]
    brief_date: str
    tier: str
    action_plan: str
    failure_modes: list[str] = field(default_factory=list)
    rollback_plan: str = ""
    executed_at: str | None = None
    result_summary: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> PendingDecision:
        """Reconstruct from dict, ignoring unknown fields for forward-compat."""
        from dataclasses import fields as dc_fields

        known = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


def save_pending_decisions(decisions: list[PendingDecision]) -> Path:
    """Write pending decisions to JSON file, capped at MAX_DECISIONS.

    Uses exclusive flock to prevent partial reads during concurrent writes.
    """
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    capped = decisions[:MAX_DECISIONS]
    data = [asdict(d) for d in capped]
    with open(DECISIONS_PATH, "w", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
    logger.info("Saved %d pending decisions to %s", len(capped), DECISIONS_PATH)
    return DECISIONS_PATH


def load_pending_decisions() -> list[PendingDecision]:
    """Load pending decisions from JSON file (under shared flock).

    Auto-expires decisions older than DECISION_TTL_DAYS based on brief_date.
    Executed decisions are also pruned (they've already been acted on).
    """
    if not DECISIONS_PATH.exists():
        return []
    try:
        with open(DECISIONS_PATH, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        decisions = [PendingDecision.from_dict(d) for d in data]
        return _prune_stale(decisions)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.warning("Failed to load pending decisions: %s", exc)
        return []


def _prune_stale(decisions: list[PendingDecision]) -> list[PendingDecision]:
    """Remove decisions whose brief_date is older than DECISION_TTL_DAYS."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=DECISION_TTL_DAYS)
    kept: list[PendingDecision] = []

    for d in decisions:
        # Expire based on brief_date
        try:
            brief_dt = datetime.fromisoformat(d.brief_date)
            if brief_dt.tzinfo is None:
                brief_dt = brief_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            # brief_date might be just a date string like "2026-03-17"
            try:
                brief_dt = datetime.strptime(d.brief_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            except (ValueError, TypeError):
                kept.append(d)
                continue
        if brief_dt < cutoff:
            logger.info(
                "Auto-expired stale decision #%d (%s) from %s",
                d.number,
                d.finding_id,
                d.brief_date,
            )
            continue
        kept.append(d)

    return kept


def find_decision(
    number: int | None = None, *, finding_id: str | None = None
) -> PendingDecision | None:
    """Find a pending decision by display number or stable finding_id."""
    for d in load_pending_decisions():
        if number is not None and d.number == number:
            return d
        if finding_id is not None and d.finding_id == finding_id:
            return d
    return None


def mark_executed(number: int, result_summary: str) -> None:
    """Stamp a decision as executed (under exclusive flock)."""
    if not DECISIONS_PATH.exists():
        return
    with open(DECISIONS_PATH, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            data = json.load(f)
            for d in data:
                if d["number"] == number:
                    d["executed_at"] = datetime.now(timezone.utc).isoformat()
                    d["result_summary"] = result_summary
                    break
            f.seek(0)
            f.truncate()
            json.dump(data, f, indent=2)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
