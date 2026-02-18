"""Marsh agent -- marketplace health auditor.

Scans marketplace models, credit service, and API layer to audit:
  - Marketplace model completeness (supply/demand/coverage fields)
  - Credit economy (earn/spend actions, expiry, non-transferability)
  - Intro pipeline metrics (pending/approved/declined trackability)
  - Suppression list marketplace impact and coverage signals
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from ops_team.shared.config import (
    API_DIR,
    MARKETPLACE_ACTIONS,
    MODELS_DIR,
    REPORTS_DIR,
    SERVICES_DIR,
)
from ops_team.shared.learning import OpsLearningState
from ops_team.shared.report import MarketplaceFinding, OpsInsight, OpsTeamReport

logger = logging.getLogger(__name__)

AGENT_NAME = "marsh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read a file, returning empty string on any error."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("marsh: could not read %s: %s", path, exc)
        return ""


def _relative(path: Path) -> str:
    """Return a short relative-ish path string for reports."""
    parts = path.parts
    try:
        idx = parts.index("app")
        return "/".join(parts[idx:])
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Check: Marketplace model completeness
# ---------------------------------------------------------------------------

# Fields we expect on the core marketplace models
_LISTING_EXPECTED_FIELDS = [
    "company_id",
    "role_level",
    "department_category",
    "warm_score_range",
    "is_available",
    "network_holder_id",
    "contact_id",
    "connection_recency",
]

_INTRO_EXPECTED_FIELDS = [
    "status",
    "job_seeker_id",
    "network_holder_id",
    "marketplace_listing_id",
    "job_seeker_profile_snapshot",
    "requested_at",
    "reviewed_at",
    "completed_at",
]


def _check_marketplace_model(
    model_source: str,
    findings: list[Finding],
    mkt_findings: list[MarketplaceFinding],
    metrics: dict,
) -> None:
    """Verify MarketplaceListing and IntroFacilitation have expected fields."""
    model_path = _relative(MODELS_DIR / "marketplace.py")

    # -- MarketplaceListing fields --
    listing_found: list[str] = []
    listing_missing: list[str] = []
    for field_name in _LISTING_EXPECTED_FIELDS:
        if re.search(rf"\b{field_name}\b", model_source):
            listing_found.append(field_name)
        else:
            listing_missing.append(field_name)

    metrics["listing_fields_found"] = len(listing_found)
    metrics["listing_fields_expected"] = len(_LISTING_EXPECTED_FIELDS)

    if listing_missing:
        severity = (
            "high"
            if any(
                f in listing_missing
                for f in (
                    "company_id",
                    "role_level",
                    "is_available",
                    "network_holder_id",
                )
            )
            else "medium"
        )
        findings.append(
            Finding(
                id="marsh-001",
                severity=severity,
                category="model_completeness",
                title=f"MarketplaceListing missing {len(listing_missing)} expected fields",
                detail=f"Missing: {', '.join(listing_missing)}",
                file=model_path,
                recommendation="Add missing fields to MarketplaceListing for full marketplace coverage",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-001",
                category="model_completeness",
                severity=severity,
                title=f"MarketplaceListing missing fields: {', '.join(listing_missing)}",
                file=model_path,
                detail=f"Found {len(listing_found)}/{len(_LISTING_EXPECTED_FIELDS)} expected fields",
                recommendation="Ensure all anonymized marketplace fields are present for search quality",
            )
        )

    # -- IntroFacilitation fields --
    intro_found: list[str] = []
    intro_missing: list[str] = []
    for field_name in _INTRO_EXPECTED_FIELDS:
        if re.search(rf"\b{field_name}\b", model_source):
            intro_found.append(field_name)
        else:
            intro_missing.append(field_name)

    metrics["intro_fields_found"] = len(intro_found)
    metrics["intro_fields_expected"] = len(_INTRO_EXPECTED_FIELDS)

    if intro_missing:
        severity = (
            "high"
            if any(
                f in intro_missing
                for f in (
                    "status",
                    "job_seeker_id",
                    "network_holder_id",
                    "marketplace_listing_id",
                )
            )
            else "medium"
        )
        findings.append(
            Finding(
                id="marsh-002",
                severity=severity,
                category="model_completeness",
                title=f"IntroFacilitation missing {len(intro_missing)} expected fields",
                detail=f"Missing: {', '.join(intro_missing)}",
                file=model_path,
                recommendation="Add missing fields to IntroFacilitation for pipeline tracking",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-002",
                category="model_completeness",
                severity=severity,
                title=f"IntroFacilitation missing fields: {', '.join(intro_missing)}",
                file=model_path,
                detail=f"Found {len(intro_found)}/{len(_INTRO_EXPECTED_FIELDS)} expected fields",
                recommendation="Intro pipeline requires all status and participant fields for trackability",
            )
        )

    # Check for MarketplaceListing class itself
    if "class MarketplaceListing" not in model_source:
        findings.append(
            Finding(
                id="marsh-003",
                severity="critical",
                category="model_completeness",
                title="MarketplaceListing model class not found",
                detail="app/models/marketplace.py does not define MarketplaceListing",
                file=model_path,
                recommendation="The core marketplace listing model is required for the anonymized index",
            )
        )

    # Check for IntroFacilitation class itself
    if "class IntroFacilitation" not in model_source:
        findings.append(
            Finding(
                id="marsh-004",
                severity="critical",
                category="model_completeness",
                title="IntroFacilitation model class not found",
                detail="app/models/marketplace.py does not define IntroFacilitation",
                file=model_path,
                recommendation="The intro facilitation model is required for the consent-gated intro pipeline",
            )
        )


# ---------------------------------------------------------------------------
# Check: Credit economy
# ---------------------------------------------------------------------------

_EARN_ACTIONS = [
    "csv_upload",
    "intro_facilitation",
    "data_freshness",
    "welcome_bonus",
    "purchase",
]
_SPEND_ACTIONS = [
    "cross_network_search",
    "marketplace_search",
    "request_intro",
    "intro_request",
]


def _check_credit_economy(
    credit_source: str,
    api_source: str,
    findings: list[Finding],
    mkt_findings: list[MarketplaceFinding],
    metrics: dict,
    marketplace_api_source: str = "",
) -> None:
    """Verify earn/spend actions, expiry logic, and non-transferability."""
    credit_path = _relative(SERVICES_DIR / "credits.py")
    api_path = _relative(API_DIR / "credits.py")
    # Include marketplace API because earn/spend reason strings appear in callers
    combined = credit_source + "\n" + api_source + "\n" + marketplace_api_source

    # -- Earn actions --
    earn_found: list[str] = []
    earn_missing: list[str] = []
    for action in _EARN_ACTIONS:
        if re.search(rf'["\']?{action}["\']?', combined, re.IGNORECASE):
            earn_found.append(action)
        else:
            earn_missing.append(action)

    metrics["earn_actions_found"] = len(earn_found)
    metrics["earn_actions_expected"] = len(_EARN_ACTIONS)

    if earn_missing:
        findings.append(
            Finding(
                id="marsh-010",
                severity="medium",
                category="credit_economy",
                title=f"Credit economy missing {len(earn_missing)} earn actions",
                detail=f"Missing: {', '.join(earn_missing)}",
                file=credit_path,
                recommendation="Implement missing earn triggers to complete the credit economy loop",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-010",
                category="credit_economy",
                severity="medium",
                title=f"Missing earn actions: {', '.join(earn_missing)}",
                file=credit_path,
                detail=f"Found {len(earn_found)}/{len(_EARN_ACTIONS)} expected earn reasons",
                recommendation="Network holders need all earn incentives to maintain supply-side engagement",
            )
        )

    # -- Spend actions --
    spend_found: list[str] = []
    spend_missing: list[str] = []
    for action in _SPEND_ACTIONS:
        if re.search(rf'["\']?{action}["\']?', combined, re.IGNORECASE):
            spend_found.append(action)
        else:
            spend_missing.append(action)

    metrics["spend_actions_found"] = len(spend_found)
    metrics["spend_actions_expected"] = len(_SPEND_ACTIONS)

    if spend_missing:
        findings.append(
            Finding(
                id="marsh-011",
                severity="medium",
                category="credit_economy",
                title=f"Credit economy missing {len(spend_missing)} spend actions",
                detail=f"Missing: {', '.join(spend_missing)}",
                file=credit_path,
                recommendation="Ensure all credit-consuming actions are wired through spend_credits",
            )
        )

    # -- Expiry logic --
    has_expiry = "expire_stale_credits" in credit_source or "expired" in credit_source
    has_expires_at = "expires_at" in credit_source
    metrics["has_expiry_logic"] = has_expiry and has_expires_at

    if not has_expiry:
        findings.append(
            Finding(
                id="marsh-012",
                severity="high",
                category="credit_economy",
                title="Credit expiry logic not found",
                detail="expire_stale_credits function or 'expired' type not found in credits service",
                file=credit_path,
                recommendation="Credits must expire after 12 months per CLAUDE.md to avoid liability accrual",
            )
        )

    if not has_expires_at:
        findings.append(
            Finding(
                id="marsh-013",
                severity="high",
                category="credit_economy",
                title="expires_at field not referenced in credits service",
                detail="Credit transactions should set expires_at for 12-month expiry",
                file=credit_path,
                recommendation="Set expires_at on all earned credit transactions",
            )
        )

    # -- Non-transferability --
    has_transfer = re.search(r"def\s+transfer_credits", combined)
    metrics["has_transfer_function"] = bool(has_transfer)

    if has_transfer:
        findings.append(
            Finding(
                id="marsh-014",
                severity="high",
                category="credit_economy",
                title="Transfer function found -- credits should be non-transferable",
                detail="A transfer_credits function exists, violating non-transferability requirement",
                file=credit_path,
                recommendation="Remove transfer functionality to stay in loyalty-program territory (not money transmitter)",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-014",
                category="credit_economy",
                severity="high",
                title="Credit transfer function violates non-transferability requirement",
                file=credit_path,
                recommendation="Non-transferable credits keep us outside FinCEN/Singapore PSA scope",
            )
        )

    # -- Balance calculation --
    has_balance = "get_balance" in credit_source
    has_summary = "get_credit_summary" in credit_source
    metrics["has_balance_calculation"] = has_balance
    metrics["has_credit_summary"] = has_summary

    if not has_balance:
        findings.append(
            Finding(
                id="marsh-015",
                severity="high",
                category="credit_economy",
                title="Balance calculation function not found",
                detail="get_balance not present in credits service",
                file=credit_path,
                recommendation="Balance = SUM query on non-expired transactions is the core credit primitive",
            )
        )

    # -- Transaction logging in API --
    has_audit_log = "log_event" in api_source
    metrics["credits_api_has_audit_log"] = has_audit_log

    if not has_audit_log:
        findings.append(
            Finding(
                id="marsh-016",
                severity="medium",
                category="credit_economy",
                title="Credits API does not log to audit trail",
                detail="log_event not found in credits API",
                file=api_path,
                recommendation="Credit purchases and admin actions should log to audit_logs",
            )
        )


# ---------------------------------------------------------------------------
# Check: Intro pipeline
# ---------------------------------------------------------------------------

_PIPELINE_STATUSES = ["requested", "approved", "declined", "expired"]


def _check_intro_pipeline(
    marketplace_api_source: str,
    findings: list[Finding],
    mkt_findings: list[MarketplaceFinding],
    metrics: dict,
) -> None:
    """Verify the full intro lifecycle is tracked in the marketplace API."""
    api_path = _relative(API_DIR / "marketplace.py")

    # -- Request intro endpoint --
    has_request_intro = bool(
        re.search(r"request.intro|request_intro", marketplace_api_source)
    )
    metrics["has_request_intro_endpoint"] = has_request_intro

    if not has_request_intro:
        findings.append(
            Finding(
                id="marsh-020",
                severity="high",
                category="intro_pipeline",
                title="request-intro endpoint not found in marketplace API",
                detail="The core intro request flow is missing from the API layer",
                file=api_path,
                recommendation="Implement POST /marketplace/request-intro for the consent-gated intro flow",
            )
        )

    # -- Approve/decline endpoint --
    has_approve = bool(re.search(r"approve", marketplace_api_source, re.IGNORECASE))
    has_decline = bool(re.search(r"decline", marketplace_api_source, re.IGNORECASE))
    metrics["has_approve_action"] = has_approve
    metrics["has_decline_action"] = has_decline

    if not has_approve:
        findings.append(
            Finding(
                id="marsh-021",
                severity="high",
                category="intro_pipeline",
                title="Approve action not found in marketplace API",
                detail="Network holders cannot approve intro requests",
                file=api_path,
                recommendation="Implement approve action in PATCH /marketplace/requests/{id}",
            )
        )

    if not has_decline:
        findings.append(
            Finding(
                id="marsh-022",
                severity="high",
                category="intro_pipeline",
                title="Decline action not found in marketplace API",
                detail="Network holders cannot decline intro requests",
                file=api_path,
                recommendation="Implement decline action with partial credit refund",
            )
        )

    # -- Pipeline status coverage --
    statuses_found: list[str] = []
    statuses_missing: list[str] = []
    for status_name in _PIPELINE_STATUSES:
        if re.search(rf'["\']?{status_name}["\']?', marketplace_api_source):
            statuses_found.append(status_name)
        else:
            statuses_missing.append(status_name)

    metrics["pipeline_statuses_found"] = len(statuses_found)
    metrics["pipeline_statuses_expected"] = len(_PIPELINE_STATUSES)

    if statuses_missing:
        severity = (
            "high"
            if any(s in statuses_missing for s in ("requested", "approved"))
            else "medium"
        )
        findings.append(
            Finding(
                id="marsh-023",
                severity=severity,
                category="intro_pipeline",
                title=f"Intro pipeline missing {len(statuses_missing)} status values",
                detail=f"Missing: {', '.join(statuses_missing)}",
                file=api_path,
                recommendation="All pipeline statuses must be handled for complete intro lifecycle tracking",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-023",
                category="intro_pipeline",
                severity=severity,
                title=f"Missing intro statuses: {', '.join(statuses_missing)}",
                file=api_path,
                detail=f"Found {len(statuses_found)}/{len(_PIPELINE_STATUSES)} expected statuses",
                recommendation="Incomplete status tracking prevents intro pipeline analytics",
            )
        )

    # -- Funnel instrumentation (UsageLog tracking) --
    has_usage_log = (
        "UsageLog" in marketplace_api_source or "usage_log" in marketplace_api_source
    )
    metrics["intro_pipeline_instrumented"] = has_usage_log

    if not has_usage_log:
        findings.append(
            Finding(
                id="marsh-024",
                severity="medium",
                category="intro_pipeline",
                title="Intro pipeline not instrumented with UsageLog",
                detail="Approve/decline actions should log to usage_logs for funnel analytics",
                file=api_path,
                recommendation="Add UsageLog entries for intro_approve and intro_decline actions",
            )
        )


# ---------------------------------------------------------------------------
# Check: Marketplace actions coverage
# ---------------------------------------------------------------------------


def _check_marketplace_actions(
    sources: dict[str, str],
    findings: list[Finding],
    mkt_findings: list[MarketplaceFinding],
    metrics: dict,
) -> None:
    """Verify each MARKETPLACE_ACTIONS value is referenced across source files."""
    combined = "\n".join(sources.values())

    # Map canonical action names to alternative patterns found in the codebase.
    # The code uses different naming conventions (e.g., marketplace_search vs
    # cross_network_search, request-intro vs request_intro).
    _ACTION_ALIASES: dict[str, list[str]] = {
        "cross_network_search": [
            "cross_network_search",
            "marketplace_search",
            "marketplace.search",
        ],
        "request_intro": ["request_intro", "request.intro", "intro_request"],
        "approve_intro": ["approve_intro", "intro_approve", r'"approve"'],
        "decline_intro": ["decline_intro", "intro_decline", r'"decline"'],
    }

    covered: list[str] = []
    uncovered: list[str] = []
    for action in MARKETPLACE_ACTIONS:
        aliases = _ACTION_ALIASES.get(action, [action])
        found = False
        for alias in aliases:
            pattern = alias.replace("_", "[_-]?")
            if re.search(pattern, combined, re.IGNORECASE):
                found = True
                break
        if found:
            covered.append(action)
        else:
            uncovered.append(action)

    metrics["marketplace_actions_covered"] = len(covered)
    metrics["marketplace_actions_expected"] = len(MARKETPLACE_ACTIONS)
    coverage_ratio = len(covered) / max(1, len(MARKETPLACE_ACTIONS))
    metrics["marketplace_action_coverage"] = round(coverage_ratio, 2)

    if uncovered:
        findings.append(
            Finding(
                id="marsh-030",
                severity="medium",
                category="marketplace_actions",
                title=f"{len(uncovered)} marketplace actions not found in source",
                detail=f"Missing: {', '.join(uncovered)}",
                recommendation="Implement or alias all expected marketplace actions for full coverage",
            )
        )
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-030",
                category="marketplace_actions",
                severity="medium",
                title=f"Marketplace action coverage: {coverage_ratio:.0%}",
                detail=f"Covered: {', '.join(covered)}. Missing: {', '.join(uncovered)}",
                recommendation="Full action coverage is required for marketplace analytics and metering",
            )
        )


# ---------------------------------------------------------------------------
# Check: Suppression list marketplace impact
# ---------------------------------------------------------------------------


def _check_suppression_impact(
    model_source: str,
    api_source: str,
    findings: list[Finding],
    mkt_findings: list[MarketplaceFinding],
    metrics: dict,
) -> None:
    """Verify suppression list is referenced and checked during marketplace ops."""
    model_path = _relative(MODELS_DIR / "marketplace.py")
    api_path = _relative(API_DIR / "marketplace.py")

    # Check that the suppression list model/table exists somewhere in the codebase
    privacy_model = MODELS_DIR / "privacy.py"
    privacy_source = _read_safe(privacy_model)
    has_suppression_model = (
        "suppression_list" in privacy_source or "SuppressionList" in privacy_source
    )
    metrics["has_suppression_model"] = has_suppression_model

    if not has_suppression_model:
        findings.append(
            Finding(
                id="marsh-040",
                severity="high",
                category="suppression_impact",
                title="Suppression list model not found",
                detail="SuppressionList or suppression_list table not found in app/models/privacy.py",
                file=_relative(privacy_model),
                recommendation="Suppression list is required for privacy compliance (GDPR/CCPA/PDPA deletion)",
            )
        )

    # Check that marketplace API references suppression checking
    has_suppression_check_api = (
        "suppression" in api_source.lower() or "hash_for_suppression" in api_source
    )
    metrics["marketplace_checks_suppression"] = has_suppression_check_api

    if not has_suppression_check_api:
        # This is important but the duplicate-detection hash check in request_intro
        # partially covers this ground -- severity medium rather than high
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-040",
                category="suppression_impact",
                severity="medium",
                title="Marketplace API does not explicitly check suppression list on search",
                file=api_path,
                detail="Suppression checking should happen at marketplace search time, not just import time",
                recommendation="Add suppression hash check before returning marketplace search results",
            )
        )

    # Check that suppression is enforced at CSV import time (reference check)
    has_hash_util = "hash_for_suppression" in api_source
    metrics["marketplace_uses_hash_util"] = has_hash_util

    if has_hash_util:
        # Good -- the marketplace API uses hash comparison for duplicate detection
        mkt_findings.append(
            MarketplaceFinding(
                id="marsh-mkt-041",
                category="suppression_impact",
                severity="info",
                title="Marketplace API uses hash_for_suppression for duplicate detection",
                file=api_path,
                detail="SHA-256 hash comparison prevents redundant credit spending",
                recommendation="No action needed -- privacy-preserving duplicate detection is in place",
            )
        )


# ---------------------------------------------------------------------------
# Check: Coverage signals
# ---------------------------------------------------------------------------


def _check_coverage_signals(
    model_source: str,
    findings: list[Finding],
    insights: list[OpsInsight],
    metrics: dict,
) -> None:
    """Check for fields and structures that track marketplace coverage."""
    model_path = _relative(MODELS_DIR / "marketplace.py")

    # Check for NetworkHolderAvailability (company-level coverage tracking)
    has_availability_model = "class NetworkHolderAvailability" in model_source
    metrics["has_availability_model"] = has_availability_model

    # Check for ConnectorReputation (supply quality signals)
    has_reputation_model = "class ConnectorReputation" in model_source
    metrics["has_reputation_model"] = has_reputation_model

    # Check for NetworkSharingPreferences (opt-in tracking)
    has_sharing_prefs = "class NetworkSharingPreferences" in model_source
    metrics["has_sharing_prefs_model"] = has_sharing_prefs

    # Count how many coverage-related models exist
    coverage_models_found = sum(
        [
            has_availability_model,
            has_reputation_model,
            has_sharing_prefs,
        ]
    )
    metrics["coverage_models_found"] = coverage_models_found
    metrics["coverage_models_expected"] = 3

    if not has_availability_model:
        findings.append(
            Finding(
                id="marsh-050",
                severity="medium",
                category="coverage",
                title="NetworkHolderAvailability model not found",
                detail="Company-level supply coverage tracking is missing",
                file=model_path,
                recommendation="Add availability tracking to measure marketplace coverage by company",
            )
        )

    if not has_reputation_model:
        findings.append(
            Finding(
                id="marsh-051",
                severity="medium",
                category="coverage",
                title="ConnectorReputation model not found",
                detail="Supply quality signals (response rate, rating) are not tracked",
                file=model_path,
                recommendation="Reputation tracking is critical for marketplace trust and supply quality",
            )
        )

    # Check for is_active / is_available flags (listing-level coverage)
    has_active_flag = "is_active" in model_source
    has_available_flag = "is_available" in model_source
    metrics["has_active_listing_flag"] = has_active_flag or has_available_flag

    # Check for category_filters (department-level coverage control)
    has_category_filters = "category_filters" in model_source
    metrics["has_category_filters"] = has_category_filters

    # Generate insight about marketplace coverage readiness
    total_signals = sum(
        [
            has_availability_model,
            has_reputation_model,
            has_sharing_prefs,
            has_active_flag or has_available_flag,
            has_category_filters,
        ]
    )
    coverage_readiness = total_signals / 5.0

    insights.append(
        OpsInsight(
            id="marsh-insight-001",
            category="marketplace_health",
            title="Marketplace coverage signal readiness",
            evidence=(
                f"{total_signals}/5 coverage signals present: "
                f"availability={'Y' if has_availability_model else 'N'}, "
                f"reputation={'Y' if has_reputation_model else 'N'}, "
                f"sharing_prefs={'Y' if has_sharing_prefs else 'N'}, "
                f"active_flag={'Y' if (has_active_flag or has_available_flag) else 'N'}, "
                f"category_filters={'Y' if has_category_filters else 'N'}"
            ),
            impact="Coverage signals determine whether the marketplace can surface meaningful supply-demand matches",
            recommendation=(
                "All 5 coverage signals should be present for marketplace health monitoring"
                if coverage_readiness < 1.0
                else "Full coverage signal set in place -- monitor for drift"
            ),
            confidence=0.85,
            persona="both",
            actionable_by="engineering",
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> OpsTeamReport:
    """Run all marketplace health checks and return an OpsTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    mkt_findings: list[MarketplaceFinding] = []
    insights: list[OpsInsight] = []
    metrics: dict = {}

    # Read source files
    model_path = MODELS_DIR / "marketplace.py"
    credit_svc_path = SERVICES_DIR / "credits.py"
    marketplace_api_path = API_DIR / "marketplace.py"
    credits_api_path = API_DIR / "credits.py"

    model_source = _read_safe(model_path)
    credit_source = _read_safe(credit_svc_path)
    marketplace_api_source = _read_safe(marketplace_api_path)
    credits_api_source = _read_safe(credits_api_path)

    metrics["files_scanned"] = sum(
        1
        for s in [
            model_source,
            credit_source,
            marketplace_api_source,
            credits_api_source,
        ]
        if s
    )
    metrics["files_expected"] = 4

    if not model_source:
        findings.append(
            Finding(
                id="marsh-000",
                severity="critical",
                category="model_completeness",
                title="Marketplace model file not found or empty",
                detail=f"Could not read {_relative(model_path)}",
                file=_relative(model_path),
                recommendation="app/models/marketplace.py is required for the marketplace to function",
            )
        )

    # Run checks
    _check_marketplace_model(model_source, findings, mkt_findings, metrics)
    _check_credit_economy(
        credit_source,
        credits_api_source,
        findings,
        mkt_findings,
        metrics,
        marketplace_api_source=marketplace_api_source,
    )
    _check_intro_pipeline(marketplace_api_source, findings, mkt_findings, metrics)

    all_sources = {
        "model": model_source,
        "credit_service": credit_source,
        "marketplace_api": marketplace_api_source,
        "credits_api": credits_api_source,
    }
    _check_marketplace_actions(all_sources, findings, mkt_findings, metrics)
    _check_suppression_impact(
        model_source, marketplace_api_source, findings, mkt_findings, metrics
    )
    _check_coverage_signals(model_source, findings, insights, metrics)

    duration = time.time() - start

    # -- Generate summary insight --
    total_findings = len(findings)
    high_or_critical = sum(1 for f in findings if f.severity in ("critical", "high"))
    insights.append(
        OpsInsight(
            id="marsh-insight-002",
            category="marketplace_health",
            title="Marketplace health summary",
            evidence=(
                f"{total_findings} findings ({high_or_critical} high/critical), "
                f"{metrics.get('marketplace_action_coverage', 0):.0%} action coverage, "
                f"{metrics.get('pipeline_statuses_found', 0)}/{metrics.get('pipeline_statuses_expected', 0)} "
                f"pipeline statuses, "
                f"{metrics.get('earn_actions_found', 0)} earn + {metrics.get('spend_actions_found', 0)} spend actions"
            ),
            impact="Marketplace structural completeness directly affects revenue readiness and trust",
            recommendation=(
                "Address high/critical findings before launch to avoid broken marketplace flows"
                if high_or_critical > 0
                else "Marketplace structure is sound -- monitor for drift as features evolve"
            ),
            confidence=0.9,
            persona="both",
            actionable_by="engineering",
        )
    )

    # -- Learning: record scan, findings, attention weights, health snapshot --
    ls = OpsLearningState(AGENT_NAME)
    ls.record_scan(metrics)

    file_findings: dict[str, int] = {}
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
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1

    for mf in mkt_findings:
        ls.record_finding(
            {
                "id": mf.id,
                "severity": mf.severity,
                "category": mf.category,
                "title": mf.title,
                "file": mf.file,
            }
        )

    if file_findings:
        ls.update_attention_weights(file_findings)

    for ins in insights:
        ls.record_insight(
            {
                "id": ins.id,
                "category": ins.category,
                "title": ins.title,
                "confidence": ins.confidence,
            }
        )

    # Health snapshot (higher = healthier; penalize by finding severity)
    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    # Track KPIs
    ls.track_kpi(
        "marketplace_action_coverage", metrics.get("marketplace_action_coverage", 0)
    )
    ls.track_kpi("pipeline_statuses_found", metrics.get("pipeline_statuses_found", 0))
    ls.track_kpi("earn_action_count", metrics.get("earn_actions_found", 0))
    ls.track_kpi("spend_action_count", metrics.get("spend_actions_found", 0))
    ls.track_kpi("listing_field_coverage", metrics.get("listing_fields_found", 0))

    # Learning updates for CoS consumption
    learning_updates: list[str] = [
        f"Scanned {metrics.get('files_scanned', 0)}/{metrics.get('files_expected', 0)} marketplace files",
        f"Marketplace action coverage: {metrics.get('marketplace_action_coverage', 0):.0%}",
        f"Pipeline statuses: {metrics.get('pipeline_statuses_found', 0)}/{metrics.get('pipeline_statuses_expected', 0)}",
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )
    patterns = ls.state.get("recurring_patterns", {})
    escalated = [k for k, v in patterns.items() if v.get("auto_escalated")]
    if escalated:
        learning_updates.append(f"Escalated patterns: {len(escalated)}")

    return OpsTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        marketplace_findings=mkt_findings,
        ops_insights=insights,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: OpsTeamReport) -> Path:
    """Save report to ops_team/reports/marsh_latest.json."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / "marsh_latest.json"
    path.write_text(report.serialize())
    logger.info("marsh: report saved to %s", path)
    return path
