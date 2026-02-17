"""KPI engine — compute, grade, and render engineering KPIs from agent reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from agents.shared.config import (
    HEALTH_WEIGHTS,
    KPI_TARGETS,
    REPORTS_DIR,
    SEVERITY_WEIGHTS,
)
from agents.shared import learning
from agents.shared.report import AgentReport, Finding, merge_reports

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

Grade = Literal["green", "yellow", "red", "na"]

GRADE_ICON: dict[str, str] = {
    "green": "\u2705",
    "yellow": "\u26a0\ufe0f",
    "red": "\u274c",
    "na": "\u2b1c",
}
TREND_ICON: dict[str, str] = {
    "up": "\u2191",
    "down": "\u2193",
    "stable": "\u2192",
    "insufficient_data": "~",
}


@dataclass
class KPI:
    name: str
    description: str
    agent: str
    value: float | str | None
    target: float | str
    unit: str  # ratio | count | $/user/mo | score | bool | trend
    grade: Grade
    trend: str  # up | down | stable | insufficient_data
    higher_is_better: bool


@dataclass
class AgentKPIs:
    agent: str
    kpis: list[KPI]


@dataclass
class TeamKPIs:
    kpis: list[KPI]


@dataclass
class KPIDashboard:
    generated_at: str
    agent_kpis: list[AgentKPIs]
    team_kpis: TeamKPIs


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------


def _grade(
    value: float | None,
    target: float,
    *,
    higher_is_better: bool = True,
    hard_zero: bool = False,
    yellow: float | None = None,
) -> Grade:
    """Grade a numeric value against its target."""
    if value is None:
        return "na"
    if hard_zero:
        return "green" if value == 0 else "red"
    if higher_is_better:
        if value >= target:
            return "green"
        if yellow is not None and value >= yellow:
            return "yellow"
        return "red"
    else:
        if value <= target:
            return "green"
        if yellow is not None and value <= yellow:
            return "yellow"
        return "red"


def _grade_trend(trend: str, *, lower_is_better: bool = True) -> Grade:
    """Grade a trend string."""
    if trend == "insufficient_data":
        return "yellow"
    if lower_is_better:
        return "green" if trend in ("down", "stable") else "red"
    return "green" if trend in ("up", "stable") else "red"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _t(agent: str, name: str) -> dict:
    """Look up target config for a KPI."""
    return KPI_TARGETS.get((agent, name), {})


def _safe_div(a: float, b: float) -> float | None:
    """Safe division — returns None when divisor is zero."""
    return a / b if b else None


def _load_reports() -> list[AgentReport]:
    """Load cached *_latest.json reports from REPORTS_DIR."""
    reports: list[AgentReport] = []
    if not REPORTS_DIR.is_dir():
        return reports
    for path in sorted(REPORTS_DIR.glob("*_latest.json")):
        try:
            data = json.loads(path.read_text())
            reports.append(AgentReport.from_dict(data))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
    return reports


# ---------------------------------------------------------------------------
# Per-agent KPI computations
# ---------------------------------------------------------------------------


def _compute_architect_kpis(metrics: dict) -> list[KPI]:
    total_files = metrics.get("total_files_scanned", 0)
    total_funcs = metrics.get("total_functions", 0)
    kpis: list[KPI] = []

    # Lint Density
    t = _t("architect", "lint_density")
    val = _safe_div(metrics.get("lint_issues_count", 0), total_files)
    kpis.append(KPI(
        name="lint_density", description="Lint Density",
        agent="architect", value=val,
        target=t.get("target", 0.10), unit="ratio",
        grade=_grade(val, t.get("target", 0.10),
                     higher_is_better=False, yellow=t.get("yellow")),
        trend=learning.get_trend("architect", "lint_issues_count"),
        higher_is_better=False,
    ))

    # Large File Ratio
    t = _t("architect", "large_file_ratio")
    val = _safe_div(metrics.get("large_files_count", 0), total_files)
    kpis.append(KPI(
        name="large_file_ratio", description="Large File Ratio",
        agent="architect", value=val,
        target=t.get("target", 0.10), unit="ratio",
        grade=_grade(val, t.get("target", 0.10),
                     higher_is_better=False, yellow=t.get("yellow")),
        trend=learning.get_trend("architect", "large_files_count"),
        higher_is_better=False,
    ))

    # Type Coverage
    t = _t("architect", "type_coverage")
    missing = metrics.get("missing_return_types", 0)
    val = 1 - (missing / total_funcs) if total_funcs else None
    kpis.append(KPI(
        name="type_coverage", description="Type Coverage",
        agent="architect", value=val,
        target=t.get("target", 0.95), unit="ratio",
        grade=_grade(val, t.get("target", 0.95),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("architect", "missing_return_types"),
        higher_is_better=True,
    ))

    return kpis


def _compute_test_kpis(metrics: dict) -> list[KPI]:
    total = metrics.get("total_tests", 0)
    files = metrics.get("total_test_files", 0)
    kpis: list[KPI] = []

    # Test Count
    t = _t("test_engineer", "test_count")
    kpis.append(KPI(
        name="test_count", description="Test Count",
        agent="test_engineer", value=total,
        target=t.get("target", 750), unit="count",
        grade=_grade(total, t.get("target", 750),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("test_engineer", "total_tests"),
        higher_is_better=True,
    ))

    # Weak Test Ratio
    t = _t("test_engineer", "weak_test_ratio")
    val = _safe_div(metrics.get("weak_test_count", 0), total)
    kpis.append(KPI(
        name="weak_test_ratio", description="Weak Test Ratio",
        agent="test_engineer", value=val,
        target=t.get("target", 0.30), unit="ratio",
        grade=_grade(val, t.get("target", 0.30),
                     higher_is_better=False, yellow=t.get("yellow")),
        trend=learning.get_trend("test_engineer", "weak_test_count"),
        higher_is_better=False,
    ))

    # Tests Per File
    t = _t("test_engineer", "tests_per_file")
    val = _safe_div(total, files)
    kpis.append(KPI(
        name="tests_per_file", description="Tests Per File",
        agent="test_engineer", value=val,
        target=t.get("target", 25), unit="count",
        grade=_grade(val, t.get("target", 25),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("test_engineer", "total_tests"),
        higher_is_better=True,
    ))

    return kpis


def _compute_perf_kpis(metrics: dict) -> list[KPI]:
    kpis: list[KPI] = []

    # N+1 Count
    val = metrics.get("n_plus_1_patterns", 0)
    kpis.append(KPI(
        name="n_plus_1_count", description="N+1 Count",
        agent="perf_monitor", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("perf_monitor", "n_plus_1_patterns"),
        higher_is_better=False,
    ))

    # Index Coverage
    t = _t("perf_monitor", "index_coverage")
    indexed = metrics.get("indexed_columns", 0)
    unindexed = metrics.get("unindexed_query_columns", 0)
    val = _safe_div(indexed, indexed + unindexed)
    kpis.append(KPI(
        name="index_coverage", description="Index Coverage",
        agent="perf_monitor", value=val,
        target=t.get("target", 0.80), unit="ratio",
        grade=_grade(val, t.get("target", 0.80),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("perf_monitor", "unindexed_query_columns"),
        higher_is_better=True,
    ))

    # AI Cost/User/Mo
    t = _t("perf_monitor", "ai_cost_per_user")
    val = metrics.get("cost_per_user_per_month")
    kpis.append(KPI(
        name="ai_cost_per_user", description="AI Cost/User/Mo",
        agent="perf_monitor", value=val,
        target=t.get("target", 0.50), unit="$/user/mo",
        grade=_grade(val, t.get("target", 0.50),
                     higher_is_better=False, yellow=t.get("yellow"))
        if val is not None else "na",
        trend=learning.get_trend("perf_monitor", "cost_per_user_per_month"),
        higher_is_better=False,
    ))

    return kpis


def _compute_deps_kpis(metrics: dict) -> list[KPI]:
    kpis: list[KPI] = []

    # CVE Count
    val = metrics.get("cve_count", 0)
    kpis.append(KPI(
        name="cve_count", description="CVE Count",
        agent="deps_manager", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("deps_manager", "cve_count"),
        higher_is_better=False,
    ))

    # Pin Ratio
    t = _t("deps_manager", "pin_ratio")
    val = _safe_div(metrics.get("pinned_count", 0), metrics.get("total_deps", 0))
    kpis.append(KPI(
        name="pin_ratio", description="Pin Ratio",
        agent="deps_manager", value=val,
        target=t.get("target", 1.0), unit="ratio",
        grade=_grade(val, t.get("target", 1.0),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("deps_manager", "pinned_count"),
        higher_is_better=True,
    ))

    # Dead Dep Count
    val = metrics.get("dead_deps", 0)
    kpis.append(KPI(
        name="dead_dep_count", description="Dead Dep Count",
        agent="deps_manager", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("deps_manager", "dead_deps"),
        higher_is_better=False,
    ))

    return kpis


def _compute_doc_kpis(metrics: dict) -> list[KPI]:
    kpis: list[KPI] = []

    # Doc Coverage
    t = _t("doc_keeper", "doc_coverage")
    val = _safe_div(
        metrics.get("documented_endpoints", 0),
        metrics.get("total_endpoints", 0),
    )
    kpis.append(KPI(
        name="doc_coverage", description="Doc Coverage",
        agent="doc_keeper", value=val,
        target=t.get("target", 0.90), unit="ratio",
        grade=_grade(val, t.get("target", 0.90),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("doc_keeper", "documented_endpoints"),
        higher_is_better=True,
    ))

    # Claims Accuracy
    t = _t("doc_keeper", "claims_accuracy")
    verified = metrics.get("doc_claims_verified", 0)
    mismatched = metrics.get("doc_claims_mismatched", 0)
    val = _safe_div(verified, verified + mismatched)
    kpis.append(KPI(
        name="claims_accuracy", description="Claims Accuracy",
        agent="doc_keeper", value=val,
        target=t.get("target", 1.0), unit="ratio",
        grade=_grade(val, t.get("target", 1.0),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("doc_keeper", "doc_claims_mismatched"),
        higher_is_better=True,
    ))

    # Convention Violations
    val = metrics.get("convention_violations", 0)
    kpis.append(KPI(
        name="convention_violations", description="Convention Violations",
        agent="doc_keeper", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("doc_keeper", "convention_violations"),
        higher_is_better=False,
    ))

    return kpis


def _compute_security_kpis(metrics: dict) -> list[KPI]:
    kpis: list[KPI] = []

    # Critical + High
    val = metrics.get("critical_count", 0) + metrics.get("high_count", 0)
    kpis.append(KPI(
        name="critical_high", description="Critical+High",
        agent="security", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("security", "high_count"),
        higher_is_better=False,
    ))

    # Medium Findings
    t = _t("security", "medium_findings")
    val = metrics.get("medium_count", 0)
    kpis.append(KPI(
        name="medium_findings", description="Medium Findings",
        agent="security", value=val,
        target=t.get("target", 5), unit="count",
        grade=_grade(val, t.get("target", 5),
                     higher_is_better=False, yellow=t.get("yellow")),
        trend=learning.get_trend("security", "medium_count"),
        higher_is_better=False,
    ))

    # Finding Trend
    trend = learning.get_trend("security", "total_findings")
    kpis.append(KPI(
        name="finding_trend", description="Finding Trend",
        agent="security", value=trend,
        target="down/stable", unit="trend",
        grade=_grade_trend(trend, lower_is_better=True),
        trend=trend,
        higher_is_better=False,
    ))

    return kpis


def _compute_privy_kpis(metrics: dict) -> list[KPI]:
    kpis: list[KPI] = []

    # Critical + High
    val = metrics.get("critical_count", 0) + metrics.get("high_count", 0)
    kpis.append(KPI(
        name="critical_high", description="Critical+High",
        agent="privy", value=val,
        target=0, unit="count",
        grade=_grade(val, 0, hard_zero=True),
        trend=learning.get_trend("privy", "high_count"),
        higher_is_better=False,
    ))

    # Check Pass Rate
    t = _t("privy", "check_pass_rate")
    checks = metrics.get("checks_run", 0)
    findings = metrics.get("total_findings", 0)
    val = _safe_div(checks - findings, checks)
    kpis.append(KPI(
        name="check_pass_rate", description="Check Pass Rate",
        agent="privy", value=val,
        target=t.get("target", 0.90), unit="ratio",
        grade=_grade(val, t.get("target", 0.90),
                     higher_is_better=True, yellow=t.get("yellow")),
        trend=learning.get_trend("privy", "total_findings"),
        higher_is_better=True,
    ))

    return kpis


# ---------------------------------------------------------------------------
# Team KPIs + health score
# ---------------------------------------------------------------------------

_COMPUTE_FNS = {
    "architect": _compute_architect_kpis,
    "test_engineer": _compute_test_kpis,
    "perf_monitor": _compute_perf_kpis,
    "deps_manager": _compute_deps_kpis,
    "doc_keeper": _compute_doc_kpis,
    "security": _compute_security_kpis,
    "privy": _compute_privy_kpis,
}


def _compute_health_score(agent_kpis: list[AgentKPIs]) -> float:
    """Weighted composite health score (0-100)."""
    total = 0.0
    for ak in agent_kpis:
        weight = HEALTH_WEIGHTS.get(ak.agent, 0)
        if not weight:
            continue
        non_na = [k for k in ak.kpis if k.grade != "na"]
        if not non_na:
            continue
        score_sum = sum(
            1.0 if k.grade == "green" else 0.5 if k.grade == "yellow" else 0.0
            for k in non_na
        )
        total += (score_sum / len(non_na)) * weight
    return round(total, 1)


def _compute_team_kpis(
    findings: list[Finding], agent_kpis: list[AgentKPIs]
) -> TeamKPIs:
    kpis: list[KPI] = []

    # Tech Debt Score
    debt = sum(SEVERITY_WEIGHTS.get(f.severity, 0) for f in findings)
    debt_trend = learning.get_trend("lead", "debt_score")
    kpis.append(KPI(
        name="tech_debt_score", description="Tech Debt Score",
        agent="team", value=debt,
        target=50, unit="score",
        grade=_grade(debt, 50, higher_is_better=False, yellow=100),
        trend=debt_trend,
        higher_is_better=False,
    ))

    # Debt Trend
    kpis.append(KPI(
        name="debt_trend", description="Debt Trend",
        agent="team", value=debt_trend,
        target="down/stable", unit="trend",
        grade=_grade_trend(debt_trend, lower_is_better=True),
        trend=debt_trend,
        higher_is_better=False,
    ))

    # Zero Criticals (shown as count)
    crit_count = sum(1 for f in findings if f.severity == "critical")
    kpis.append(KPI(
        name="zero_criticals", description="Critical Findings",
        agent="team", value=crit_count,
        target=0, unit="count",
        grade=_grade(crit_count, 0, hard_zero=True),
        trend="stable",
        higher_is_better=False,
    ))

    # Chronic Issues
    chronic = sum(1 for f in findings if f.recurrence_count >= 3)
    kpis.append(KPI(
        name="chronic_issues", description="Chronic Issues (3+ recurrences)",
        agent="team", value=chronic,
        target=0, unit="count",
        grade=_grade(chronic, 0, hard_zero=True),
        trend="stable",
        higher_is_better=False,
    ))

    # Overall Health
    health = _compute_health_score(agent_kpis)
    kpis.append(KPI(
        name="overall_health", description="Overall Health",
        agent="team", value=health,
        target=80, unit="score",
        grade=_grade(health, 80, higher_is_better=True, yellow=60),
        trend=learning.get_trend("lead", "health_score"),
        higher_is_better=True,
    ))

    return TeamKPIs(kpis=kpis)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def compute_kpis(reports: list[AgentReport] | None = None) -> KPIDashboard:
    """Compute all KPIs from agent reports (loads cached if none passed)."""
    if reports is None:
        reports = _load_reports()

    metrics_by_agent = {r.agent: r.metrics for r in reports}

    agent_kpis: list[AgentKPIs] = []
    for agent_name, fn in _COMPUTE_FNS.items():
        kpis = fn(metrics_by_agent.get(agent_name, {}))
        agent_kpis.append(AgentKPIs(agent=agent_name, kpis=kpis))

    all_findings = merge_reports(reports) if reports else []
    team = _compute_team_kpis(all_findings, agent_kpis)

    return KPIDashboard(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        agent_kpis=agent_kpis,
        team_kpis=team,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_value(kpi: KPI) -> str:
    """Format a KPI value for display."""
    v = kpi.value
    if v is None:
        return "N/A"
    if kpi.unit == "ratio" and isinstance(v, (int, float)):
        return f"{v * 100:.1f}%"
    if kpi.unit == "$/user/mo" and isinstance(v, (int, float)):
        return f"${v:.3f}"
    if kpi.unit == "trend":
        return TREND_ICON.get(str(v), str(v))
    if kpi.unit == "bool":
        return str(v)
    # count, score
    if isinstance(v, float):
        return f"{v:.1f}" if v != int(v) else str(int(v))
    return str(v)


def _fmt_target(kpi: KPI) -> str:
    """Format a KPI target for display."""
    t = kpi.target
    if kpi.unit in ("bool", "trend"):
        return str(t)
    if isinstance(t, (int, float)) and t == 0 and not kpi.higher_is_better:
        return "0"
    op = "\u2265" if kpi.higher_is_better else "<"
    if kpi.unit == "ratio" and isinstance(t, (int, float)):
        return f"{op} {t * 100:.0f}%"
    if kpi.unit == "$/user/mo" and isinstance(t, (int, float)):
        return f"{op} ${t:.2f}"
    return f"{op} {t}"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_dashboard(dashboard: KPIDashboard) -> str:
    """Full markdown dashboard — one table per agent + team summary."""
    lines = [f"## KPI Dashboard \u2014 {dashboard.generated_at}\n"]

    for ak in dashboard.agent_kpis:
        lines.append(f"### {ak.agent}")
        lines.append("| KPI | Value | Target | Grade | Trend |")
        lines.append("|-----|-------|--------|-------|-------|")
        for k in ak.kpis:
            icon = GRADE_ICON[k.grade]
            trend = TREND_ICON.get(k.trend, k.trend)
            lines.append(
                f"| {k.description} | {_fmt_value(k)} | {_fmt_target(k)} "
                f"| {icon} | {trend} |"
            )
        lines.append("")

    lines.append("### Team")
    lines.append("| KPI | Value | Target | Grade | Trend |")
    lines.append("|-----|-------|--------|-------|-------|")
    for k in dashboard.team_kpis.kpis:
        icon = GRADE_ICON[k.grade]
        trend = TREND_ICON.get(k.trend, k.trend)
        lines.append(
            f"| {k.description} | {_fmt_value(k)} | {_fmt_target(k)} "
            f"| {icon} | {trend} |"
        )
    lines.append("")

    # Summary line
    all_kpis = [k for ak in dashboard.agent_kpis for k in ak.kpis]
    greens = sum(1 for k in all_kpis if k.grade == "green")
    yellows = sum(1 for k in all_kpis if k.grade == "yellow")
    reds = sum(1 for k in all_kpis if k.grade == "red")
    lines.append(f"**Summary:** {greens} \u2705 | {yellows} \u26a0\ufe0f | {reds} \u274c")

    return "\n".join(lines)


def render_kpi_summary(dashboard: KPIDashboard) -> str:
    """3-line compact snapshot for the daily brief."""
    health = next(
        (k for k in dashboard.team_kpis.kpis if k.name == "overall_health"), None
    )
    debt = next(
        (k for k in dashboard.team_kpis.kpis if k.name == "tech_debt_score"), None
    )
    criticals = next(
        (k for k in dashboard.team_kpis.kpis if k.name == "zero_criticals"), None
    )

    all_kpis = [k for ak in dashboard.agent_kpis for k in ak.kpis]
    greens = sum(1 for k in all_kpis if k.grade == "green")
    yellows = sum(1 for k in all_kpis if k.grade == "yellow")
    reds = sum(1 for k in all_kpis if k.grade == "red")

    red_kpis = [k for ak in dashboard.agent_kpis for k in ak.kpis if k.grade == "red"]
    risk_names = [f"{k.agent}/{k.name}" for k in red_kpis[:3]]

    lines = ["### KPI Snapshot"]

    parts: list[str] = []
    if health:
        parts.append(
            f"**Health:** {_fmt_value(health)}/100 {GRADE_ICON[health.grade]}"
        )
    if debt:
        parts.append(f"**Debt:** {_fmt_value(debt)} {GRADE_ICON[debt.grade]}")
    if criticals:
        parts.append(
            f"**Criticals:** {_fmt_value(criticals)} {GRADE_ICON[criticals.grade]}"
        )
    if parts:
        lines.append("- " + " | ".join(parts))

    lines.append(f"- {greens} \u2705 | {yellows} \u26a0\ufe0f | {reds} \u274c")

    if risk_names:
        lines.append(f"- Top risks: {', '.join(risk_names)}")

    return "\n".join(lines)


def render_kpi_trends(dashboard: KPIDashboard) -> str:
    """Yellow/red KPIs with trends — for the weekly report."""
    lines = ["### KPI Trends (Attention Needed)"]
    lines.append("| Agent | KPI | Value | Target | Grade | Trend |")
    lines.append("|-------|-----|-------|--------|-------|-------|")

    has_rows = False
    for ak in dashboard.agent_kpis:
        for k in ak.kpis:
            if k.grade in ("yellow", "red"):
                icon = GRADE_ICON[k.grade]
                trend = TREND_ICON.get(k.trend, k.trend)
                lines.append(
                    f"| {k.agent} | {k.description} | {_fmt_value(k)} "
                    f"| {_fmt_target(k)} | {icon} | {trend} |"
                )
                has_rows = True

    for k in dashboard.team_kpis.kpis:
        if k.grade in ("yellow", "red"):
            icon = GRADE_ICON[k.grade]
            trend = TREND_ICON.get(k.trend, k.trend)
            lines.append(
                f"| team | {k.description} | {_fmt_value(k)} "
                f"| {_fmt_target(k)} | {icon} | {trend} |"
            )
            has_rows = True

    if not has_rows:
        lines.append("| | All KPIs green! | | | \u2705 | |")

    return "\n".join(lines)
