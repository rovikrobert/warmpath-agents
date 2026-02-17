"""Chief of Staff agent — synthesizes team reports into founder-facing briefs.

Usage:
    python -m agents.chief_of_staff.cos_agent daily    # Daily founder brief
    python -m agents.chief_of_staff.cos_agent weekly   # Weekly synthesis
    python -m agents.chief_of_staff.cos_agent status   # Quick status snapshot
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from agents.shared.config import REPORTS_DIR
from agents.shared.cost_tracker import check_budget_alerts, get_team_cost_summary
from agents.shared.report import AgentReport

from .cos_config import COS_CONFIG
from .cos_learning import record_cost_snapshot, update_team_reliability
from .synthesizer import synthesize_daily, synthesize_status, synthesize_weekly

logger = logging.getLogger(__name__)

# Data team reports directory — resolved lazily, patchable by tests
try:
    from data_team.shared.config import REPORTS_DIR as DATA_TEAM_REPORTS_DIR
except ImportError:
    DATA_TEAM_REPORTS_DIR = None

# Product team reports directory — resolved lazily, patchable by tests
try:
    from product_team.shared.config import REPORTS_DIR as PRODUCT_TEAM_REPORTS_DIR
except ImportError:
    PRODUCT_TEAM_REPORTS_DIR = None


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_reports() -> list[AgentReport]:
    """Load cached *_latest.json reports from REPORTS_DIR and data team."""
    reports: list[AgentReport] = []

    # Engineering reports
    if REPORTS_DIR.is_dir():
        for path in sorted(REPORTS_DIR.glob("*_latest.json")):
            try:
                data = json.loads(path.read_text())
                reports.append(AgentReport.from_dict(data))
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                continue

    # Data team reports (if available)
    _AR_FIELDS = {
        "agent", "timestamp", "scan_duration_seconds",
        "findings", "metrics", "intelligence_applied", "learning_updates",
    }
    if DATA_TEAM_REPORTS_DIR is not None and DATA_TEAM_REPORTS_DIR.is_dir():
        for path in sorted(DATA_TEAM_REPORTS_DIR.glob("*_latest.json")):
            try:
                data = json.loads(path.read_text())
                clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                reports.append(AgentReport.from_dict(clean))
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                continue

    # Product team reports (if available)
    if PRODUCT_TEAM_REPORTS_DIR is not None and PRODUCT_TEAM_REPORTS_DIR.is_dir():
        for path in sorted(PRODUCT_TEAM_REPORTS_DIR.glob("*_latest.json")):
            try:
                data = json.loads(path.read_text())
                clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                reports.append(AgentReport.from_dict(clean))
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                continue

    return reports


def _get_kpi_snapshot(reports: list[AgentReport]) -> str:
    """Generate KPI snapshot, gracefully handling import/compute errors."""
    try:
        from agents.shared.kpis import compute_kpis, render_kpi_summary

        dashboard = compute_kpis(reports)
        return render_kpi_summary(dashboard)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_daily() -> str:
    """Daily cycle: load reports -> synthesize -> output brief."""
    reports = _load_reports()
    if not reports:
        return "# Founder Daily Brief\n\nNo engineering reports available. Run agent scans first."

    kpi_snapshot = _get_kpi_snapshot(reports)
    costs = get_team_cost_summary(reports)
    alerts = check_budget_alerts(costs, COS_CONFIG["cost_budget"])
    brief = synthesize_daily(reports, kpi_snapshot, costs, alerts)

    # Update learning state
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {"user_researcher", "product_manager", "ux_lead", "design_lead", "product_lead"}
    eng_reports = [r for r in reports if r.agent not in _data_agents and r.agent not in _product_agents]
    data_reports = [r for r in reports if r.agent in _data_agents]
    product_reports = [r for r in reports if r.agent in _product_agents]
    update_team_reliability("engineering", eng_reports)
    if data_reports:
        update_team_reliability("data", data_reports)
    if product_reports:
        update_team_reliability("product", product_reports)
    record_cost_snapshot(costs)

    return brief


def run_weekly() -> str:
    """Weekly cycle: deeper analysis + self-learning."""
    reports = _load_reports()
    if not reports:
        return "# Weekly Synthesis\n\nNo engineering reports available. Run agent scans first."

    kpi_snapshot = _get_kpi_snapshot(reports)
    costs = get_team_cost_summary(reports)
    return synthesize_weekly(reports, kpi_snapshot, costs)


def run_status() -> str:
    """Quick cross-team status snapshot."""
    reports = _load_reports()
    if not reports:
        return "# Status Snapshot\n\nNo engineering reports available."
    return synthesize_status(reports)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"

    if mode == "weekly":
        print(run_weekly())
    elif mode == "status":
        print(run_status())
    else:
        print(run_daily())


if __name__ == "__main__":
    main()
