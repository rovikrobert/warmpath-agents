"""Lead agent — aggregates reports, deduplicates, prioritizes, generates briefs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from agents.shared.config import (
    MAX_FINDINGS_PER_BRIEF,
    REPORTS_DIR,
    SEVERITY_WEIGHTS,
)
from agents.shared.report import AgentReport, Finding, merge_reports
from agents.shared import learning

logger = logging.getLogger(__name__)

AGENT_NAME = "lead"


# ---------------------------------------------------------------------------
# Report collection
# ---------------------------------------------------------------------------


def _load_latest_reports() -> list[AgentReport]:
    """Load the most recent report from each agent in REPORTS_DIR."""
    reports: list[AgentReport] = []
    if not REPORTS_DIR.is_dir():
        return reports

    # Each agent writes <agent_name>_latest.json
    for path in sorted(REPORTS_DIR.glob("*_latest.json")):
        try:
            data = json.loads(path.read_text())
            reports.append(AgentReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as exc:
            logger.warning("Failed to load report %s: %s", path.name, exc)
    return reports


def save_report(report: AgentReport) -> Path:
    """Save an agent report to REPORTS_DIR as <agent>_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{report.agent}_latest.json"
    path.write_text(report.serialize())
    return path


# ---------------------------------------------------------------------------
# Scoring & prioritization
# ---------------------------------------------------------------------------


def _priority_score(f: Finding) -> float:
    """Higher score = more urgent. Combines severity, recurrence, and effort."""
    sev = SEVERITY_WEIGHTS.get(f.severity, 0)
    # Recurrence bonus: chronic issues get escalated
    recurrence_bonus = min(f.recurrence_count * 0.5, 3.0)
    # Low-effort wins get a slight bump (quicker to fix)
    effort_bonus = max(0, 2.0 - f.effort_hours) * 0.3 if f.effort_hours > 0 else 0
    return sev + recurrence_bonus + effort_bonus


# ---------------------------------------------------------------------------
# Brief generation
# ---------------------------------------------------------------------------


def generate_daily_brief(reports: list[AgentReport] | None = None) -> str:
    """Generate the daily engineering brief in markdown."""
    if reports is None:
        reports = _load_latest_reports()

    if not reports:
        return "## Engineering Brief — No Reports Available\n\nNo agent reports found. Run agent scans first."

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Merge and deduplicate findings
    all_findings = merge_reports(reports)

    # Score and sort
    scored = sorted(all_findings, key=_priority_score, reverse=True)

    # Split by severity
    critical = [f for f in scored if f.severity == "critical"]
    high = [f for f in scored if f.severity == "high"]
    medium = [f for f in scored if f.severity == "medium"]
    low = [f for f in scored if f.severity in ("low", "info")]

    # Aggregate metrics
    all_metrics: dict[str, object] = {}
    for r in reports:
        for k, v in r.metrics.items():
            all_metrics[f"{r.agent}/{k}"] = v

    # Count findings by severity
    sev_counts = {}
    for f in all_findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    # Collect learning updates
    all_learning = []
    for r in reports:
        for note in r.learning_updates:
            all_learning.append(f"[{r.agent}] {note}")

    # Build brief
    lines: list[str] = []
    lines.append(f"## Engineering Brief — {today}\n")

    # Critical
    lines.append("### Critical (act now)")
    if critical:
        for f in critical[:2]:
            loc = (
                f" (`{f.file}:{f.line}`)"
                if f.file and f.line
                else (f" (`{f.file}`)" if f.file else "")
            )
            lines.append(f"- **[{f.id}]** {f.title}{loc}")
            if f.recommendation:
                lines.append(f"  - {f.recommendation}")
    else:
        lines.append("None.")
    lines.append("")

    # Attention Needed
    lines.append("### Attention Needed")
    attention = (high + medium)[:5]
    if attention:
        for f in attention:
            loc = (
                f" (`{f.file}:{f.line}`)"
                if f.file and f.line
                else (f" (`{f.file}`)" if f.file else "")
            )
            recur = f" *(seen {f.recurrence_count}x)*" if f.recurrence_count > 1 else ""
            lines.append(f"- **[{f.id}]** {f.title}{loc}{recur}")
            if f.recommendation:
                lines.append(f"  - {f.recommendation}")
    else:
        lines.append("All clear.")
    lines.append("")

    # Healthy
    lines.append("### Healthy")
    healthy_notes: list[str] = []
    if not critical:
        healthy_notes.append("No critical findings")
    for r in reports:
        if not any(f.severity in ("critical", "high") for f in r.findings):
            healthy_notes.append(
                f"{r.agent}: clean scan ({r.scan_duration_seconds:.1f}s)"
            )
    if not healthy_notes:
        healthy_notes.append("Some areas need attention — see above")
    for note in healthy_notes:
        lines.append(f"- {note}")
    lines.append("")

    # Metrics
    lines.append("### Metrics")
    # Tech debt score: weighted sum of findings
    debt_score = sum(SEVERITY_WEIGHTS.get(f.severity, 0) for f in all_findings)
    debt_trend = learning.get_trend(AGENT_NAME, "debt_score")
    lines.append(f"- **Tech debt score:** {debt_score} ({debt_trend})")

    # Coverage
    for r in reports:
        if "coverage_percent" in r.metrics:
            lines.append(f"- **Test coverage:** {r.metrics['coverage_percent']}%")
            break

    # Open findings
    sev_str = ", ".join(f"{v} {k}" for k, v in sorted(sev_counts.items()))
    lines.append(f"- **Open findings:** {len(all_findings)} ({sev_str})")

    # AI cost
    for r in reports:
        cost = r.metrics.get("estimated_monthly_cost_1k_users")
        if cost is not None:
            lines.append(f"- **Est. AI cost (1K users):** ${cost}/mo")
            break

    # Scan summary
    total_duration = sum(r.scan_duration_seconds for r in reports)
    lines.append(
        f"- **Scan duration:** {total_duration:.1f}s across {len(reports)} agents"
    )
    lines.append("")

    # Recommendations
    lines.append("### Recommendations")
    # Auto-generate 1-2 strategic recommendations
    recommendations: list[str] = []
    if debt_score > 50:
        recommendations.append(
            "Consider dedicating a session to tech debt reduction — "
            f"debt score ({debt_score}) is elevated."
        )
    chronic = [f for f in all_findings if f.recurrence_count >= 3]
    if chronic:
        top_chronic = chronic[0]
        recommendations.append(
            f"Recurring issue: [{top_chronic.id}] {top_chronic.title} "
            f"(seen {top_chronic.recurrence_count}x). Consider fixing permanently."
        )
    auto_fixable = [f for f in all_findings if f.auto_fixable]
    if len(auto_fixable) >= 3:
        recommendations.append(
            f"{len(auto_fixable)} findings are auto-fixable — "
            "consider running `ruff check --fix .` and `ruff format .`."
        )
    if not recommendations:
        recommendations.append("Codebase is in good shape. Keep shipping.")

    for rec in recommendations[:2]:
        lines.append(f"- {rec}")
    lines.append("")

    # Low-priority items (collapsed)
    if low:
        lines.append(f"<details><summary>{len(low)} low-priority items</summary>\n")
        for f in low[:MAX_FINDINGS_PER_BRIEF]:
            lines.append(f"- [{f.id}] {f.title}")
        if len(low) > MAX_FINDINGS_PER_BRIEF:
            lines.append(f"- ... and {len(low) - MAX_FINDINGS_PER_BRIEF} more")
        lines.append("\n</details>")

    # KPI snapshot (supplementary — don't break the brief if it fails)
    try:
        from agents.shared.kpis import compute_kpis, render_kpi_summary

        dashboard = compute_kpis(reports)
        lines.append("")
        lines.append(render_kpi_summary(dashboard))
    except Exception:
        pass

    return "\n".join(lines)


