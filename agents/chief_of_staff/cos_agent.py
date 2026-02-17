"""Chief of Staff agent — synthesizes team reports into founder-facing briefs.

Usage:
    python -m agents.chief_of_staff.cos_agent daily                  # Daily founder brief
    python -m agents.chief_of_staff.cos_agent weekly                 # Weekly synthesis
    python -m agents.chief_of_staff.cos_agent status                 # Quick status snapshot
    python -m agents.chief_of_staff.cos_agent setup-notion <page_id> # One-time Notion setup
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path and load .env
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(_project_root) / ".env")
except ImportError:
    pass

from agents.shared.config import REPORTS_DIR
from agents.shared.cost_tracker import check_budget_alerts, get_team_cost_summary
from agents.shared.report import AgentReport

from .cos_config import COS_CONFIG
from .cos_learning import record_cost_snapshot, update_team_reliability
from .notion_sync import NotionSync
from .synthesizer import synthesize_daily, synthesize_status, synthesize_weekly
from .whatsapp_bridge import WhatsAppBridge

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

# Ops team reports directory — resolved lazily, patchable by tests
try:
    from ops_team.shared.config import REPORTS_DIR as OPS_TEAM_REPORTS_DIR
except ImportError:
    OPS_TEAM_REPORTS_DIR = None

# Finance team reports directory — resolved lazily, patchable by tests
try:
    from finance_team.shared.config import REPORTS_DIR as FINANCE_TEAM_REPORTS_DIR
except ImportError:
    FINANCE_TEAM_REPORTS_DIR = None

# GTM team reports directory — resolved lazily, patchable by tests
try:
    from gtm_team.shared.config import REPORTS_DIR as GTM_TEAM_REPORTS_DIR
except ImportError:
    GTM_TEAM_REPORTS_DIR = None


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

    # Ops team reports (if available)
    if OPS_TEAM_REPORTS_DIR is not None and OPS_TEAM_REPORTS_DIR.is_dir():
        for path in sorted(OPS_TEAM_REPORTS_DIR.glob("*_latest.json")):
            try:
                data = json.loads(path.read_text())
                clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                reports.append(AgentReport.from_dict(clean))
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                continue

    # Finance team reports (if available)
    if FINANCE_TEAM_REPORTS_DIR is not None and FINANCE_TEAM_REPORTS_DIR.is_dir():
        for path in sorted(FINANCE_TEAM_REPORTS_DIR.glob("*_latest.json")):
            try:
                data = json.loads(path.read_text())
                clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                reports.append(AgentReport.from_dict(clean))
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                continue

    # GTM team reports (if available)
    if GTM_TEAM_REPORTS_DIR is not None and GTM_TEAM_REPORTS_DIR.is_dir():
        for path in sorted(GTM_TEAM_REPORTS_DIR.glob("*_latest.json")):
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
    """Daily cycle: load reports -> synthesize -> output brief -> Notion + WhatsApp."""
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
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    _finance_agents = {"finance_manager", "credits_manager", "investor_relations", "legal_compliance", "finance_lead"}
    _gtm_agents = {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"}
    eng_reports = [r for r in reports if r.agent not in _data_agents and r.agent not in _product_agents and r.agent not in _ops_agents and r.agent not in _finance_agents and r.agent not in _gtm_agents]
    data_reports = [r for r in reports if r.agent in _data_agents]
    product_reports = [r for r in reports if r.agent in _product_agents]
    ops_reports = [r for r in reports if r.agent in _ops_agents]
    finance_reports = [r for r in reports if r.agent in _finance_agents]
    gtm_reports = [r for r in reports if r.agent in _gtm_agents]
    update_team_reliability("engineering", eng_reports)
    if data_reports:
        update_team_reliability("data", data_reports)
    if product_reports:
        update_team_reliability("product", product_reports)
    if ops_reports:
        update_team_reliability("ops", ops_reports)
    if finance_reports:
        update_team_reliability("finance", finance_reports)
    if gtm_reports:
        update_team_reliability("gtm", gtm_reports)
    record_cost_snapshot(costs)

    # Push to Notion and generate WhatsApp message
    _push_daily_outputs(brief, costs, alerts)

    return brief


def _push_daily_outputs(
    brief: str, costs: dict, alerts: list[str]
) -> None:
    """Push daily brief to Notion and generate WhatsApp message (best-effort)."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_cost = costs.get("total_estimated_cost_usd", 0)

    # Extract headline from brief (first heading line)
    headline = "Daily brief generated"
    for line in brief.split("\n"):
        if line.startswith("# "):
            headline = line.lstrip("# ").strip()
            break

    # Notion sync
    notion_page_id = ""
    try:
        notion = NotionSync()
        if notion.enabled:
            result = notion.push_daily_brief(
                date=today,
                headline=headline,
                team_status={},
                decisions_needed=[],
                blockers=[],
                cost_yesterday=f"${total_cost:.2f}",
                brief_markdown=brief,
            )
            notion_page_id = result.get("page_id", "")
    except Exception:
        logger.debug("Notion sync skipped (not configured or error)")

    # WhatsApp message (includes Notion link if available)
    try:
        wa = WhatsAppBridge()
        brief_data = {
            "decisions_needed": [],
            "progress": [],
        }
        wa.generate_morning_brief(brief_data, costs, alerts, notion_page_id=notion_page_id)
    except Exception:
        logger.debug("WhatsApp message generation skipped")


def run_weekly() -> str:
    """Weekly cycle: deeper analysis + self-learning."""
    reports = _load_reports()
    if not reports:
        return "# Weekly Synthesis\n\nNo engineering reports available. Run agent scans first."

    kpi_snapshot = _get_kpi_snapshot(reports)
    costs = get_team_cost_summary(reports)
    brief = synthesize_weekly(reports, kpi_snapshot, costs)

    # Push weekly WhatsApp summary (best-effort)
    try:
        wa = WhatsAppBridge()
        wa.generate_weekly_summary(
            week_num=_current_week_number(),
            metrics={
                "weekly_cost": f"${costs.get('total_estimated_cost_usd', 0) * 7:.2f}",
                "daily_avg": f"${costs.get('total_estimated_cost_usd', 0):.2f}/day",
            },
        )
    except Exception:
        logger.debug("Weekly WhatsApp summary skipped")

    return brief


def run_status() -> str:
    """Quick cross-team status snapshot."""
    reports = _load_reports()
    if not reports:
        return "# Status Snapshot\n\nNo engineering reports available."
    return synthesize_status(reports)


def _current_week_number() -> int:
    """Return ISO week number for the current date."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isocalendar()[1]


# ---------------------------------------------------------------------------
# Notion setup
# ---------------------------------------------------------------------------


def setup_notion(parent_page_id: str) -> None:
    """One-time Notion workspace setup — creates databases under a parent page."""
    notion = NotionSync()
    if not notion.enabled:
        print("Error: NOTION_API_KEY not set. Cannot create databases.")
        return
    db_ids = notion.setup_databases(parent_page_id)
    if db_ids:
        print("Notion databases created:")
        for name, db_id in db_ids.items():
            print(f"  {name}: {db_id}")
        print("\nAdd these IDs to your .env or cos_config for future runs.")
    else:
        print("No databases were created. Check your Notion API key and parent page ID.")


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
    elif mode == "setup-notion":
        if len(sys.argv) < 3:
            print("Usage: python -m agents.chief_of_staff.cos_agent setup-notion <parent_page_id>")
            sys.exit(1)
        setup_notion(sys.argv[2])
    else:
        print(run_daily())


if __name__ == "__main__":
    main()
