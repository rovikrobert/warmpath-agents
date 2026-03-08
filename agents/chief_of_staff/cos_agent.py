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

from agents.shared.config import REPORTS_DIR  # noqa: E402
from agents.shared.cost_tracker import check_budget_alerts, get_team_cost_summary  # noqa: E402
from agents.shared.report import AgentReport  # noqa: E402

from .budget_enforcer import (  # noqa: E402
    enforce_budget,
    get_budget_enforcement_report,
    update_throttle_status,
)
from .cos_config import COS_CONFIG  # noqa: E402
from .cos_learning import (  # noqa: E402
    record_cost_snapshot,
    record_founder_decision,
    update_team_reliability,
)
from .notion_sync import NotionSync  # noqa: E402
from .org_evaluator import evaluate_triggers, generate_restructuring_proposal  # noqa: E402
from .pod_manager import detect_permanent_pods, get_pod_report  # noqa: E402
from .resolver import attempt_resolution  # noqa: E402
from .router import get_request_tracking_report, route_and_track_request  # noqa: E402
from .schemas import Conflict  # noqa: E402
from .synthesizer import synthesize_daily, synthesize_status, synthesize_weekly  # noqa: E402
from .telegram_bridge import TelegramBridge, TELEGRAM_DIR  # noqa: E402

logger = logging.getLogger(__name__)

# Team report directories — import failures are BUGS, not optional features.
# If a team package is missing, we want to know immediately.
_TEAM_REPORT_DIRS: dict[str, Path | None] = {}
for _team_name, _module_path in [
    ("data", "data_team.shared.config"),
    ("product", "product_team.shared.config"),
    ("ops", "ops_team.shared.config"),
    ("finance", "finance_team.shared.config"),
    ("gtm", "gtm_team.shared.config"),
]:
    try:
        import importlib

        _mod = importlib.import_module(_module_path)
        _TEAM_REPORT_DIRS[_team_name] = _mod.REPORTS_DIR
    except ImportError:
        logger.error(
            "BUG: Cannot import %s — %s team reports will be MISSING from briefs. "
            "Fix the import or check that the package is installed.",
            _module_path,
            _team_name,
        )
        _TEAM_REPORT_DIRS[_team_name] = None

