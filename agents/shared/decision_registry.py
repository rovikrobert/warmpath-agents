"""Decision registry — maps Telegram brief decision numbers to findings.

Persists pending decisions from daily briefs so Telegram approvals
can look up the original finding and dispatch to the execution engine.
Storage: JSON file with fcntl file locking for concurrency safety.
"""

from __future__ import annotations

import fcntl
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DECISIONS_PATH = Path("agents/chief_of_staff/reports/pending_decisions.json")

# Max decisions to store (matches Telegram display cap in MessageFormatter)
MAX_DECISIONS = 3


@dataclass
class PendingDecision:
    number: int
    finding_id: str
    finding: dict[str, Any]
    brief_date: str
    tier: str
    action_plan: str
    executed_at: str | None = None
    result_summary: str | None = None


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
    """Load pending decisions from JSON file (under shared flock)."""
    if not DECISIONS_PATH.exists():
        return []
    try:
        with open(DECISIONS_PATH, encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
        return [PendingDecision(**d) for d in data]
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        logger.warning("Failed to load pending decisions: %s", exc)
        return []


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
