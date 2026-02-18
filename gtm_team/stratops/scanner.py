"""StratOps Manager agent — competitive intelligence, market entry, geographic
expansion, positioning, and referral rails thesis scanner.

Scans strategy documents to assess strategic readiness, competitive coverage,
and market entry sequencing for WarmPath's GTM team.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from agents.shared.report import Finding
from agents.shared.web_tools import web_search
from gtm_team.shared.config import (
    PROJECT_ROOT,
    REPORTS_DIR,
    TRACKED_COMPETITORS,
)
from gtm_team.shared.learning import GTMLearningState
from gtm_team.shared.report import GTMTeamReport, MarketInsight
from gtm_team.shared.strategy_context import (
    extract_competitive_info,
    extract_geographic_strategy,
    load_strategy_docs,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "stratops"

_THIS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file safely, returning empty string on error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _relative(path: Path) -> str:
    """Return path relative to PROJECT_ROOT for readable output."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_competitive_coverage(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Check that tracked competitors are mentioned in strategy docs.

    High severity if <50% coverage; medium if <75%; info observation otherwise.
    """
    comp_info = extract_competitive_info(docs)
    mentioned = comp_info.get("competitors_mentioned", [])
    total = comp_info.get("total_tracked", len(TRACKED_COMPETITORS))
    coverage = comp_info.get("coverage_ratio", 0.0)

    metrics["competitor_coverage_ratio"] = round(coverage, 2)
    metrics["competitors_mentioned"] = len(mentioned)
    metrics["competitors_tracked"] = total

    missing = [c for c in TRACKED_COMPETITORS if c not in mentioned]

    if coverage < 0.5:
        findings.append(
            Finding(
                id="STRAT-COMP-LOW",
                severity="high",
                category="competitive",
                title=f"Low competitive coverage: {coverage:.0%} ({len(mentioned)}/{total})",
                detail=(
                    f"Only {len(mentioned)} of {total} tracked competitors are mentioned "
                    f"in strategy docs. Missing: {', '.join(missing[:5])}."
                ),
                recommendation=(
                    "Create or update competitive analysis to cover all tracked competitors: "
                    + ", ".join(missing[:5])
                ),
                effort_hours=2.0,
            )
        )
    elif coverage < 0.75:
        findings.append(
            Finding(
                id="STRAT-COMP-MED",
                severity="medium",
                category="competitive",
                title=f"Moderate competitive coverage: {coverage:.0%} ({len(mentioned)}/{total})",
                detail=f"Missing competitors: {', '.join(missing)}.",
                recommendation="Add analysis for missing competitors.",
                effort_hours=1.0,
            )
        )

    # Always produce a market insight for competitive landscape
    insights.append(
        MarketInsight(
            id="strat-insight-comp",
            category="competitive",
            title=f"Competitive coverage: {coverage:.0%} ({len(mentioned)}/{total} tracked)",
            evidence=f"Mentioned: {', '.join(mentioned) or 'none'}. Missing: {', '.join(missing) or 'none'}.",
            strategic_impact="Low coverage means blind spots in competitive positioning",
            recommended_response="Expand competitive analysis in strategy docs"
            if coverage < 0.75
            else "Maintain current coverage",
            urgency="this_week" if coverage < 0.5 else "this_month",
            confidence="high",
        )
    )

    # Check for market sizing
    if comp_info.get("has_market_sizing"):
        insights.append(
            MarketInsight(
                id="strat-insight-tam",
                category="market_entry",
                title="Market sizing (TAM/SAM/SOM) documented",
                evidence="Found TAM/SAM/SOM or total addressable market references",
                strategic_impact="Market sizing supports investor conversations and prioritization",
                urgency="monitor",
                confidence="medium",
            )
        )


def _check_market_entry_analysis(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Check for market entry strategy documentation (Singapore, US, APAC).

    Medium severity if no entry strategy found.
    """
    all_text = "\n".join(docs.values()).lower()

    has_singapore = "singapore" in all_text
    has_us = "united states" in all_text or "us market" in all_text
    has_apac = "southeast asia" in all_text or "sea" in all_text or "apac" in all_text
    has_entry_sequence = (
        "market entry" in all_text
        or "entry sequence" in all_text
        or "expansion" in all_text
        or "launch market" in all_text
    )

    markets_mentioned = sum([has_singapore, has_us, has_apac])
    metrics["markets_mentioned"] = markets_mentioned
    metrics["has_entry_sequence"] = has_entry_sequence

    if not has_entry_sequence and markets_mentioned == 0:
        findings.append(
            Finding(
                id="STRAT-ENTRY-MISSING",
                severity="medium",
                category="market_entry",
                title="No market entry strategy documented",
                detail=(
                    "No geographic market entry strategy found in strategy docs. "
                    "WarmPath needs a clear sequence for Singapore -> US -> APAC."
                ),
                recommendation=(
                    "Document market entry sequence: primary market (Singapore), "
                    "expansion markets (US, APAC), regulatory requirements per market."
                ),
                effort_hours=3.0,
            )
        )
    elif not has_entry_sequence:
        findings.append(
            Finding(
                id="STRAT-ENTRY-NOSEQUENCE",
                severity="low",
                category="market_entry",
                title=f"Markets mentioned ({markets_mentioned}) but no entry sequence",
                detail="Geographic markets are referenced but no explicit entry sequence is documented.",
                recommendation="Add explicit market entry prioritization and sequencing.",
                effort_hours=1.0,
            )
        )

    insights.append(
        MarketInsight(
            id="strat-insight-entry",
            category="market_entry",
            title=f"Market entry: {markets_mentioned} markets, sequence={'yes' if has_entry_sequence else 'no'}",
            evidence=(
                f"Singapore: {'yes' if has_singapore else 'no'}, "
                f"US: {'yes' if has_us else 'no'}, "
                f"APAC: {'yes' if has_apac else 'no'}"
            ),
            strategic_impact="Clear entry sequence de-risks geographic expansion",
            recommended_response="Formalize entry sequence"
            if not has_entry_sequence
            else "Monitor expansion readiness",
            urgency="this_month" if not has_entry_sequence else "monitor",
            confidence="high",
        )
    )