# Expose as module-level names for backward compat and test patching
DATA_TEAM_REPORTS_DIR = _TEAM_REPORT_DIRS.get("data")
PRODUCT_TEAM_REPORTS_DIR = _TEAM_REPORT_DIRS.get("product")
OPS_TEAM_REPORTS_DIR = _TEAM_REPORT_DIRS.get("ops")
FINANCE_TEAM_REPORTS_DIR = _TEAM_REPORT_DIRS.get("finance")
GTM_TEAM_REPORTS_DIR = _TEAM_REPORT_DIRS.get("gtm")


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _load_reports() -> tuple[list[AgentReport], list[dict]]:
    """Load cached reports from Redis (preferred) or filesystem (fallback).

    Returns (reports, cross_team_requests) — cross-team requests are extracted
    from team reports and surfaced separately for the daily brief.
    """
    reports: list[AgentReport] = []
    cross_team_requests: list[dict] = []

    _AR_FIELDS = {
        "agent",
        "timestamp",
        "scan_duration_seconds",
        "findings",
        "metrics",
        "intelligence_applied",
        "learning_updates",
    }

    # Try Redis first (persists across Railway Cron container restarts)
    try:
        from agents.shared.report_store import load_all_reports_from_redis

        redis_reports = load_all_reports_from_redis()
        if redis_reports:
            logger.info("Loading %d reports from Redis", len(redis_reports))
            for data in redis_reports:
                try:
                    # Extract cross-team requests
                    for req in data.get("cross_team_requests", []):
                        req["source_agent"] = data.get("agent", "unknown")
                        cross_team_requests.append(req)

                    clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                    reports.append(AgentReport.from_dict(clean))
                except (KeyError, TypeError) as exc:
                    logger.warning("Failed to parse Redis report: %s", exc)
                    continue
            if reports:
                return reports, cross_team_requests
            logger.warning(
                "Redis reports parsed but none valid, falling back to filesystem"
            )
    except Exception:
        logger.debug("Redis report loading unavailable, using filesystem")

    # Filesystem fallback (local dev or Redis unavailable)
    def _load_dir(
        reports_dir: Path | None, team_label: str, is_engineering: bool = False
    ) -> None:
        if reports_dir is None:
            logger.error(
                "BUG: %s reports dir is None — team import failed. "
                "This team will be MISSING from the daily brief.",
                team_label,
            )
            return
        if not reports_dir.is_dir():
            logger.warning(
                "%s reports dir does not exist: %s — no reports to load. "
                "Run the %s team scan first.",
                team_label,
                reports_dir,
                team_label,
            )
            return
        json_files = sorted(reports_dir.glob("*_latest.json"))
        if not json_files:
            logger.warning(
                "%s reports dir is empty: %s — no *_latest.json files found.",
                team_label,
                reports_dir,
            )
            return
        loaded = 0
        for path in json_files:
            try:
                data = json.loads(path.read_text())
                # Extract cross-team requests before stripping fields
                for req in data.get("cross_team_requests", []):
                    req["source_agent"] = data.get("agent", "unknown")
                    cross_team_requests.append(req)
                if is_engineering:
                    reports.append(AgentReport.from_dict(data))
                else:
                    clean = {k: v for k, v in data.items() if k in _AR_FIELDS}
                    reports.append(AgentReport.from_dict(clean))
                loaded += 1
            except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
                logger.warning(
                    "Failed to load %s report %s: %s", team_label, path.name, exc
                )
                continue
        logger.info("Loaded %d/%d reports from %s", loaded, len(json_files), team_label)

    _load_dir(REPORTS_DIR, "engineering", is_engineering=True)
    _load_dir(DATA_TEAM_REPORTS_DIR, "data")
    _load_dir(PRODUCT_TEAM_REPORTS_DIR, "product")
    _load_dir(OPS_TEAM_REPORTS_DIR, "ops")
    _load_dir(FINANCE_TEAM_REPORTS_DIR, "finance")
    _load_dir(GTM_TEAM_REPORTS_DIR, "gtm")

    return reports, cross_team_requests


def _get_kpi_snapshot(reports: list[AgentReport]) -> str:
    """Generate KPI snapshot, gracefully handling import/compute errors."""
    try:
        from agents.shared.kpis import compute_kpis, render_kpi_summary

        dashboard = compute_kpis(reports)
        return render_kpi_summary(dashboard)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Conflict detection & resolution logging
# ---------------------------------------------------------------------------


def _detect_conflicts(cross_team_requests: list[dict]) -> list[Conflict]:
    """Detect conflicts from cross-team requests.

    A conflict exists when two different teams have requests touching the same
    domain with a meaningful urgency gap (>= 2 levels apart).
    """
    conflicts: list[Conflict] = []
    domain_keywords: dict[str, list[str]] = {
        "security": ["security", "privacy", "breach", "pii", "vulnerability"],
        "shipping": ["ship", "feature", "launch", "release", "sprint"],
        "cost": ["cost", "budget", "spend", "credit", "billing"],
        "data": ["schema", "migration", "database", "pipeline"],
        "ux": ["ux", "accessibility", "onboarding", "journey", "conversion"],
    }
    domain_buckets: dict[str, list[dict]] = {d: [] for d in domain_keywords}
    for req in cross_team_requests:
        req_text = (
            req.get("request", "") + " " + (req.get("blocking", "") or "")
        ).lower()
        for domain, kws in domain_keywords.items():
            if any(kw in req_text for kw in kws):
                domain_buckets[domain].append(req)

    conflict_id = 0
    urgency_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for domain, reqs in domain_buckets.items():
        if len(reqs) < 2:
            continue
        teams = list({r.get("source_agent", r.get("team", "unknown")) for r in reqs})
        if len(teams) < 2:
            continue
        urgencies = [urgency_map.get(r.get("urgency", "medium"), 2) for r in reqs]
        if max(urgencies) - min(urgencies) >= 2:
            conflict_id += 1
            conflicts.append(
                Conflict(
                    id=f"conflict-{conflict_id:03d}-{domain}",
                    teams=teams[:2],
                    description=f"Conflicting urgency on {domain}: {teams[0]} vs {teams[1]}",
                    positions={
                        r.get("source_agent", r.get("team", "unknown")): r.get(
                            "request", ""
                        )
                        for r in reqs[:2]
                    },
                    evidence={
                        r.get("source_agent", r.get("team", "unknown")): r.get(
                            "blocking", ""
                        )
                        or ""
                        for r in reqs[:2]
                    },
                    cos_recommendation=f"Prioritize {domain} concern by decision principles",
                    resolution_level=1,
                )
            )
    return conflicts


