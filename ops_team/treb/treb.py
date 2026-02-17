"""Treb agent -- Network Holder Partner Auditor.

Audits the supply-side (network holder) experience: CSV upload, marketplace
sharing controls, intro facilitation, frontend supply pages, and engagement
touchpoints.

Scans:
  - app/api/contacts.py
  - app/api/marketplace.py
  - app/services/marketplace_indexer.py
  - frontend/src/pages/*.jsx
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from ops_team.shared.config import (
    API_DIR,
    FRONTEND_SRC,
    NH_JOURNEY_STEPS,
    PAGES_DIR,
    REPORTS_DIR,
    SERVICES_DIR,
)
from ops_team.shared.learning import OpsLearningState
from ops_team.shared.report import OpsInsight, OpsTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "treb"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read file contents, returning empty string on failure."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    """Return path relative to the project root for display."""
    try:
        return str(path.relative_to(FRONTEND_SRC.parent.parent))
    except ValueError:
        return str(path)


def _find_jsx_files() -> list[Path]:
    """Return all .jsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted(PAGES_DIR.rglob("*.jsx"))


# ---------------------------------------------------------------------------
# Check 1 — NH Journey Completeness
# ---------------------------------------------------------------------------

# Patterns that indicate each journey step is implemented.
_JOURNEY_PATTERNS: dict[str, list[str]] = {
    "signup": [r"/signup", r"register", r"create.*account"],
    "upload_csv": [r"/upload", r"csv", r"file.*upload"],
    "opt_in": [r"opt.?in", r"sharing", r"marketplace.*share"],
    "review_intros": [r"approve", r"decline", r"review.*intro"],
    "earn": [r"credit", r"earn", r"bonus", r"reward"],
}


