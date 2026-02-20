"""Session cost and duration logger — runs when a Claude Code session ends.

Logs session metadata for Finance team cost tracking.
Triggered by the Stop hook in .claude/settings.json.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import contextlib

LOG_DIR = Path("agents/hooks/session_logs")
DAILY_BUDGET_USD = 3.0


def log_session(session_data: dict | None = None) -> None:
    """Log a session's cost and duration for Finance tracking."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"sessions-{today}.jsonl"

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": os.environ.get("CLAUDE_SESSION_ID", "unknown"),
        "agent": session_data.get("agent", "unknown") if session_data else "unknown",
        "model": session_data.get("model", "unknown") if session_data else "unknown",
        "duration_seconds": session_data.get("duration_seconds", 0)
        if session_data
        else 0,
        "tokens_used": session_data.get("tokens_used", 0) if session_data else 0,
        "estimated_cost_usd": session_data.get("estimated_cost_usd", 0.0)
        if session_data
        else 0.0,
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Check daily total and warn if approaching budget
    daily_total = _get_daily_total(log_file)
    if daily_total > DAILY_BUDGET_USD:
        print(
            f"COST ALERT: Daily spend ${daily_total:.2f} exceeds "
            f"budget ${DAILY_BUDGET_USD:.2f}. Consider throttling to lower model tiers."
        )
    elif daily_total > DAILY_BUDGET_USD * 0.8:
        print(
            f"COST WARNING: Daily spend ${daily_total:.2f} is at "
            f"{daily_total / DAILY_BUDGET_USD * 100:.0f}% of budget."
        )


def _get_daily_total(log_file: Path) -> float:
    """Sum estimated costs from today's session log."""
    total = 0.0
    if log_file.exists():
        for line in log_file.read_text().strip().split("\n"):
            if line:
                entry = json.loads(line)
                total += entry.get("estimated_cost_usd", 0.0)
    return total


def get_daily_summary(date: str | None = None) -> dict:
    """Generate a cost summary for a given date (default: today)."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log_file = LOG_DIR / f"sessions-{date}.jsonl"
    if not log_file.exists():
        return {"date": date, "sessions": 0, "total_cost_usd": 0.0, "by_agent": {}}

    sessions = []
    for line in log_file.read_text().strip().split("\n"):
        if line:
            sessions.append(json.loads(line))

    by_agent: dict[str, float] = {}
    for s in sessions:
        agent = s.get("agent", "unknown")
        by_agent[agent] = by_agent.get(agent, 0.0) + s.get("estimated_cost_usd", 0.0)

    return {
        "date": date,
        "sessions": len(sessions),
        "total_cost_usd": sum(s.get("estimated_cost_usd", 0.0) for s in sessions),
        "by_agent": by_agent,
        "budget_usd": DAILY_BUDGET_USD,
    }


def main() -> None:
    """Entry point for the hook."""
    # Parse any session data passed as argument
    session_data = None
    if len(sys.argv) > 1:
        with contextlib.suppress(json.JSONDecodeError, IndexError):
            session_data = json.loads(sys.argv[1])

    log_session(session_data)

    # Print summary if requested
    if "--summary" in sys.argv:
        summary = get_daily_summary()
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