def _log_resolutions_to_notion(resolutions: list, conflicts: list) -> None:
    """Log each conflict resolution to the Notion Decision Log (best-effort)."""
    if not resolutions:
        return
    try:
        notion = NotionSync()
        if not notion.enabled:
            return
        conflict_map = {c.id: c for c in conflicts}
        for res in resolutions:
            conflict = conflict_map.get(res.conflict_id)
            decider = "Founder" if res.escalated else "CoS"
            context = (
                conflict.description if conflict else f"conflict_id={res.conflict_id}"
            )
            business_outcomes = None
            if conflict and any(
                "privacy" in p.lower() or "security" in p.lower()
                for p in conflict.positions.values()
            ):
                business_outcomes = ["#1 Job seekers land jobs"]
            notion.log_decision(
                decision=f"[{res.strategy_used}] {res.conflict_id}",
                decider=decider,
                context=context,
                outcome=res.outcome,
                business_outcomes=business_outcomes,
            )
    except Exception:
        logger.debug("Resolution logging to Notion skipped")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_daily() -> str:
    """Daily cycle: load reports -> synthesize -> output brief -> Notion + Telegram."""
    reports, cross_team_requests = _load_reports()
    if not reports:
        return "# Founder Daily Brief\n\nNo engineering reports available. Run agent scans first."

    # -- Stale scan detection --------------------------------------------------
    # Check each report's timestamp; flag teams whose latest report is >48h old.
    from datetime import datetime, timedelta, timezone as _tz

    _stale_threshold = timedelta(hours=48)
    _now = datetime.now(_tz.utc)
    _stale_teams: list[str] = []
    _team_agents_map = {
        "engineering": {
            "architect",
            "test_engineer",
            "perf_monitor",
            "deps_manager",
            "doc_keeper",
        },
        "data": {"pipeline", "analyst", "model_engineer", "data_lead"},
        "product": {
            "user_researcher",
            "product_manager",
            "ux_lead",
            "design_lead",
            "product_lead",
        },
        "ops": {"keevs", "treb", "naiv", "marsh", "ops_lead"},
        "finance": {
            "finance_manager",
            "credits_manager",
            "investor_relations",
            "legal_compliance",
            "finance_lead",
        },
        "gtm": {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"},
    }
    # Find the most recent report timestamp per team
    _team_latest: dict[str, datetime] = {}
    for _r in reports:
        _team_name_for_r = "engineering"
        for _tn, _agents in _team_agents_map.items():
            if _r.agent in _agents:
                _team_name_for_r = _tn
                break
        if _r.timestamp:
            try:
                _ts = datetime.fromisoformat(_r.timestamp)
                if _ts.tzinfo is None:
                    _ts = _ts.replace(tzinfo=_tz.utc)
                if (
                    _team_name_for_r not in _team_latest
                    or _ts > _team_latest[_team_name_for_r]
                ):
                    _team_latest[_team_name_for_r] = _ts
            except (ValueError, TypeError):
                pass
    for _tn, _ts in _team_latest.items():
        if _now - _ts > _stale_threshold:
            _hours_old = int((_now - _ts).total_seconds() / 3600)
            _stale_teams.append(f"{_tn} ({_hours_old}h old)")
    if _stale_teams:
        logger.warning("Stale scan reports detected: %s", ", ".join(_stale_teams))

    kpi_snapshot = _get_kpi_snapshot(reports)
    costs = get_team_cost_summary(reports)
    alerts = check_budget_alerts(costs, COS_CONFIG["cost_budget"])

    # Read active founder briefs from Notion (Rovik → CoS context)
    founder_requests: list[dict] = []
    try:
        notion = NotionSync()
        if notion.enabled:
            founder_requests = notion.get_active_briefs()
            if founder_requests:
                logger.info(
                    "Found %d active founder briefs from Notion", len(founder_requests)
                )
    except Exception:
        logger.debug("get_active_briefs skipped (Notion not configured)")

    # Process async commands (Gap 8 — Telegram)
    _process_async_commands()

    # Route and track cross-team requests (Gap 6)
    for req in cross_team_requests:
        try:
            route_and_track_request(req)
        except Exception:
            logger.debug("Failed to route request: %s", req.get("request", "")[:60])

    # Detect and resolve cross-team conflicts
    conflicts = _detect_conflicts(cross_team_requests)
    resolutions = [attempt_resolution(c) for c in conflicts]
    escalated = [r for r in resolutions if r.escalated]
    auto_resolved = [r for r in resolutions if not r.escalated]
    if conflicts:
        logger.info(
            "Resolved %d conflicts (%d escalated, %d auto-resolved)",
            len(conflicts),
            len(escalated),
            len(auto_resolved),
        )
    # Inject escalated resolutions as critical cross-team requests
    for res in escalated:
        cross_team_requests.append(
            {
                "source_agent": "cos",
                "team": "cos",
                "request": f"[CONFLICT ESCALATED] {res.outcome}",
                "urgency": "critical",
                "blocking": f"conflict_id={res.conflict_id}",
            }
        )

    # Budget enforcement (Gap 7) — throttle teams exceeding caps
    budget_actions = enforce_budget(costs)
    update_throttle_status(budget_actions)
    budget_report = get_budget_enforcement_report(budget_actions)

    # Pod status (Gap 5)
    pod_report = get_pod_report()

    # Request tracking report (Gap 6)
    request_report = get_request_tracking_report()

    # Run auto-repair on merged findings before synthesizing
    _repair_data = None
    _recommendation_data = None
    try:
        from agents.shared.repair import repair_auto_fixable
        from agents.shared.report import merge_reports as _merge_for_repair

        _all_findings = _merge_for_repair(reports) if reports else []
        _repair_result = repair_auto_fixable(_all_findings)
        if _repair_result.fixed_count > 0 or _repair_result.failed_count > 0:
            _repair_data = {
                "fixed_count": _repair_result.fixed_count,
                "failed_count": _repair_result.failed_count,
                "skipped_count": _repair_result.skipped_count,
                "pr_url": _repair_result.pr_url,
                "errors": _repair_result.errors,
            }
        if _repair_result.recommendations:
            _recommendation_data = _repair_result.recommendations
    except Exception as _exc:
        logger.warning("CoS repair phase skipped: %s", _exc)

    brief, brief_data = synthesize_daily(
        reports,
        kpi_snapshot,
        costs,
        alerts,
        cross_team_requests,
        founder_requests=founder_requests,
        resolutions=[r.model_dump() for r in resolutions],
        repairs=_repair_data,
        recommendations=_recommendation_data,
    )

    # Inject stale scan alerts into decisions_needed so they surface in Notion/Telegram
    if _stale_teams:
        _stale_decision = {
            "id": "stale-scans",
            "summary": f"STALE SCANS: {', '.join(_stale_teams)} — re-run with `python3 -m agents.orchestrator --all`",
            "severity": "high",
            "business_impact": "Blind spots — decisions based on outdated data",
            "recommended_action": "Re-run agent scans to refresh report data",
            "outcomes": [],
        }
        brief_data.setdefault("decisions_needed", []).insert(0, _stale_decision)
        # Also prepend to the rendered brief
        _parts = brief.split("\n", 1)
        _stale_block = (
            "\n\n> **STALE SCANS:** "
            + ", ".join(_stale_teams)
            + " — re-run with `python3 -m agents.orchestrator --all`\n\n"
        )
        brief = _parts[0] + _stale_block + (_parts[1] if len(_parts) > 1 else "")

    # Append new sections to brief
    for section in (budget_report, pod_report, request_report):
        if section:
            brief += "\n" + section

    # Update learning state
    _data_agents = {"pipeline", "analyst", "model_engineer", "data_lead"}
    _product_agents = {
        "user_researcher",
        "product_manager",
        "ux_lead",
        "design_lead",
        "product_lead",
    }
    _ops_agents = {"keevs", "treb", "naiv", "marsh", "ops_lead"}
    _finance_agents = {
        "finance_manager",
        "credits_manager",
        "investor_relations",
        "legal_compliance",
        "finance_lead",
    }
    _gtm_agents = {"stratops", "monetization", "marketing", "partnerships", "gtm_lead"}
    eng_reports = [
        r
        for r in reports
        if r.agent not in _data_agents
        and r.agent not in _product_agents
        and r.agent not in _ops_agents
        and r.agent not in _finance_agents
        and r.agent not in _gtm_agents
    ]
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

    # Push to Notion and generate Telegram message
    team_report_groups = {
        "engineering": eng_reports,
        "data": data_reports,
        "product": product_reports,
        "ops": ops_reports,
        "finance": finance_reports,
        "gtm": gtm_reports,
    }
    _push_daily_outputs(brief, costs, alerts, brief_data, team_report_groups)

    # Log conflict resolutions to Notion Decision Log
    _log_resolutions_to_notion(resolutions, conflicts)

    return brief


def _build_team_detail_markdown(team: str, reports: list[AgentReport]) -> str:
    """Build rich detail markdown for a team's Notion dashboard page."""
    if not reports:
        return ""
    lines: list[str] = []

    # Severity distribution
    all_findings = [f for r in reports for f in r.findings]
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in all_findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
    nonzero = {k: v for k, v in severity_counts.items() if v > 0}
    if nonzero:
        lines.append("## Severity Distribution")
        for sev, count in nonzero.items():
            lines.append(f"- {sev.title()}: {count}")
    else:
        lines.append("## Severity Distribution")
        lines.append("- No findings this cycle")

    # Per-agent breakdown
    lines.append("## Agent Breakdown")
    for r in sorted(reports, key=lambda x: len(x.findings), reverse=True):
        duration = (
            f"{r.scan_duration_seconds:.1f}s" if r.scan_duration_seconds else "N/A"
        )
        lines.append(f"- {r.agent}: {len(r.findings)} findings ({duration})")

    # Top findings (up to 10, highest severity first)
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    top = sorted(all_findings, key=lambda f: sev_order.get(f.severity, 5))[:10]
    if top:
        lines.append("## Top Findings")
        for f in top:
            lines.append(f"- [{f.severity.upper()}] {f.title}")
            if f.recommendation:
                lines.append(f"  Rec: {f.recommendation[:120]}")

    # Key metrics (if any reports have them)
    merged_metrics: dict = {}
    for r in reports:
        if r.metrics:
            merged_metrics.update(r.metrics)
    if merged_metrics:
        lines.append("## Key Metrics")
        # Show up to 10 most interesting metrics (skip internal/raw ones)
        shown = 0
        for k, v in merged_metrics.items():
            if shown >= 10:
                break
            if isinstance(v, (int, float, str, bool)):
                lines.append(f"- {k}: {v}")
                shown += 1

    return "\n".join(lines)


def _push_daily_outputs(
    brief: str,
    costs: dict,
    alerts: list[str],
    brief_data: dict | None = None,
    team_report_groups: dict[str, list[AgentReport]] | None = None,
) -> None:
    """Push daily brief to Notion and generate Telegram message (best-effort).

    Idempotent: skips if today's brief has already been pushed (prevents
    duplicate Notion pages and Telegram spam from multiple deploys/triggers).
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_cost = costs.get("total_estimated_cost_usd", 0)

    # Extract headline from brief (first heading line)
    headline = "Daily brief generated"
    for line in brief.split("\n"):
        if line.startswith("# "):
            headline = line.lstrip("# ").strip()
            break

    # Notion sync (skip if already pushed today)
    notion_page_id = ""
    try:
        notion = NotionSync()
        if notion.enabled:
            if notion._state.get("last_daily_sync") == today:
                logger.info(
                    "Daily brief already synced to Notion for %s — skipping", today
                )
                notion_page_id = notion._state.get("last_daily_page_id", "")
            else:
                _bd = brief_data or {}
                result = notion.push_daily_brief(
                    date=today,
                    headline=headline,
                    team_status={
                        p.get("team", "engineering"): p.get("note", "Clean scan")
                        for p in _bd.get("progress", [])
                    },
                    decisions_needed=[
                        d.get("summary", "") for d in _bd.get("decisions_needed", [])
                    ],
                    blockers=[],
                    cost_yesterday=f"${total_cost:.2f}",
                    brief_markdown=brief,
                )
                notion_page_id = result.get("page_id", "")
    except Exception:
        logger.debug("Notion sync skipped (not configured or error)")

    # Telegram message — skip if already sent today
    tg_marker = TELEGRAM_DIR / f"telegram-daily-{today}.txt"
    if tg_marker.exists():
        logger.info("Daily Telegram already sent for %s — skipping", today)
    else:
        try:
            tg = TelegramBridge()
            tg_data = brief_data or {"decisions_needed": [], "team_summaries": []}
            tg.generate_daily_brief(
                tg_data, costs, alerts, notion_page_id=notion_page_id
            )
        except Exception:
            logger.debug("Telegram daily brief generation skipped")

    # Push per-team reports to Notion (skip if already pushed today)
    if brief_data:
        try:
            notion = NotionSync()
        except Exception:
            notion = None
            logger.warning("Failed to initialize NotionSync for team reports")
        if notion and notion.enabled:
            if notion._state.get("last_team_reports_sync") == today:
                logger.info(
                    "Team reports already synced to Notion for %s — skipping",
                    today,
                )
            else:
                _trg = team_report_groups or {}
                failed_teams: list[str] = []
                for ts in brief_data.get("team_summaries", []):
                    team_name = ts.get("team", "unknown")
                    try:
                        detail_md = _build_team_detail_markdown(
                            team_name, _trg.get(team_name, [])
                        )
                        notion.push_team_report(
                            date=today,
                            team=team_name,
                            health=ts.get("health", "green"),
                            summary=ts.get("summary", ""),
                            agent_count=ts.get("agent_count", 0),
                            finding_count=ts.get("finding_count", 0),
                            detail_markdown=detail_md,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to push %s team report to Notion", team_name
                        )
                        failed_teams.append(team_name)

                if not failed_teams:
                    notion._state["last_team_reports_sync"] = today
                    notion._save_state()
                else:
                    logger.warning(
                        "Team report push incomplete — failed: %s",
                        ", ".join(failed_teams),
                    )


def run_weekly() -> str:
    """Weekly cycle: deeper analysis + self-learning + org evaluation."""
    reports, _cross_team = _load_reports()
    if not reports:
        return "# Weekly Synthesis\n\nNo engineering reports available. Run agent scans first."

    kpi_snapshot = _get_kpi_snapshot(reports)
    costs = get_team_cost_summary(reports)
    brief = synthesize_weekly(reports, kpi_snapshot, costs)

    # Org restructuring evaluation (Gap 4 — COS.md 7.7: weekly trigger scan)
    try:
        triggers = evaluate_triggers(reports, costs)
        if triggers:
            proposal = generate_restructuring_proposal(triggers)
            brief += "\n" + proposal
            logger.info("Org evaluation: %d triggers fired", len(triggers))
    except Exception:
        logger.debug("Org evaluation skipped")

    # Pod health review (Gap 5 — COS.md 7.7: weekly pod check)
    try:
        pod_report = get_pod_report()
        if pod_report:
            brief += "\n" + pod_report
        permanent_warnings = detect_permanent_pods()
        if permanent_warnings:
            brief += "\n### Pod Anti-Pattern Alerts\n\n"
            brief += "\n".join(f"- [!] {w}" for w in permanent_warnings)
            brief += "\n"
    except Exception:
        logger.debug("Pod review skipped")

    # Telegram weekly summary — skip if already sent
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tg_weekly_marker = TELEGRAM_DIR / f"telegram-weekly-{today}.txt"
    if tg_weekly_marker.exists():
        logger.info("Weekly Telegram already sent for %s — skipping", today)
    else:
        try:
            tg = TelegramBridge()
            tg.generate_weekly_summary(
                week_num=_current_week_number(),
                metrics={
                    "weekly_cost": f"${costs.get('total_estimated_cost_usd', 0) * 7:.2f}",
                    "daily_avg": f"${costs.get('total_estimated_cost_usd', 0):.2f}/day",
                },
            )
        except Exception:
            logger.debug("Telegram weekly summary skipped")

    # Push weekly synthesis to Notion
    try:
        notion = NotionSync()
        if notion.enabled:
            notion.push_weekly_synthesis(date=today, brief_markdown=brief)
    except Exception:
        logger.debug("Weekly Notion sync skipped")

    return brief


def run_status() -> str:
    """Quick cross-team status snapshot."""
    reports, _cross_team = _load_reports()
    if not reports:
        return "# Status Snapshot\n\nNo engineering reports available."
    return synthesize_status(reports)


def _current_week_number() -> int:
    """Return ISO week number for the current date."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isocalendar()[1]


# ---------------------------------------------------------------------------
# Async command processing (Gap 8 — Telegram)
# ---------------------------------------------------------------------------


def _process_async_commands() -> list[dict]:
    """Scan for Telegram reply files and process commands."""
    results: list[dict] = []

    # Telegram replies (file-based fallback before webhook is live)
    if TELEGRAM_DIR.is_dir():
        for reply_file in sorted(TELEGRAM_DIR.glob("telegram-reply-*.txt")):
            parsed = _process_single_reply(reply_file, source="telegram")
            if parsed:
                results.append(parsed)

    return results


def _process_single_reply(reply_file: Path, source: str = "telegram") -> dict | None:
    """Process a single reply file and archive it."""
    try:
        text = reply_file.read_text(encoding="utf-8").strip()
        if not text:
            return None

        from agents.shared.message_formatter import MessageFormatter

        parsed = MessageFormatter.parse_reply(text)
        parsed["source"] = source
        command = parsed.get("command", "unknown")

        if command == "status":
            logger.info("%s command: status request", source.title())
        elif command == "approve":
            item_id = parsed.get("item", "")
            record_founder_decision(item_id, "cos_recommendation", "approved")
            logger.info("%s command: approved %s", source.title(), item_id)
        elif command == "choose":
            choice = parsed.get("choice", "")
            logger.info("%s command: chose option %s", source.title(), choice)
        elif command == "ship":
            feature = parsed.get("feature", "")
            logger.info("%s command: ship %s", source.title(), feature)
        else:
            logger.info("%s command: %s", source.title(), command)

        # Archive processed reply
        processed_path = reply_file.with_suffix(".processed")
        reply_file.rename(processed_path)

        return parsed
    except Exception:
        logger.debug("Failed to process reply: %s", reply_file.name)
        return None


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
        print(
            "No databases were created. Check your Notion API key and parent page ID."
        )


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
            print(
                "Usage: python -m agents.chief_of_staff.cos_agent setup-notion <parent_page_id>"
            )
            sys.exit(1)
        setup_notion(sys.argv[2])
    else:
        print(run_daily())


if __name__ == "__main__":
    main()
