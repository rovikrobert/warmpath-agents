"""Product Monetization Manager agent — pricing architecture, credit economy,
feature gating, revenue modeling, and marketplace monetization scanner.

Scans strategy documents and codebase to validate monetization implementation
against documented business model for WarmPath's GTM team.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from agents.shared.report import Finding
from gtm_team.shared.config import (
    API_DIR,
    MODELS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    SERVICES_DIR,
)
from gtm_team.shared.learning import GTMLearningState
from gtm_team.shared.report import GTMTeamReport, MarketInsight
from gtm_team.shared.strategy_context import (
    extract_pricing_info,
    load_strategy_docs,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "monetization"

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


def _check_pricing_architecture(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Scan strategy docs for pricing tiers and validate Stripe/payment presence.

    High severity if no pricing model documented.
    """
    pricing_info = extract_pricing_info(docs)
    tiers_found = len(pricing_info.get("tiers", []))
    metrics["pricing_tiers_documented"] = tiers_found

    # Check for Stripe/payment integration in codebase
    stripe_found = False
    payment_files: list[str] = []
    if API_DIR.is_dir():
        for py_file in sorted(API_DIR.glob("*.py")):
            content = _read_safe(py_file)
            if re.search(r"stripe|payment|checkout|subscription|billing", content, re.IGNORECASE):
                stripe_found = True
                payment_files.append(_relative(py_file))

    metrics["has_stripe_integration"] = stripe_found
    metrics["payment_files_count"] = len(payment_files)

    if tiers_found == 0 and not stripe_found:
        findings.append(Finding(
            id="MON-PRICE-NONE",
            severity="high",
            category="pricing",
            title="No pricing model documented or implemented",
            detail=(
                "No pricing tiers found in strategy docs and no Stripe/payment "
                "integration found in API files."
            ),
            recommendation=(
                "Document pricing tiers (free, $20-30/month Active Job Seeker) "
                "and implement Stripe integration."
            ),
            effort_hours=4.0,
        ))
    elif tiers_found == 0:
        findings.append(Finding(
            id="MON-PRICE-NODOC",
            severity="medium",
            category="pricing",
            title="Pricing not explicitly documented in strategy",
            detail=(
                f"Stripe/payment code found in {len(payment_files)} file(s) but "
                "no explicit pricing tier documentation in strategy docs."
            ),
            file=payment_files[0] if payment_files else None,
            recommendation="Document pricing tiers and map to Stripe products/prices.",
            effort_hours=1.0,
        ))
    elif not stripe_found:
        findings.append(Finding(
            id="MON-PRICE-NOIMPL",
            severity="medium",
            category="pricing",
            title="Pricing documented but no Stripe integration found",
            detail=(
                f"{tiers_found} pricing tier pattern(s) in strategy docs but no "
                "Stripe or payment references in API files."
            ),
            recommendation="Implement Stripe integration to match documented pricing.",
            effort_hours=3.0,
        ))

    insights.append(MarketInsight(
        id="mon-insight-pricing",
        category="pricing",
        title=f"Pricing: {tiers_found} tier(s) documented, Stripe={'yes' if stripe_found else 'no'}",
        evidence=(
            f"Strategy tier patterns: {tiers_found}. "
            f"Payment files: {', '.join(payment_files) or 'none'}."
        ),
        strategic_impact="Pricing architecture gates revenue generation",
        recommended_response="Complete pricing-to-implementation mapping" if not stripe_found else "Maintain pricing alignment",
        urgency="this_week" if tiers_found == 0 and not stripe_found else "this_month",
        confidence="high",
    ))


