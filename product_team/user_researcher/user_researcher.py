"""UserResearcher agent — source catalog, persona management, research framework, journey mapping.

Scans frontend pages and CLAUDE.md to map user journeys and identify gaps.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from agents.shared.web_tools import web_search
from product_team.shared.config import (
    API_DIR,
    FRONTEND_SRC,
    PAGES_DIR,
    PERSONAS,
    PROJECT_ROOT,
)
from product_team.shared.learning import ProductLearningState
from product_team.shared.report import ProductInsight, ProductTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "user_researcher"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_page_files() -> list[Path]:
    """Return all .jsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted(PAGES_DIR.glob("*.jsx"))


def _read_safe(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _page_name(path: Path) -> str:
    """Extract page name from file (e.g., Dashboard.jsx -> Dashboard)."""
    return path.stem


# ---------------------------------------------------------------------------
# Journey mapping
# ---------------------------------------------------------------------------


def _map_user_journeys(
    page_files: list[Path],
    insights: list[ProductInsight],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Map pages to personas and identify journey gaps."""
    actual_pages = {_page_name(p) for p in page_files}
    metrics["pages_found"] = len(actual_pages)

    for persona_id, persona in PERSONAS.items():
        expected = set(persona.get("key_pages", []))
        found = expected & actual_pages
        missing = expected - actual_pages
        coverage = len(found) / max(1, len(expected))

        metrics[f"{persona_id}_page_coverage"] = round(coverage, 2)
        metrics[f"{persona_id}_pages_found"] = len(found)
        metrics[f"{persona_id}_pages_expected"] = len(expected)

        if missing:
            findings.append(
                Finding(
                    id=f"ur-journey-{persona_id}",
                    severity="medium" if len(missing) > 2 else "low",
                    category="user_research",
                    title=f"{persona['label']} journey: {len(missing)} pages missing",
                    detail=f"Missing: {', '.join(sorted(missing))}",
                    recommendation=f"Verify if {', '.join(sorted(missing))} pages are needed for {persona['label']} flow",
                )
            )

        insights.append(
            ProductInsight(
                id=f"ur-insight-journey-{persona_id}",
                category="journey",
                title=f"{persona['label']} journey coverage: {coverage:.0%}",
                evidence=f"{len(found)}/{len(expected)} key pages present: {', '.join(sorted(found))}",
                impact=f"{'Complete' if coverage >= 1.0 else 'Incomplete'} journey for {persona['label']}s",
                recommendation="Fill journey gaps"
                if coverage < 1.0
                else "Journey complete",
                confidence=0.9,
                persona=persona_id,
            )
        )


def _check_persona_balance(
    page_files: list[Path],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Check feature balance between demand (job seeker) and supply (network holder)."""
    demand_pages = set()
    supply_pages = set()
    actual_pages = {_page_name(p) for p in page_files}

    for persona_id, persona in PERSONAS.items():
        matched = set(persona.get("key_pages", [])) & actual_pages
        if persona.get("tier") == "demand":
            demand_pages.update(matched)
        elif persona.get("tier") == "supply":
            supply_pages.update(matched)

    metrics["demand_pages"] = len(demand_pages)
    metrics["supply_pages"] = len(supply_pages)

    balance = len(supply_pages) / max(1, len(demand_pages))
    metrics["supply_demand_page_ratio"] = round(balance, 2)

    insights.append(
        ProductInsight(
            id="ur-insight-balance",
            category="persona",
            title=f"Supply/demand page ratio: {balance:.2f}",
            evidence=f"Demand (job seeker): {len(demand_pages)} pages, Supply (network holder): {len(supply_pages)} pages",
            impact="Balanced product investment"
            if 0.6 <= balance <= 1.5
            else "Potential imbalance in persona investment",
            recommendation="Review supply-side features"
            if balance < 0.6
            else "Balance is acceptable",
            confidence=0.8,
        )
    )


def _scan_user_sentiment(
    insights: list[ProductInsight],
    findings: list[Finding],
    metrics: dict,
) -> None:
    """Search web for user sentiment about referral platforms and job search tools."""
    queries = [
        "employee referral platform review site:reddit.com",
        "warm introduction job search tool",
        "referral marketplace job seekers",
    ]
    total_results = 0
    sentiment_snippets: list[str] = []

    for query in queries:
        results = web_search(query, max_results=3)
        total_results += len(results)
        for r in results:
            sentiment_snippets.append(f"{r.title}: {r.snippet[:120]}")

    metrics["web_sentiment_results"] = total_results
    metrics["web_sentiment_queries"] = len(queries)

    if total_results > 0:
        insights.append(
            ProductInsight(
                id="ur-insight-sentiment",
                category="research",
                title=f"Web sentiment scan: {total_results} results across {len(queries)} queries",
                evidence="; ".join(sentiment_snippets[:5]),
                impact="External user sentiment informs product positioning and feature prioritization",
                recommendation="Review sentiment trends for unmet needs in referral job search",
                confidence=0.6,
            )
        )
    else:
        insights.append(
            ProductInsight(
                id="ur-insight-sentiment",
                category="research",
                title="Web sentiment scan: no results (network may be unavailable)",
                evidence="Web search returned 0 results — may be offline or rate-limited",
                impact="Cannot assess external user sentiment without web access",
                recommendation="Retry when network is available",
                confidence=0.3,
            )
        )


def _catalog_research_sources(
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Catalog available intelligence sources for user research."""
    from product_team.shared.intelligence import PRODUCT_INTEL_CATEGORIES

    researcher_categories = [
        cat
        for cat, meta in PRODUCT_INTEL_CATEGORIES.items()
        if "user_researcher" in meta.get("agents", [])
    ]
    metrics["research_source_count"] = len(researcher_categories)

    insights.append(
        ProductInsight(
            id="ur-insight-sources",
            category="strategy",
            title=f"{len(researcher_categories)} intelligence sources available",
            evidence=f"Categories: {', '.join(researcher_categories)}",
            impact="Research infrastructure readiness",
            recommendation="Populate intelligence categories with initial data",
            confidence=1.0,
        )
    )


def _scan_page_content(
    page_files: list[Path],
    insights: list[ProductInsight],
    metrics: dict,
) -> None:
    """Analyze page content for user-facing features."""
    total_components = 0
    pages_with_api_calls = 0
    api_pattern = re.compile(
        r"(?:fetch|axios|api\.|useQuery|useMutation)", re.IGNORECASE
    )

    for path in page_files:
        source = _read_safe(path)
        total_components += source.count("const ")
        if api_pattern.search(source):
            pages_with_api_calls += 1

    metrics["pages_with_api_calls"] = pages_with_api_calls
    metrics["total_page_components"] = total_components


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> ProductTeamReport:
    """Run all user research checks and return a ProductTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[ProductInsight] = []
    metrics: dict = {}

    page_files = _find_page_files()
    metrics["total_page_files"] = len(page_files)

    if not page_files:
        findings.append(
            Finding(
                id="ur-000",
                severity="info",
                category="user_research",
                title="No page files found in frontend/src/pages/",
                detail="Frontend may not be initialized yet",
                recommendation="Initialize React frontend under frontend/src/pages/",
            )
        )
    else:
        _map_user_journeys(page_files, insights, findings, metrics)
        _check_persona_balance(page_files, insights, metrics)
        _scan_page_content(page_files, insights, metrics)

    _catalog_research_sources(insights, metrics)
    _scan_user_sentiment(insights, findings, metrics)

    duration = time.time() - start

    # Learning
    ls = ProductLearningState(AGENT_NAME)
    ls.record_scan(metrics)
    for f in findings:
        ls.record_finding(
            {
                "id": f.id,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "file": f.file,
            }
        )
        ls.record_severity_calibration(f.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    for i in insights:
        ls.record_insight(
            {
                "id": i.id,
                "category": i.category,
                "title": i.title,
                "confidence": i.confidence,
            }
        )

    ls.track_kpi("pages_found", metrics.get("pages_found", 0))

    learning_updates = [
        f"Scanned {len(page_files)} page files, {len(insights)} insights"
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return ProductTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        product_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: ProductTeamReport) -> Path:
    """Save report to product_team/reports/."""
    from product_team.shared.config import REPORTS_DIR

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