def _check_nh_journey(
    api_sources: dict[str, str],
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Verify that each NH_JOURNEY_STEP has backend support."""
    combined_source = "\n".join(api_sources.values()).lower()
    covered: list[str] = []
    gaps: list[str] = []

    for step in NH_JOURNEY_STEPS:
        patterns = _JOURNEY_PATTERNS.get(step, [])
        found = any(re.search(p, combined_source) for p in patterns)
        if found:
            covered.append(step)
        else:
            gaps.append(step)

    coverage = len(covered) / max(1, len(NH_JOURNEY_STEPS))
    metrics["nh_journey_steps_total"] = len(NH_JOURNEY_STEPS)
    metrics["nh_journey_steps_covered"] = len(covered)
    metrics["nh_journey_coverage"] = round(coverage, 2)
    metrics["nh_journey_gaps"] = gaps

    if gaps:
        findings.append(Finding(
            id="treb-001",
            severity="high",
            category="nh_journey",
            title=f"NH journey gaps: {', '.join(gaps)}",
            detail=(
                f"{len(gaps)}/{len(NH_JOURNEY_STEPS)} journey steps lack "
                f"backend support. Covered: {', '.join(covered) or 'none'}."
            ),
            recommendation="Implement missing journey steps to complete the NH funnel.",
        ))

    if coverage >= 0.8:
        insights.append(OpsInsight(
            id="treb-ins-001",
            category="supply_activation",
            title="NH journey is mostly complete",
            evidence=f"{len(covered)}/{len(NH_JOURNEY_STEPS)} steps covered",
            impact="Network holders can complete the core loop",
            recommendation="Focus on polishing the remaining gaps",
            confidence=coverage,
            persona="network_holder",
            actionable_by="engineering",
        ))


# ---------------------------------------------------------------------------
# Check 2 — Sharing Controls
# ---------------------------------------------------------------------------

_SHARING_CONTROL_PATTERNS: dict[str, list[str]] = {
    "opt_in_marketplace": [r"opt.?in.?marketplace", r"opt.?in"],
    "category_filter": [r"category.?filter", r"category", r"filter.*share"],
    "individual_exclusion": [
        r"individual.?exclusion",
        r"exclude.*contact",
        r"exclusion",
    ],
    "pause_unpause": [r"pause", r"unpause", r"suspend.*sharing"],
}


def _check_sharing_controls(
    marketplace_source: str,
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Check marketplace API/service for the four sharing controls."""
    source_lower = marketplace_source.lower()
    controls_found: list[str] = []
    controls_missing: list[str] = []

    for control, patterns in _SHARING_CONTROL_PATTERNS.items():
        found = any(re.search(p, source_lower) for p in patterns)
        if found:
            controls_found.append(control)
        else:
            controls_missing.append(control)

    metrics["sharing_controls_total"] = len(_SHARING_CONTROL_PATTERNS)
    metrics["sharing_controls_found"] = len(controls_found)
    metrics["sharing_controls_found_list"] = controls_found
    metrics["sharing_controls_missing"] = controls_missing

    if controls_missing:
        findings.append(Finding(
            id="treb-002",
            severity="medium",
            category="sharing_controls",
            title=f"Missing sharing controls: {', '.join(controls_missing)}",
            detail=(
                f"{len(controls_missing)}/{len(_SHARING_CONTROL_PATTERNS)} "
                f"sharing controls not detected in marketplace code."
            ),
            recommendation=(
                "Implement missing controls so network holders have "
                "granular sharing options per CLAUDE.md spec."
            ),
        ))

    if len(controls_found) == len(_SHARING_CONTROL_PATTERNS):
        insights.append(OpsInsight(
            id="treb-ins-002",
            category="supply_activation",
            title="All sharing controls present",
            evidence=f"All {len(controls_found)} controls detected",
            impact="Network holders have full granular sharing control",
            recommendation="Monitor usage of each control for optimisation",
            confidence=1.0,
            persona="network_holder",
            actionable_by="product",
        ))


# ---------------------------------------------------------------------------
# Check 3 — Intro Facilitation Flow
# ---------------------------------------------------------------------------

_FACILITATION_PATTERNS: dict[str, list[str]] = {
    "request_intro": [r"request.?intro", r"intro.*request", r"create.*intro"],
    "approve_intro": [r"approve.?intro", r"approve", r"accept.*intro"],
    "decline_intro": [r"decline.?intro", r"decline", r"reject.*intro"],
}

_STATUS_KEYWORDS = ["pending", "approved", "declined"]


def _check_intro_facilitation(
    marketplace_source: str,
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for request/approve/decline endpoints and status tracking."""
    source_lower = marketplace_source.lower()
    endpoints_found: list[str] = []
    endpoints_missing: list[str] = []

    for endpoint, patterns in _FACILITATION_PATTERNS.items():
        found = any(re.search(p, source_lower) for p in patterns)
        if found:
            endpoints_found.append(endpoint)
        else:
            endpoints_missing.append(endpoint)

    # Status tracking
    statuses_found = [s for s in _STATUS_KEYWORDS if s in source_lower]

    metrics["facilitation_endpoints_total"] = len(_FACILITATION_PATTERNS)
    metrics["facilitation_endpoints_found"] = len(endpoints_found)
    metrics["facilitation_endpoints_missing"] = endpoints_missing
    metrics["facilitation_statuses_found"] = statuses_found

    if endpoints_missing:
        findings.append(Finding(
            id="treb-003",
            severity="high",
            category="intro_facilitation",
            title=f"Missing facilitation endpoints: {', '.join(endpoints_missing)}",
            detail=(
                f"{len(endpoints_missing)}/{len(_FACILITATION_PATTERNS)} "
                f"intro lifecycle endpoints not detected. "
                f"Found: {', '.join(endpoints_found) or 'none'}."
            ),
            recommendation=(
                "Implement missing intro lifecycle endpoints so network "
                "holders can manage intro requests."
            ),
        ))

    if len(statuses_found) < len(_STATUS_KEYWORDS):
        missing_statuses = [s for s in _STATUS_KEYWORDS if s not in statuses_found]
        findings.append(Finding(
            id="treb-004",
            severity="medium",
            category="intro_facilitation",
            title=f"Missing intro status tracking: {', '.join(missing_statuses)}",
            detail=(
                "Intro status lifecycle should track pending, approved, "
                "and declined states for proper funnel instrumentation."
            ),
            recommendation="Add status column/enum with all lifecycle states.",
        ))


# ---------------------------------------------------------------------------
# Check 4 — Frontend Supply-Side Pages
# ---------------------------------------------------------------------------

_SUPPLY_KEYWORDS = re.compile(
    r"(?:contact|sharing|marketplace|upload|referral.?bonus|connector|network.?holder|"
    r"my.?network|share.*contact|intro.*facilit|opt.?in)",
    re.IGNORECASE,
)


def _check_frontend_supply_pages(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Count JSX pages that serve the supply-side (network holder) persona."""
    supply_pages: list[str] = []

    for path in jsx_files:
        source = _read_safe(path)
        if not source:
            continue
        if _SUPPLY_KEYWORDS.search(source):
            supply_pages.append(_relative(path))

    metrics["frontend_pages_total"] = len(jsx_files)
    metrics["frontend_supply_pages"] = len(supply_pages)
    metrics["frontend_supply_page_list"] = supply_pages

    if not supply_pages and jsx_files:
        findings.append(Finding(
            id="treb-005",
            severity="medium",
            category="frontend_supply",
            title="No supply-side pages detected in frontend",
            detail=(
                f"{len(jsx_files)} JSX pages scanned but none contain "
                "supply-side keywords (contacts, sharing, upload, etc.)."
            ),
            recommendation=(
                "Ensure frontend has dedicated pages for the network "
                "holder journey: upload, sharing controls, intro review."
            ),
        ))
    elif supply_pages:
        insights.append(OpsInsight(
            id="treb-ins-003",
            category="supply_activation",
            title=f"{len(supply_pages)} supply-side pages detected",
            evidence=f"Pages: {', '.join(p.split('/')[-1] for p in supply_pages[:5])}",
            impact="Network holders have frontend touchpoints for the core loop",
            recommendation="Verify each page maps to a journey step",
            confidence=0.8,
            persona="network_holder",
            actionable_by="product",
        ))


# ---------------------------------------------------------------------------
# Check 5 — Engagement Touchpoints
# ---------------------------------------------------------------------------

_ENGAGEMENT_PATTERNS: dict[str, list[str]] = {
    "welcome_email": [r"welcome", r"onboard", r"getting.?started"],
    "upload_confirmation": [r"upload.*confirm", r"upload.*success", r"csv.*processed"],
    "intro_notification": [r"intro.*notif", r"new.*request", r"pending.*intro"],
    "earn_notification": [r"earn.*notif", r"credit.*earned", r"bonus.*earned"],
    "reputation_display": [r"reputation", r"connector.*score", r"facilitator.*score"],
    "leaderboard": [r"leaderboard", r"top.*connector", r"ranking"],
}


def _check_engagement_touchpoints(
    api_sources: dict[str, str],
    jsx_files: list[Path],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Check for engagement/notification patterns across API and frontend."""
    # Combine all source material
    combined = "\n".join(api_sources.values()).lower()
    for path in jsx_files:
        combined += "\n" + _read_safe(path).lower()

    found: list[str] = []
    missing: list[str] = []

    for touchpoint, patterns in _ENGAGEMENT_PATTERNS.items():
        if any(re.search(p, combined) for p in patterns):
            found.append(touchpoint)
        else:
            missing.append(touchpoint)

    metrics["engagement_touchpoints_total"] = len(_ENGAGEMENT_PATTERNS)
    metrics["engagement_touchpoints_found"] = len(found)
    metrics["engagement_touchpoints_found_list"] = found
    metrics["engagement_touchpoints_missing"] = missing

    if missing:
        findings.append(Finding(
            id="treb-006",
            severity="medium",
            category="engagement",
            title=f"Missing engagement touchpoints: {', '.join(missing)}",
            detail=(
                f"{len(missing)}/{len(_ENGAGEMENT_PATTERNS)} engagement "
                f"touchpoints not detected. Found: {', '.join(found) or 'none'}."
            ),
            recommendation=(
                "Add missing engagement hooks to keep network holders "
                "active and informed about their contribution value."
            ),
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> OpsTeamReport:
    """Run all supply-side checks and return an OpsTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[OpsInsight] = []
    metrics: dict = {}

    # ---- Read API source files --------------------------------------------

    api_files: dict[str, Path] = {
        "contacts": API_DIR / "contacts.py",
        "marketplace": API_DIR / "marketplace.py",
    }

    api_sources: dict[str, str] = {}
    for key, path in api_files.items():
        source = _read_safe(path)
        if source:
            api_sources[key] = source
        else:
            findings.append(Finding(
                id=f"treb-src-{key}",
                severity="info",
                category="source_availability",
                title=f"Could not read {_relative(path)}",
                detail=f"File not found or unreadable: {path}",
                file=_relative(path),
                recommendation="Verify the file exists at the expected path.",
            ))

    # ---- Read service file ------------------------------------------------

    indexer_path = SERVICES_DIR / "marketplace_indexer.py"
    indexer_source = _read_safe(indexer_path)
    if indexer_source:
        api_sources["indexer"] = indexer_source

    # Build combined marketplace source (API + service)
    marketplace_combined = api_sources.get("marketplace", "")
    if indexer_source:
        marketplace_combined += "\n" + indexer_source

    # ---- Read JSX files ---------------------------------------------------

    jsx_files = _find_jsx_files()
    metrics["jsx_pages_scanned"] = len(jsx_files)

    # ---- Run checks -------------------------------------------------------

    if not api_sources:
        findings.append(Finding(
            id="treb-000",
            severity="high",
            category="nh_journey",
            title="No API source files readable",
            detail="Could not read any API files; all checks skipped.",
            recommendation="Ensure app/api/ directory and files exist.",
        ))
    else:
        _check_nh_journey(api_sources, findings, insights, metrics)
        _check_sharing_controls(marketplace_combined, findings, insights, metrics)
        _check_intro_facilitation(marketplace_combined, findings, metrics)

    _check_frontend_supply_pages(jsx_files, findings, insights, metrics)
    _check_engagement_touchpoints(api_sources, jsx_files, findings, metrics)

    # ---- Compute supply-side health score ---------------------------------

    severity_penalty = {
        "critical": 20,
        "high": 10,
        "medium": 3,
        "low": 1,
        "info": 0,
    }
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    metrics["supply_health_score"] = round(health, 1)

    duration = time.time() - start

    # ---- Learning updates -------------------------------------------------

    ls = OpsLearningState(AGENT_NAME)
    ls.record_scan(metrics)

    file_findings: dict[str, int] = {}
    for f in findings:
        ls.record_finding({
            "id": f.id,
            "severity": f.severity,
            "category": f.category,
            "title": f.title,
            "file": f.file,
        })
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1

    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    for ins in insights:
        ls.record_insight({
            "id": ins.id,
            "category": ins.category,
            "title": ins.title,
            "confidence": ins.confidence,
        })

    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    journey_coverage = metrics.get("nh_journey_coverage", 0)
    ls.track_kpi("nh_journey_coverage", journey_coverage)
    ls.track_kpi("sharing_controls_found", metrics.get("sharing_controls_found", 0))
    ls.track_kpi("supply_pages", metrics.get("frontend_supply_pages", 0))
    ls.track_kpi("supply_health_score", health)

    learning_updates: list[str] = [
        f"Scanned {len(api_sources)} API files + {len(jsx_files)} JSX pages, "
        f"supply health={health}",
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return OpsTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        ops_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: OpsTeamReport) -> Path:
    """Save report JSON to ops_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