def _check_credit_economy(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Scan credits service for earn/spend actions, expiry, non-transferability.

    Medium severity if gaps found.
    """
    credits_service_path = SERVICES_DIR / "credits.py"
    credits_content = _read_safe(credits_service_path)
    rel_path = _relative(credits_service_path)

    if not credits_content:
        findings.append(Finding(
            id="MON-CREDIT-NOSVC",
            severity="medium",
            category="credit_economy",
            title="Credits service not found",
            detail=f"Expected credits service at {rel_path} but file is missing or empty.",
            recommendation="Create app/services/credits.py with earn/spend/expiry logic.",
            effort_hours=4.0,
        ))
        metrics["credit_service_exists"] = False
        metrics["credit_actions_found"] = 0
        return

    metrics["credit_service_exists"] = True

    # Check for key credit economy elements
    credit_signals = {
        "earn_action": bool(re.search(r"earn|add_credits|credit_earn|award", credits_content, re.IGNORECASE)),
        "spend_action": bool(re.search(r"spend|deduct|charge|consume|subtract", credits_content, re.IGNORECASE)),
        "expiry": bool(re.search(r"expir|ttl|stale|month|valid_until", credits_content, re.IGNORECASE)),
        "non_transferable": bool(re.search(r"transfer|non.transfer|user_id", credits_content, re.IGNORECASE)),
        "balance_check": bool(re.search(r"balance|sum|total|sufficient|enough", credits_content, re.IGNORECASE)),
    }

    found = sum(credit_signals.values())
    total = len(credit_signals)
    metrics["credit_actions_found"] = found
    metrics["credit_signals_total"] = total

    for signal, present in credit_signals.items():
        metrics[f"credit_{signal}"] = present

    missing = [k for k, v in credit_signals.items() if not v]
    if missing:
        severity = "medium" if len(missing) <= 2 else "high"
        findings.append(Finding(
            id="MON-CREDIT-GAP",
            severity=severity,
            category="credit_economy",
            title=f"Credit economy gaps: {found}/{total} elements implemented",
            detail=f"Missing in credits service: {', '.join(missing)}.",
            file=rel_path,
            recommendation=f"Implement missing credit economy elements: {', '.join(missing)}.",
            effort_hours=len(missing) * 1.0,
        ))

    # Cross-reference with strategy docs
    pricing_info = extract_pricing_info(docs)
    strategy_credit = pricing_info.get("credit_economy", {})
    metrics["strategy_credit_elements"] = len(strategy_credit)

    insights.append(MarketInsight(
        id="mon-insight-credit",
        category="pricing",
        title=f"Credit economy: {found}/{total} elements in service, {len(strategy_credit)} in strategy",
        evidence=", ".join(f"{k}={'yes' if v else 'no'}" for k, v in credit_signals.items()),
        strategic_impact="Credit economy drives marketplace liquidity and retention",
        recommended_response="Close credit economy gaps" if missing else "Credit economy is solid",
        urgency="this_month" if missing else "monitor",
        confidence="high",
    ))


def _check_feature_gating(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Scan API files for feature gating patterns (free vs paid tier checks).

    Medium severity if no gating found.
    """
    gating_patterns = [
        re.compile(r"subscription|tier|plan|premium|pro\b|free.tier", re.IGNORECASE),
        re.compile(r"is_subscribed|has_subscription|check_plan|require_plan", re.IGNORECASE),
        re.compile(r"feature_flag|feature_gate|access_level|permission", re.IGNORECASE),
        re.compile(r"credit.*check|check.*credit|sufficient.*credit|enough.*credit", re.IGNORECASE),
    ]

    gated_files: list[str] = []
    total_api_files = 0

    if API_DIR.is_dir():
        for py_file in sorted(API_DIR.glob("*.py")):
            total_api_files += 1
            content = _read_safe(py_file)
            for pattern in gating_patterns:
                if pattern.search(content):
                    gated_files.append(_relative(py_file))
                    break

    metrics["api_files_scanned"] = total_api_files
    metrics["api_files_with_gating"] = len(gated_files)
    gating_ratio = len(gated_files) / max(1, total_api_files)
    metrics["gating_coverage_ratio"] = round(gating_ratio, 2)

    if not gated_files:
        findings.append(Finding(
            id="MON-GATE-NONE",
            severity="medium",
            category="feature_gating",
            title="No feature gating patterns found in API",
            detail=(
                f"Scanned {total_api_files} API files but found no subscription, "
                "tier, or credit-check patterns."
            ),
            recommendation=(
                "Implement feature gating: check user subscription tier or credit balance "
                "before premium actions (cross-network search, intro facilitation)."
            ),
            effort_hours=3.0,
        ))
    elif gating_ratio < 0.3:
        findings.append(Finding(
            id="MON-GATE-LOW",
            severity="low",
            category="feature_gating",
            title=f"Low feature gating coverage: {gating_ratio:.0%} of API files",
            detail=f"Only {len(gated_files)} of {total_api_files} API files have gating patterns.",
            recommendation="Review which endpoints should be gated for paid tier.",
            effort_hours=1.0,
        ))

    insights.append(MarketInsight(
        id="mon-insight-gating",
        category="pricing",
        title=f"Feature gating: {len(gated_files)}/{total_api_files} API files",
        evidence=f"Gated files: {', '.join(gated_files) or 'none'}",
        strategic_impact="Feature gating enforces monetization boundaries",
        recommended_response="Implement gating" if not gated_files else "Review gating completeness",
        urgency="this_month" if not gated_files else "monitor",
        confidence="medium",
    ))


def _check_revenue_model(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Scan strategy docs for revenue projections and model documentation.

    Medium severity if missing.
    """
    all_text = "\n".join(docs.values())
    all_lower = all_text.lower()

    revenue_signals = {
        "revenue_model": bool(re.search(r"revenue\s+model|business\s+model|monetiz", all_lower)),
        "pricing_detail": bool(re.search(r"\$\d+.*month|\$\d+.*year|per\s+month", all_lower)),
        "unit_economics": bool(re.search(r"ltv|cac|arpu|churn|conversion\s+rate|unit\s+economics", all_lower)),
        "projection": bool(re.search(r"projection|forecast|runway|revenue\s+target|mrr|arr", all_lower)),
    }

    found = sum(revenue_signals.values())
    total = len(revenue_signals)
    metrics["revenue_model_signals"] = found
    metrics["revenue_model_total"] = total

    for signal, present in revenue_signals.items():
        metrics[f"revenue_{signal}"] = present

    missing = [k for k, v in revenue_signals.items() if not v]
    if found == 0:
        findings.append(Finding(
            id="MON-REV-NONE",
            severity="medium",
            category="revenue",
            title="No revenue model documentation",
            detail="No revenue model, pricing detail, unit economics, or projections found.",
            recommendation=(
                "Document revenue model: subscription pricing, credit purchases, "
                "unit economics (LTV, CAC, ARPU), and 12-month projections."
            ),
            effort_hours=4.0,
        ))
    elif found < 3:
        findings.append(Finding(
            id="MON-REV-PARTIAL",
            severity="low",
            category="revenue",
            title=f"Partial revenue model: {found}/{total} elements",
            detail=f"Missing: {', '.join(missing)}.",
            recommendation=f"Add missing revenue model elements: {', '.join(missing)}.",
            effort_hours=2.0,
        ))

    insights.append(MarketInsight(
        id="mon-insight-rev",
        category="pricing",
        title=f"Revenue model: {found}/{total} elements documented",
        evidence=", ".join(f"{k}={'yes' if v else 'no'}" for k, v in revenue_signals.items()),
        strategic_impact="Revenue model clarity drives fundraising and operational decisions",
        recommended_response="Complete revenue model" if found < total else "Revenue model documented",
        urgency="this_month" if found < 2 else "monitor",
        confidence="high" if found > 0 else "medium",
    ))


def _check_marketplace_monetization(
    docs: dict[str, str],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict[str, Any],
) -> None:
    """Scan marketplace models/API for monetization hooks (credit deduction, billing).

    Medium severity if gaps found.
    """
    marketplace_model_path = MODELS_DIR / "marketplace.py"
    marketplace_api_path = API_DIR / "marketplace.py"

    model_content = _read_safe(marketplace_model_path)
    api_content = _read_safe(marketplace_api_path)

    model_rel = _relative(marketplace_model_path)
    api_rel = _relative(marketplace_api_path)

    metrics["marketplace_model_exists"] = bool(model_content)
    metrics["marketplace_api_exists"] = bool(api_content)

    if not model_content and not api_content:
        findings.append(Finding(
            id="MON-MKT-NONE",
            severity="medium",
            category="marketplace_monetization",
            title="No marketplace files found",
            detail=f"Expected {model_rel} and {api_rel} but both are missing or empty.",
            recommendation="Implement marketplace model and API with monetization hooks.",
            effort_hours=5.0,
        ))
        metrics["marketplace_monetization_hooks"] = 0
        return

    combined = model_content + "\n" + api_content

    monetization_hooks = {
        "credit_deduction": bool(re.search(
            r"credit|deduct|charge|spend|cost", combined, re.IGNORECASE
        )),
        "billing_trigger": bool(re.search(
            r"bill|invoice|payment|stripe|checkout", combined, re.IGNORECASE
        )),
        "intro_cost": bool(re.search(
            r"intro.*credit|credit.*intro|facilitat.*cost|request.*credit",
            combined, re.IGNORECASE,
        )),
        "search_cost": bool(re.search(
            r"search.*credit|credit.*search|cross.network.*cost",
            combined, re.IGNORECASE,
        )),
    }

    found = sum(monetization_hooks.values())
    total = len(monetization_hooks)
    metrics["marketplace_monetization_hooks"] = found

    for hook, present in monetization_hooks.items():
        metrics[f"mkt_{hook}"] = present

    missing = [k for k, v in monetization_hooks.items() if not v]
    if missing:
        findings.append(Finding(
            id="MON-MKT-GAP",
            severity="medium" if len(missing) <= 2 else "high",
            category="marketplace_monetization",
            title=f"Marketplace monetization gaps: {found}/{total} hooks",
            detail=f"Missing: {', '.join(missing)}.",
            file=api_rel if api_content else model_rel,
            recommendation=f"Implement missing marketplace monetization hooks: {', '.join(missing)}.",
            effort_hours=len(missing) * 1.5,
        ))

    insights.append(MarketInsight(
        id="mon-insight-mkt",
        category="pricing",
        title=f"Marketplace monetization: {found}/{total} hooks present",
        evidence=", ".join(f"{k}={'yes' if v else 'no'}" for k, v in monetization_hooks.items()),
        strategic_impact="Marketplace monetization hooks enforce the credit economy",
        recommended_response="Close monetization gaps" if missing else "Hooks complete",
        urgency="this_month" if found < 2 else "monitor",
        confidence="high",
    ))


# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------


def _compute_monetization_readiness(metrics: dict[str, Any]) -> float:
    """Compute a 0-100 monetization readiness score from metrics.

    Weights:
    - Pricing architecture: 25%
    - Credit economy: 25%
    - Feature gating: 15%
    - Revenue model: 15%
    - Marketplace monetization: 20%
    """
    # Pricing: presence of tiers + Stripe
    pricing_score = (
        50.0 * min(1.0, metrics.get("pricing_tiers_documented", 0) / 2)
        + 50.0 * (1 if metrics.get("has_stripe_integration") else 0)
    )

    # Credit economy: proportion of signals found
    credit_total = metrics.get("credit_signals_total", 5)
    credit_score = metrics.get("credit_actions_found", 0) / max(1, credit_total) * 100

    # Feature gating
    gating_score = metrics.get("gating_coverage_ratio", 0.0) * 100

    # Revenue model
    rev_total = metrics.get("revenue_model_total", 4)
    rev_score = metrics.get("revenue_model_signals", 0) / max(1, rev_total) * 100

    # Marketplace monetization
    mkt_hooks = metrics.get("marketplace_monetization_hooks", 0)
    mkt_score = mkt_hooks / 4 * 100

    readiness = (
        pricing_score * 0.25
        + credit_score * 0.25
        + gating_score * 0.15
        + rev_score * 0.15
        + mkt_score * 0.20
    )
    return round(min(100.0, max(0.0, readiness)), 1)


# ---------------------------------------------------------------------------
# Main scan entry point
# ---------------------------------------------------------------------------


def scan() -> GTMTeamReport:
    """Run all monetization checks and return a GTMTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[MarketInsight] = []
    metrics: dict[str, Any] = {}
    learning_updates: list[str] = []

    # Load strategy docs
    docs = load_strategy_docs()
    metrics["strategy_docs_loaded"] = len(docs)

    # Run all checks (strategy docs may be empty -- checks handle gracefully)
    _check_pricing_architecture(docs, findings, insights, metrics)
    _check_credit_economy(docs, findings, insights, metrics)
    _check_feature_gating(docs, findings, insights, metrics)
    _check_revenue_model(docs, findings, insights, metrics)
    _check_marketplace_monetization(docs, findings, insights, metrics)

    # Compute readiness score
    readiness = _compute_monetization_readiness(metrics)
    metrics["monetization_readiness_score"] = readiness

    # -- Self-learning -------------------------------------------------------
    ls = GTMLearningState(AGENT_NAME)
    ls.record_scan({k: v for k, v in metrics.items() if isinstance(v, (int, float, bool))})

    for f in findings:
        ls.record_finding({
            "id": f.id,
            "severity": f.severity,
            "category": f.category,
            "title": f.title,
            "file": f.file,
        })
        ls.record_severity_calibration(f.severity)

    # Attention weights on scanned files
    file_finding_counts: dict[str, int] = {}
    for f in findings:
        key = f.file or f.category or "general"
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
    ls.track_kpi("monetization_readiness", readiness)
    ls.track_kpi("credit_actions", metrics.get("credit_actions_found", 0))
    ls.track_kpi("gating_coverage", metrics.get("gating_coverage_ratio", 0.0))

    ls.save()

    # Learning update notes
    learning_updates.append(
        f"Scan #{ls.state.get('total_scans', 0)}: "
        f"{len(findings)} findings, {len(insights)} insights, "
        f"readiness={readiness}"
    )
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file for h in hot_spots)}"
        )

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
        "Monetization scan complete: %d findings, %d insights in %.1fs (readiness=%.0f)",
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
    path = REPORTS_DIR / "monetization_latest.json"
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
    print(f"Monetization readiness: {report.metrics.get('monetization_readiness_score', 0)}/100")

    if sev_counts.get("critical", 0) or sev_counts.get("high", 0):
        sys.exit(1)
