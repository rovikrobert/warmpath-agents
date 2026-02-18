"""Partnerships & Community Manager agent — supply-side recruitment readiness, referral
program features, community infrastructure, partnership integration points, network
holder value proposition analysis.

Scans CLAUDE.md, app/api/contacts.py, app/services/marketplace_indexer.py, and
frontend/src/pages/*.jsx for partnership and community readiness signals.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from agents.shared.report import Finding
from gtm_team.shared.config import (
    API_DIR,
    PAGES_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    SERVICES_DIR,
)
from gtm_team.shared.learning import GTMLearningState
from gtm_team.shared.report import (
    GTMTeamReport,
    MarketInsight,
    PartnershipOpportunity,
)
from gtm_team.shared.strategy_context import (
    extract_personas,
    extract_pricing_info,
    get_strategy_doc,
)

logger = logging.getLogger(__name__)

AGENT_NAME = "partnerships"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_safe(path: Path) -> str:
    """Read file, returning empty string on failure."""
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _relative(path: Path) -> str:
    """Return path relative to project root."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _find_jsx_files() -> list[Path]:
    """Return all .jsx files under frontend/src/pages/."""
    if not PAGES_DIR.is_dir():
        return []
    return sorted(PAGES_DIR.glob("*.jsx"))


# ---------------------------------------------------------------------------
# Check functions
# ---------------------------------------------------------------------------