def _check_geographic_readiness(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Check regulatory/compliance documentation per target market.

    Medium severity if regulatory notes are missing.
    """
    geo_info = extract_geographic_strategy(docs)
    markets = geo_info.get("markets_mentioned", {})
    has_regulatory = geo_info.get("has_regulatory_notes", False)

    metrics["geographic_markets_found"] = len(markets)
    metrics["has_regulatory_notes"] = has_regulatory

    if markets and not has_regulatory:
        findings.append(
            Finding(
                id="STRAT-GEO-NOREG",
                severity="medium",
                category="geographic",
                title="Geographic markets mentioned without regulatory notes",
                detail=(
                    f"Markets {', '.join(markets.keys())} are mentioned but no regulatory "
                    "framework (PDPA, GDPR, CCPA) documentation found."
                ),
                recommendation=(
                    "Document regulatory requirements for each target market: "
                    "PDPA (Singapore), GDPR (EU), CCPA (US)."
                ),
                effort_hours=2.0,
            )
        )
    elif not markets:
        findings.append(
            Finding(
                id="STRAT-GEO-NONE",
                severity="low",
                category="geographic",
                title="No geographic markets documented",
                detail="No target geographic markets identified in strategy docs.",
                recommendation="Define target markets and document entry requirements.",
                effort_hours=1.0,
            )
        )

    insights.append(
        MarketInsight(
            id="strat-insight-geo",
            category="market_entry",
            title=f"Geographic readiness: {len(markets)} markets, regulatory={'covered' if has_regulatory else 'missing'}",
            evidence=f"Markets: {', '.join(markets.keys()) or 'none'}. Regulatory: {'yes' if has_regulatory else 'no'}.",
            strategic_impact="Regulatory gaps block market entry",
            recommended_response="Add regulatory docs"
            if not has_regulatory
            else "Maintain regulatory coverage",
            urgency="this_week" if markets and not has_regulatory else "monitor",
            confidence="high",
        )
    )


def _check_positioning_strength(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Check for differentiation documentation and value propositions.

    High severity if no positioning found.
    """
    import re

    all_text = "\n".join(docs.values())
    all_lower = all_text.lower()

    has_differentiators = bool(
        re.search(
            r"differentiator|competitive\s+advantage|unique\s+value|key\s+differentiator",
            all_lower,
        )
    )
    has_value_prop = bool(
        re.search(
            r"value\s+prop|wedge\s+market|core\s+thesis|two.sided\s+marketplace",
            all_lower,
        )
    )
    has_positioning = bool(
        re.search(
            r"positioning|market\s+position|category\s+design",
            all_lower,
        )
    )
    has_privacy_messaging = bool(
        re.search(
            r"privacy.first|anonymi[sz]ed|consent.gate|vault\s+model",
            all_lower,
        )
    )

    signals = sum(
        [has_differentiators, has_value_prop, has_positioning, has_privacy_messaging]
    )
    metrics["positioning_signals"] = signals
    metrics["has_differentiators"] = has_differentiators
    metrics["has_value_prop"] = has_value_prop
    metrics["has_positioning"] = has_positioning
    metrics["has_privacy_messaging"] = has_privacy_messaging

    if signals == 0:
        findings.append(
            Finding(
                id="STRAT-POS-NONE",
                severity="high",
                category="positioning",
                title="No positioning or differentiation documented",
                detail=(
                    "No differentiators, value propositions, or positioning statements "
                    "found in strategy docs."
                ),
                recommendation=(
                    "Document: (1) key differentiators, (2) value proposition per persona, "
                    "(3) competitive positioning statement, (4) privacy-first messaging."
                ),
                effort_hours=3.0,
            )
        )
    elif signals < 3:
        findings.append(
            Finding(
                id="STRAT-POS-PARTIAL",
                severity="medium",
                category="positioning",
                title=f"Partial positioning: {signals}/4 elements documented",
                detail=(
                    f"Differentiators: {'yes' if has_differentiators else 'no'}, "
                    f"Value prop: {'yes' if has_value_prop else 'no'}, "
                    f"Positioning: {'yes' if has_positioning else 'no'}, "
                    f"Privacy messaging: {'yes' if has_privacy_messaging else 'no'}"
                ),
                recommendation="Complete positioning documentation for missing elements.",
                effort_hours=1.5,
            )
        )

    insights.append(
        MarketInsight(
            id="strat-insight-pos",
            category="competitive",
            title=f"Positioning strength: {signals}/4 elements",
            evidence=(
                f"Differentiators: {'yes' if has_differentiators else 'no'}, "
                f"Value prop: {'yes' if has_value_prop else 'no'}, "
                f"Positioning: {'yes' if has_positioning else 'no'}, "
                f"Privacy messaging: {'yes' if has_privacy_messaging else 'no'}"
            ),
            strategic_impact="Weak positioning makes GTM execution ineffective",
            recommended_response="Strengthen positioning"
            if signals < 3
            else "Position is solid",
            urgency="this_week"
            if signals == 0
            else "this_month"
            if signals < 3
            else "monitor",
            confidence="high",
        )
    )


def _scan_competitor_updates(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Search the web for recent competitor news and product updates."""
    results_by_competitor: dict[str, list] = {}
    total_results = 0

    for competitor in TRACKED_COMPETITORS[:5]:  # Top 5 to stay within rate limits
        results = web_search(
            f"{competitor} referral platform news 2025 2026", max_results=3
        )
        results_by_competitor[competitor] = results
        total_results += len(results)

    metrics["web_competitor_results"] = total_results
    metrics["web_competitors_searched"] = len(results_by_competitor)

    active_competitors: list[str] = []
    for comp, results in results_by_competitor.items():
        if results:
            active_competitors.append(comp)

    if active_competitors:
        evidence_parts = []
        for comp in active_competitors[:3]:
            top = results_by_competitor[comp][0]
            evidence_parts.append(f"{comp}: {top.title[:80]}")

        insights.append(
            MarketInsight(
                id="strat-insight-web-comp",
                category="competitive",
                title=f"Live competitor intel: {len(active_competitors)} competitors with recent activity",
                evidence="; ".join(evidence_parts),
                strategic_impact="Active competitor moves may require strategic response",
                recommended_response="Review competitor updates for positioning implications",
                urgency="this_week" if len(active_competitors) > 2 else "this_month",
                confidence="medium",
            )
        )
    else:
        insights.append(
            MarketInsight(
                id="strat-insight-web-comp",
                category="competitive",
                title="Live competitor intel: no recent activity found (or network unavailable)",
                evidence="Web search returned no competitor results",
                strategic_impact="Cannot assess real-time competitive landscape without web access",
                urgency="monitor",
                confidence="low",
            )
        )


def _check_referral_rails_thesis(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Check for platform evolution documentation (referral rails thesis).

    Info-level observation -- tracks thesis documentation completeness.
    """
    import re

    all_text = "\n".join(docs.values())
    all_lower = all_text.lower()

    thesis_signals = {
        "referral_bonus": bool(
            re.search(r"referral\s+bonus|employer\s+referral", all_lower)
        ),
        "network_effects": bool(
            re.search(r"network\s+effect|flywheel|supply.side", all_lower)
        ),
        "marketplace_thesis": bool(
            re.search(r"two.sided\s+marketplace|marketplace|cross.network", all_lower)
        ),
        "warm_score": bool(re.search(r"warm\s+score|warm_score|warmth", all_lower)),
        "cultural_context": bool(
            re.search(
                r"cultural\s+context|approach\s+style|message\s+sequence", all_lower
            )
        ),
        "credit_economy": bool(
            re.search(r"credit|non.transferable|loyalty\s+program", all_lower)
        ),
    }

    documented = sum(thesis_signals.values())
    total = len(thesis_signals)
    metrics["thesis_coverage"] = round(documented / max(1, total), 2)
    metrics["thesis_signals"] = documented

    for signal, present in thesis_signals.items():
        metrics[f"thesis_{signal}"] = present

    if documented < total:
        missing = [k for k, v in thesis_signals.items() if not v]
        findings.append(
            Finding(
                id="STRAT-THESIS-GAP",
                severity="info",
                category="thesis",
                title=f"Referral rails thesis: {documented}/{total} elements documented",
                detail=f"Missing thesis elements: {', '.join(missing)}",
                recommendation="Document missing thesis elements for investor and team alignment.",
                effort_hours=1.0,
            )
        )

    insights.append(
        MarketInsight(
            id="strat-insight-thesis",
            category="competitive",
            title=f"Referral rails thesis: {documented}/{total} elements documented",
            evidence=", ".join(
                f"{k}={'yes' if v else 'no'}" for k, v in thesis_signals.items()
            ),
            strategic_impact="Complete thesis documentation drives aligned execution",
            recommended_response="Document remaining thesis elements"
            if documented < total
            else "Thesis well-documented",
            urgency="monitor",
            confidence="high",
        )
    )


# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------


def _compute_strategic_readiness(metrics: dict[str, Any]) -> float:
    """Compute a 0-100 strategic readiness score from metrics.

    Weights:
    - Competitive coverage: 25%
    - Market entry: 20%
    - Geographic readiness: 15%
    - Positioning: 25%
    - Thesis: 15%
    """
    comp_score = metrics.get("competitor_coverage_ratio", 0.0) * 100
    entry_score = 50.0 * (1 if metrics.get("has_entry_sequence") else 0) + 50.0 * min(
        1.0, metrics.get("markets_mentioned", 0) / 3
    )
    geo_score = 50.0 * min(
        1.0, metrics.get("geographic_markets_found", 0) / 3
    ) + 50.0 * (1 if metrics.get("has_regulatory_notes") else 0)
    pos_score = metrics.get("positioning_signals", 0) / 4 * 100
    thesis_score = metrics.get("thesis_coverage", 0.0) * 100

    readiness = (
        comp_score * 0.25
        + entry_score * 0.20
        + geo_score * 0.15
        + pos_score * 0.25
        + thesis_score * 0.15
    )
    return round(min(100.0, max(0.0, readiness)), 1)


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------


def scan() -> GTMTeamReport:
    """Run all StratOps checks and return a GTMTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[MarketInsight] = []
    metrics: dict[str, Any] = {}
    learning_updates: list[str] = []

    # Load strategy docs
    docs = load_strategy_docs()
    metrics["strategy_docs_loaded"] = len(docs)

    if not docs:
        findings.append(
            Finding(
                id="STRAT-NODOCS",
                severity="high",
                category="strategy",
                title="No strategy documents found",
                detail="Could not load any strategy documents. StratOps cannot operate without them.",
                recommendation="Ensure CLAUDE.md and other strategy docs exist at project root.",
                effort_hours=0.5,
            )
        )
    else:
        # Run all checks
        _check_competitive_coverage(docs, findings, insights, metrics)
        _check_market_entry_analysis(docs, findings, insights, metrics)
        _check_geographic_readiness(docs, findings, insights, metrics)
        _check_positioning_strength(docs, findings, insights, metrics)
        _check_referral_rails_thesis(docs, findings, insights, metrics)

    # Live competitive intelligence from web
    _scan_competitor_updates(findings, insights, metrics)

    # Compute readiness score
    readiness = _compute_strategic_readiness(metrics)
    metrics["strategic_readiness_score"] = readiness

    # -- Self-learning -------------------------------------------------------
    ls = GTMLearningState(AGENT_NAME)
    ls.record_scan(
        {k: v for k, v in metrics.items() if isinstance(v, (int, float, bool))}
    )

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

    # Attention weights on strategy docs
    file_finding_counts: dict[str, int] = {}
    for f in findings:
        key = f.category or "general"
        file_finding_counts[key] = file_finding_counts.get(key, 0) + 1
    ls.update_attention_weights(file_finding_counts)

    # Health snapshot
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # KPI tracking
    ls.track_kpi("strategic_readiness", readiness)
    ls.track_kpi("competitor_coverage", metrics.get("competitor_coverage_ratio", 0.0))
    ls.track_kpi("market_count", metrics.get("markets_mentioned", 0))

    ls.save()

    # Learning update notes
    learning_updates.append(
        f"Scan #{ls.state.get('total_scans', 0)}: "
        f"{len(findings)} findings, {len(insights)} insights, "
        f"readiness={readiness}"
    )
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(f"Hot spots: {', '.join(h.file for h in hot_spots)}")

    duration = time.time() - start

    report = GTMTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        market_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )

    logger.info(
        "StratOps scan complete: %d findings, %d insights in %.1fs (readiness=%.0f)",
        len(findings),
        len(insights),
        duration,
        readiness,
    )

    return report


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def save_report(report: GTMTeamReport) -> Path:
    """Save report to gtm_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "stratops_latest.json"
    path.write_text(report.serialize())
    return path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    report = scan()
    print(report.to_markdown())

    sev_counts: dict[str, int] = {}
    for f in report.findings:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
    summary_parts = [f"{v} {k}" for k, v in sorted(sev_counts.items())]
    print(
        f"\nTotal: {len(report.findings)} findings ({', '.join(summary_parts) or 'clean'})"
    )
    print(
        f"Strategic readiness: {report.metrics.get('strategic_readiness_score', 0)}/100"
    )

    if sev_counts.get("critical", 0) or sev_counts.get("high", 0):
        sys.exit(1)