def generate_weekly_report(reports: list[AgentReport] | None = None) -> str:
    """Generate a weekly trend report."""
    if reports is None:
        reports = _load_latest_reports()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"## Weekly Engineering Report — {today}\n")

    # Trends
    lines.append("### Trends")
    debt_trend = learning.get_trend(AGENT_NAME, "debt_score")
    lines.append(f"- **Tech debt:** {debt_trend}")
    for agent in [
        "test_engineer",
        "architect",
        "perf_monitor",
        "deps_manager",
        "doc_keeper",
    ]:
        total = learning.get_total_scans(agent)
        lines.append(f"- **{agent}:** {total} total scans")
    lines.append("")

    # Recurring patterns
    lines.append("### Recurring Patterns")
    all_findings = merge_reports(reports) if reports else []
    recurring = [f for f in all_findings if f.recurrence_count >= 2]
    if recurring:
        for f in sorted(recurring, key=lambda x: -x.recurrence_count)[:5]:
            lines.append(
                f"- [{f.id}] {f.title} — seen {f.recurrence_count}x since {f.first_seen}"
            )
    else:
        lines.append("No recurring patterns detected yet.")
    lines.append("")

    # Intelligence summary
    lines.append("### External Intelligence")
    for r in reports:
        for note in r.intelligence_applied:
            lines.append(f"- [{r.agent}] {note}")
    lines.append("")

    # KPI trends (supplementary — don't break the weekly report if it fails)
    try:
        from agents.shared.kpis import compute_kpis, render_kpi_trends

        dashboard = compute_kpis(reports)
        lines.append(render_kpi_trends(dashboard))
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-learning
# ---------------------------------------------------------------------------


def record_brief_metrics(findings: list[Finding]) -> None:
    """Record metrics for trend tracking."""
    debt_score = sum(SEVERITY_WEIGHTS.get(f.severity, 0) for f in findings)
    sev_counts = {}
    for f in findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

    learning.record_scan(
        AGENT_NAME,
        {
            "debt_score": debt_score,
            "total_findings": len(findings),
            "critical_count": sev_counts.get("critical", 0),
            "high_count": sev_counts.get("high", 0),
            "medium_count": sev_counts.get("medium", 0),
            "low_count": sev_counts.get("low", 0),
        },
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"

    if mode == "weekly":
        print(generate_weekly_report())
    else:
        print(generate_daily_brief())