def _check_supply_side_readiness(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan app/api/ for CSV upload, marketplace opt-in endpoints."""
    contacts_api = API_DIR / "contacts.py"
    contacts_content = _read_safe(contacts_api)

    marketplace_api = API_DIR / "marketplace.py"
    marketplace_content = _read_safe(marketplace_api)

    marketplace_indexer = SERVICES_DIR / "marketplace_indexer.py"
    indexer_content = _read_safe(marketplace_indexer)

    # Core supply-side features
    supply_source = contacts_content + "\n" + marketplace_content
    has_csv_upload = bool(
        re.search(r"(?:upload|csv|import)", contacts_content, re.IGNORECASE)
    )
    has_marketplace_opt_in = bool(
        re.search(
            r"(?:opt.in.marketplace|sharing.preferences|opt_in_marketplace)",
            supply_source,
            re.IGNORECASE,
        )
    )
    has_indexer = bool(indexer_content.strip())
    has_anonymization = bool(
        re.search(r"(?:anonym|hash|blind.index)", indexer_content, re.IGNORECASE)
    )

    metrics["supply_has_csv_upload"] = has_csv_upload
    metrics["supply_has_marketplace_opt_in"] = has_marketplace_opt_in
    metrics["supply_has_indexer"] = has_indexer
    metrics["supply_has_anonymization"] = has_anonymization

    supply_score = sum(
        [has_csv_upload, has_marketplace_opt_in, has_indexer, has_anonymization]
    )
    metrics["supply_readiness_score"] = supply_score

    if not has_csv_upload:
        findings.append(
            Finding(
                id="prt-supply-001",
                severity="high",
                category="supply_readiness",
                title="CSV upload endpoint not detected in contacts API",
                detail="No upload/csv/import patterns found in contacts.py",
                file=_relative(contacts_api),
                recommendation="Verify CSV upload endpoint exists — core for network holder onboarding",
            )
        )

    if not has_marketplace_opt_in:
        findings.append(
            Finding(
                id="prt-supply-002",
                severity="high",
                category="supply_readiness",
                title="Marketplace opt-in not detected in contacts API",
                detail="No opt-in/marketplace/sharing patterns found in contacts.py",
                file=_relative(contacts_api),
                recommendation="Verify marketplace opt-in endpoint exists — required for supply side",
            )
        )

    if not has_indexer:
        findings.append(
            Finding(
                id="prt-supply-003",
                severity="high",
                category="supply_readiness",
                title="Marketplace indexer service is empty or missing",
                detail="marketplace_indexer.py has no content — anonymized index generation blocked",
                file=_relative(marketplace_indexer),
                recommendation="Implement marketplace indexer with anonymized listing generation",
            )
        )

    # Check frontend for NH onboarding pages
    jsx_files = _find_jsx_files()
    nh_pages = ["SharingSettings.jsx", "OnboardingPage.jsx"]
    nh_pages_found = []
    for path in jsx_files:
        if path.name in nh_pages:
            nh_pages_found.append(path.name)

    metrics["nh_onboarding_pages"] = nh_pages_found

    if "SharingSettings.jsx" not in nh_pages_found:
        findings.append(
            Finding(
                id="prt-supply-004",
                severity="medium",
                category="supply_readiness",
                title="No SharingSettings page for network holders",
                detail="Network holders need a dedicated page to manage what they share",
                recommendation="Create SharingSettings.jsx with marketplace opt-in controls",
            )
        )

    if supply_score >= 3:
        insights.append(
            MarketInsight(
                id="prt-supply-insight-001",
                category="market_entry",
                title="Supply-side infrastructure largely ready",
                evidence=f"Supply readiness score: {supply_score}/4",
                strategic_impact="Platform can support network holder recruitment",
                recommended_response="Begin outreach to seed network holders",
                urgency="this_week",
                confidence="high",
            )
        )


def _check_referral_program_features(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan credits system for referral incentives."""
    # Check credits API/service
    credits_api = API_DIR / "credits.py"
    credits_content = _read_safe(credits_api)

    # Also check for credit service files
    credits_service = SERVICES_DIR / "credits.py"
    credits_svc_content = _read_safe(credits_service)
    combined_credits = credits_content + credits_svc_content

    # Scan all API files for credit-related patterns
    if not combined_credits.strip():
        api_files = sorted(API_DIR.glob("*.py")) if API_DIR.is_dir() else []
        for api_file in api_files:
            content = _read_safe(api_file)
            if re.search(r"credit", content, re.IGNORECASE):
                combined_credits += content

    # Core referral program features
    has_earn_actions = bool(
        re.search(r"(?:earn|reward|grant|add.credit)", combined_credits, re.IGNORECASE)
    )
    has_spend_actions = bool(
        re.search(
            r"(?:spend|deduct|charge|use.credit)", combined_credits, re.IGNORECASE
        )
    )
    has_balance = bool(
        re.search(r"(?:balance|total|sum)", combined_credits, re.IGNORECASE)
    )
    has_history = bool(
        re.search(r"(?:history|transaction|log)", combined_credits, re.IGNORECASE)
    )

    metrics["credits_has_earn"] = has_earn_actions
    metrics["credits_has_spend"] = has_spend_actions
    metrics["credits_has_balance"] = has_balance
    metrics["credits_has_history"] = has_history

    credits_score = sum([has_earn_actions, has_spend_actions, has_balance, has_history])
    metrics["credits_feature_score"] = credits_score

    if not has_earn_actions:
        findings.append(
            Finding(
                id="prt-ref-001",
                severity="medium",
                category="referral_program",
                title="No credit earn actions detected",
                detail="No earn/reward/grant patterns found in credits endpoints",
                recommendation="Implement credit earn actions: CSV upload (100), intro facilitation (50), data freshness (10)",
            )
        )

    if not has_spend_actions:
        findings.append(
            Finding(
                id="prt-ref-002",
                severity="medium",
                category="referral_program",
                title="No credit spend actions detected",
                detail="No spend/deduct/charge patterns found in credits endpoints",
                recommendation="Implement credit spend: cross-network search (5), intro request (20)",
            )
        )

    # Check frontend for credits visibility
    jsx_files = _find_jsx_files()
    credits_in_ui = False
    for path in jsx_files:
        content = _read_safe(path)
        if re.search(r"(?:credits?|balance|earn|reward)", content, re.IGNORECASE):
            credits_in_ui = True
            break

    metrics["credits_visible_in_ui"] = credits_in_ui

    if not credits_in_ui:
        findings.append(
            Finding(
                id="prt-ref-003",
                severity="medium",
                category="referral_program",
                title="Credits not visible in frontend UI",
                detail="No credit/balance/earn references found in JSX pages",
                recommendation="Add credit balance display and earn/spend history to user dashboard",
            )
        )

    # Check CLAUDE.md for credit economy spec
    claude_md = get_strategy_doc("CLAUDE.md")
    pricing_info = extract_pricing_info({"CLAUDE.md": claude_md} if claude_md else None)
    credit_economy = pricing_info.get("credit_economy", {})
    metrics["strategy_credit_economy_defined"] = bool(credit_economy)


def _check_community_infrastructure(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan JSX pages for community features."""
    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path) + "\n"

    # Community feature patterns
    community_features = {
        "sharing": re.compile(r"(?:share|sharing|invite)", re.IGNORECASE),
        "social_proof": re.compile(
            r"(?:testimonial|success\s+stor|review|rating|\d+\s*(?:users?|referrals?))",
            re.IGNORECASE,
        ),
        "leaderboard": re.compile(
            r"(?:leaderboard|top\s+connectors?|ranking|score)", re.IGNORECASE
        ),
        "success_stories": re.compile(
            r"(?:success|story|stories|testimonial|case\s+study)", re.IGNORECASE
        ),
        "connector_score": re.compile(
            r"(?:connector|reputation|score|badge|level)", re.IGNORECASE
        ),
        "notifications": re.compile(
            r"(?:notification|alert|notify|bell)", re.IGNORECASE
        ),
    }

    features_found: dict[str, bool] = {}
    for feature_name, pattern in community_features.items():
        features_found[feature_name] = bool(pattern.search(all_content))

    found_count = sum(1 for v in features_found.values() if v)
    total = len(features_found)
    community_score = round(found_count / max(1, total), 2)

    metrics["community_features_found"] = found_count
    metrics["community_features_total"] = total
    metrics["community_score"] = community_score
    metrics["community_feature_detail"] = {k: v for k, v in features_found.items()}

    missing = [k for k, v in features_found.items() if not v]

    if found_count < 3:
        findings.append(
            Finding(
                id="prt-comm-001",
                severity="medium",
                category="community",
                title=f"Limited community infrastructure ({found_count}/{total} features)",
                detail=f"Missing: {', '.join(missing)}",
                recommendation="Add social proof, leaderboard, and connector scores to drive engagement",
            )
        )

    if not features_found.get("leaderboard"):
        insights.append(
            MarketInsight(
                id="prt-comm-insight-001",
                category="channel",
                title="No leaderboard/connector ranking system",
                evidence="No leaderboard/ranking patterns found in frontend",
                strategic_impact="Network holders lack visible status incentive (motivation #4 in CLAUDE.md)",
                recommended_response="Build top connectors leaderboard to drive supply-side engagement",
                urgency="this_month",
                confidence="medium",
            )
        )


def _check_partnership_integration_points(
    findings: list[Finding],
    partnerships: list[PartnershipOpportunity],
    metrics: dict,
) -> None:
    """Scan API for extensibility (white-label potential, partner API endpoints)."""
    api_files = sorted(API_DIR.glob("*.py")) if API_DIR.is_dir() else []
    all_api_content = ""
    api_file_names: list[str] = []

    for path in api_files:
        content = _read_safe(path)
        all_api_content += content + "\n"
        api_file_names.append(path.name)

    metrics["total_api_files"] = len(api_files)

    # Check for partner-facing patterns
    has_partner_api = bool(
        re.search(r"(?:partner|affiliate|white.?label)", all_api_content, re.IGNORECASE)
    )
    has_batch_endpoints = bool(
        re.search(r"(?:batch|bulk|import.all)", all_api_content, re.IGNORECASE)
    )
    has_webhook_out = bool(
        re.search(
            r"(?:webhook|callback|notify.partner)", all_api_content, re.IGNORECASE
        )
    )
    has_api_keys = bool(
        re.search(r"(?:api.key|partner.key|client.id)", all_api_content, re.IGNORECASE)
    )

    metrics["api_has_partner_endpoints"] = has_partner_api
    metrics["api_has_batch_endpoints"] = has_batch_endpoints
    metrics["api_has_webhook_out"] = has_webhook_out
    metrics["api_has_api_keys"] = has_api_keys

    extensibility_score = sum(
        [has_partner_api, has_batch_endpoints, has_webhook_out, has_api_keys]
    )
    metrics["api_extensibility_score"] = extensibility_score

    if extensibility_score == 0:
        findings.append(
            Finding(
                id="prt-integ-001",
                severity="info",
                category="partnership_integration",
                title="No partner integration points detected",
                detail="No partner API, batch endpoints, outbound webhooks, or API keys found",
                recommendation="Plan partner API for bootcamp/university integrations post-MVP",
            )
        )

    # Identify partnership opportunities based on codebase
    personas = extract_personas()

    if personas.get("has_bootcamp_persona"):
        partnerships.append(
            PartnershipOpportunity(
                id="prt-opp-bootcamp",
                partner_name="Coding Bootcamps (General Assembly, Le Wagon, etc.)",
                partner_type="bootcamp",
                value_prop_to_them="Higher placement rates via referral access for graduates",
                value_prop_to_us="Pre-qualified demand-side users with high activation potential",
                estimated_user_impact="50-200 users per cohort partnership",
                estimated_revenue_impact="$1K-4K/month per bootcamp at $20/user",
                effort="medium",
                stage="identified",
                next_action="Research top 10 bootcamps in Singapore/SEA for outreach",
            )
        )

    if personas.get("has_coach_persona"):
        partnerships.append(
            PartnershipOpportunity(
                id="prt-opp-coaches",
                partner_name="Career Coaches (independent + firms)",
                partner_type="co_marketing",
                value_prop_to_them="Concrete referral tool to offer clients (not just advice)",
                value_prop_to_us="Multiplier channel — each coach brings 5-20 active seekers",
                estimated_user_impact="5-20 users per coach",
                estimated_revenue_impact="$100-600/month per coach relationship",
                effort="low",
                stage="identified",
                next_action="Create coach partnership landing page + affiliate/referral link",
            )
        )

    # Always suggest university partnership
    partnerships.append(
        PartnershipOpportunity(
            id="prt-opp-university",
            partner_name="University Career Services (NUS, NTU, SMU)",
            partner_type="university",
            value_prop_to_them="Better employment outcomes via alumni referral networks",
            value_prop_to_us="Volume demand-side users, brand credibility, institutional partnerships",
            estimated_user_impact="100-500 graduating students per university per year",
            estimated_revenue_impact="$2K-10K/month per university partnership",
            effort="high",
            stage="identified",
            next_action="Pilot with one Singapore university career center",
            legal_review_required=True,
            legal_review_status="not_required",
        )
    )


def _check_network_holder_value_prop(
    jsx_files: list[Path],
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Scan strategy docs and frontend for NH value proposition messaging."""
    claude_md = get_strategy_doc("CLAUDE.md")

    # Check CLAUDE.md for NH motivation documentation
    nh_motivations = {
        "referral_bonuses": re.compile(r"referral\s+bonus", re.IGNORECASE),
        "reputation": re.compile(r"reputation|connector\s+score", re.IGNORECASE),
        "credits": re.compile(r"credits?\s+(?:for|bank|earn)", re.IGNORECASE),
        "dealflow": re.compile(r"dealflow|leaderboard|early\s+access", re.IGNORECASE),
    }

    strategy_nh_coverage: dict[str, bool] = {}
    for motive_name, pattern in nh_motivations.items():
        strategy_nh_coverage[motive_name] = (
            bool(pattern.search(claude_md)) if claude_md else False
        )

    strategy_count = sum(1 for v in strategy_nh_coverage.values() if v)
    metrics["strategy_nh_motivations_documented"] = strategy_count
    metrics["strategy_nh_motivation_detail"] = {
        k: v for k, v in strategy_nh_coverage.items()
    }

    # Check frontend for NH value prop messaging
    all_content = ""
    for path in jsx_files:
        all_content += _read_safe(path) + "\n"

    frontend_nh_patterns = {
        "referral_bonus_mention": re.compile(
            r"(?:referral\s+bonus|earn\s+.{0,20}referr|bonus|bounty)", re.IGNORECASE
        ),
        "reputation_mention": re.compile(
            r"(?:reputation|connector|trust\s+score|profile\s+score)", re.IGNORECASE
        ),
        "credits_mention": re.compile(
            r"(?:earn\s+credits?|free\s+credits?|credit\s+balance)", re.IGNORECASE
        ),
        "nh_specific_cta": re.compile(
            r"(?:share\s+your\s+network|upload\s+(?:your\s+)?connections?|help\s+someone\s+get\s+referred)",
            re.IGNORECASE,
        ),
    }

    frontend_nh_coverage: dict[str, bool] = {}
    for feature_name, pattern in frontend_nh_patterns.items():
        frontend_nh_coverage[feature_name] = bool(pattern.search(all_content))

    frontend_count = sum(1 for v in frontend_nh_coverage.values() if v)
    metrics["frontend_nh_value_prop_signals"] = frontend_count
    metrics["frontend_nh_value_prop_detail"] = {
        k: v for k, v in frontend_nh_coverage.items()
    }

    nh_total = strategy_count + frontend_count
    metrics["nh_value_prop_total_score"] = nh_total

    missing_frontend = [k for k, v in frontend_nh_coverage.items() if not v]
    if frontend_count < 2:
        findings.append(
            Finding(
                id="prt-nhvp-001",
                severity="medium",
                category="nh_value_prop",
                title=f"Weak network holder value proposition in UI ({frontend_count}/4 signals)",
                detail=f"Missing in frontend: {', '.join(missing_frontend)}",
                recommendation="Strengthen NH-facing messaging: referral bonuses, credits earned, reputation building",
            )
        )

    if not frontend_nh_coverage.get("referral_bonus_mention"):
        insights.append(
            MarketInsight(
                id="prt-nhvp-insight-001",
                category="market_entry",
                title="Referral bonus messaging absent from frontend",
                evidence="No referral bonus/bounty/earn references found in JSX pages",
                strategic_impact="Primary NH motivation (#1 in CLAUDE.md) is not communicated to users",
                recommended_response="Add prominent referral bonus messaging to SharingSettings and onboarding",
                urgency="this_week",
                confidence="high",
            )
        )

    if strategy_count >= 3 and frontend_count < 2:
        insights.append(
            MarketInsight(
                id="prt-nhvp-insight-002",
                category="competitive",
                title="Strategy-to-frontend gap on NH value prop",
                evidence=f"Strategy docs cover {strategy_count}/4 motivations but frontend only shows {frontend_count}/4",
                strategic_impact="NH recruitment effectiveness limited by weak frontend messaging",
                recommended_response="Translate CLAUDE.md NH motivations into user-facing copy on key pages",
                urgency="this_month",
                confidence="high",
            )
        )


def _check_pipeline_infrastructure(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check that the partnership pipeline API/model infrastructure exists."""
    model_file = PROJECT_ROOT / "app" / "models" / "gtm.py"
    api_file = PROJECT_ROOT / "app" / "api" / "partnerships.py"
    service_file = PROJECT_ROOT / "app" / "services" / "gtm_service.py"

    has_model = model_file.exists() and "PartnershipOpportunity" in _read_safe(
        model_file
    )
    has_api = api_file.exists()
    has_service = (
        service_file.exists() and "partnership" in _read_safe(service_file).lower()
    )

    metrics["pipeline_model_exists"] = has_model
    metrics["pipeline_api_exists"] = has_api
    metrics["pipeline_service_exists"] = has_service

    if not has_model:
        findings.append(
            Finding(
                id="PART-NO-PIPELINE-MODEL",
                severity="high",
                category="partnership",
                title="Partnership pipeline DB model missing",
                detail="No PartnershipOpportunity model in app/models/gtm.py",
                recommendation="Create partnership_opportunities table for CRM-style pipeline tracking",
                effort_hours=2.0,
            )
        )

    # Check for dynamic (not hardcoded) partner types
    scanner_content = _read_safe(Path(__file__))
    hardcoded_types = (
        scanner_content.count("bootcamp")
        + scanner_content.count("university")
        + scanner_content.count("career_coach")
    )
    metrics["partnership_types_hardcoded"] = hardcoded_types > 3

    pipeline_status = (
        "full"
        if (has_model and has_api and has_service)
        else "partial"
        if any([has_model, has_api, has_service])
        else "none"
    )

    insights.append(
        MarketInsight(
            id="part-insight-pipeline",
            category="partnership",
            title=f"Partnership pipeline infrastructure: {pipeline_status}",
            evidence=f"Model: {has_model}, API: {has_api}, Service: {has_service}",
            strategic_impact="Pipeline tracking enables partnership velocity measurement",
            recommended_response="Pipeline infrastructure is in place"
            if pipeline_status == "full"
            else "Complete pipeline setup",
            urgency="monitor" if pipeline_status == "full" else "this_week",
            confidence="high",
        )
    )


def _check_supply_activation_data(
    findings: list[Finding],
    insights: list[MarketInsight],
    metrics: dict,
) -> None:
    """Check that data sources exist for NH activation metrics."""
    models_content = _read_safe(PROJECT_ROOT / "app" / "models" / "marketplace.py")
    sharing_prefs = (
        "NetworkSharingPreferences" in models_content
        or "network_sharing_preferences" in models_content
    )
    marketplace_listings = "MarketplaceListing" in models_content

    contacts_content = _read_safe(PROJECT_ROOT / "app" / "models" / "contact.py")
    csv_uploads = "CsvUpload" in contacts_content

    usage_content = _read_safe(PROJECT_ROOT / "app" / "models" / "enrichment.py")
    usage_logs = "UsageLog" in usage_content

    activation_sources = {
        "csv_uploads": csv_uploads,
        "sharing_preferences": sharing_prefs,
        "marketplace_listings": marketplace_listings,
        "usage_logs": usage_logs,
    }

    metrics["activation_data_sources"] = activation_sources
    metrics["activation_data_coverage"] = (
        sum(activation_sources.values()) / len(activation_sources) * 100
    )

    missing = [k for k, v in activation_sources.items() if not v]
    if missing:
        findings.append(
            Finding(
                id="PART-ACTIVATION-DATA-GAPS",
                severity="medium",
                category="partnership",
                title=f"Supply-side activation: {len(missing)} data sources missing",
                detail=f"Missing: {', '.join(missing)}",
                recommendation="Ensure all activation metric data sources are available",
                effort_hours=1.0,
            )
        )

    insights.append(
        MarketInsight(
            id="part-insight-activation",
            category="partnership",
            title=f"Supply-side data: {metrics['activation_data_coverage']:.0f}% sources available",
            evidence=(
                f"Available: {', '.join(k for k, v in activation_sources.items() if v)}. "
                f"Missing: {', '.join(missing) if missing else 'none'}."
            ),
            strategic_impact="Activation data enables NH churn prediction and engagement optimization",
            recommended_response="All key data sources available"
            if not missing
            else "Add missing data collection",
            urgency="monitor" if not missing else "this_week",
            confidence="high",
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan() -> GTMTeamReport:
    """Run all partnership and community checks and return a GTMTeamReport."""
    start = time.time()
    findings: list[Finding] = []
    insights: list[MarketInsight] = []
    partnerships: list[PartnershipOpportunity] = []
    metrics: dict = {}

    jsx_files = _find_jsx_files()
    metrics["total_jsx_pages"] = len(jsx_files)

    _check_supply_side_readiness(findings, insights, metrics)
    _check_referral_program_features(findings, insights, metrics)
    _check_community_infrastructure(jsx_files, findings, insights, metrics)
    _check_partnership_integration_points(findings, partnerships, metrics)
    _check_network_holder_value_prop(jsx_files, findings, insights, metrics)

    # Pipeline infrastructure and supply-side activation data
    _check_pipeline_infrastructure(findings, insights, metrics)
    _check_supply_activation_data(findings, insights, metrics)

    # Compute partnership readiness score
    score_components = {
        "supply_readiness": min(1.0, metrics.get("supply_readiness_score", 0) / 4),
        "credits_features": min(1.0, metrics.get("credits_feature_score", 0) / 4),
        "community": metrics.get("community_score", 0),
        "api_extensibility": min(1.0, metrics.get("api_extensibility_score", 0) / 4),
        "nh_value_prop": min(1.0, metrics.get("nh_value_prop_total_score", 0) / 8),
    }
    weights = {
        "supply_readiness": 0.30,
        "credits_features": 0.20,
        "community": 0.15,
        "api_extensibility": 0.10,
        "nh_value_prop": 0.25,
    }

    weighted_sum = sum(score_components.get(k, 0) * weights.get(k, 0) for k in weights)
    total_weight = sum(weights.values())
    readiness_score = round(weighted_sum / max(0.01, total_weight) * 100, 1)
    metrics["partnership_readiness_score"] = readiness_score

    duration = time.time() - start

    # Learning — record scan, findings, health snapshot
    ls = GTMLearningState(AGENT_NAME)
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
        if f.file:
            file_findings[f.file] = file_findings.get(f.file, 0) + 1
    if file_findings:
        ls.update_attention_weights(file_findings)

    for f in findings:
        ls.record_severity_calibration(f.severity)

    severity_penalty = {"critical": 20, "high": 10, "medium": 3, "low": 1, "info": 0}
    penalty = sum(severity_penalty.get(f.severity, 0) for f in findings)
    health = max(0.0, 100.0 - penalty)
    finding_counts: dict[str, int] = {}
    for f in findings:
        finding_counts[f.severity] = finding_counts.get(f.severity, 0) + 1
    ls.record_health_snapshot(health, finding_counts)

    ls.track_kpi("partnership_readiness_score", readiness_score)
    ls.track_kpi("partnership_opportunities", len(partnerships))

    learning_updates = [
        f"Scanned supply/credits/community, readiness={readiness_score}",
        f"Identified {len(partnerships)} partnership opportunities",
    ]
    hot_spots = ls.get_hot_spots(top_n=3)
    if hot_spots:
        learning_updates.append(
            f"Hot spots: {', '.join(h.file.split('/')[-1] for h in hot_spots)}"
        )

    return GTMTeamReport(
        agent=AGENT_NAME,
        scan_duration_seconds=round(duration, 2),
        findings=findings,
        market_insights=insights,
        partnership_opportunities=partnerships,
        metrics=metrics,
        learning_updates=learning_updates,
    )


def save_report(report: GTMTeamReport) -> Path:
    """Save report to gtm_team/reports/."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{AGENT_NAME}_latest.json"
    path.write_text(report.serialize())
    return path
