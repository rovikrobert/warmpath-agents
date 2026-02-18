"""Business outcome definitions and alignment scoring for CoS agent."""

from __future__ import annotations

# The 4 business outcomes (priority order — higher index = lower priority)
HELP_JOB_SEEKERS = "help_job_seekers"
HELP_NETWORK_BUILDERS = "network_builders"
BILLION_DOLLAR = "billion_dollar"
COST_EFFICIENCY = "cost_efficiency"

OUTCOME_PRIORITY = [
    HELP_JOB_SEEKERS,
    HELP_NETWORK_BUILDERS,
    BILLION_DOLLAR,
    COST_EFFICIENCY,
]

OUTCOME_LABELS = {
    HELP_JOB_SEEKERS: "Help Job Seekers Get Referred",
    HELP_NETWORK_BUILDERS: "Help Network Holders Monetize Connections",
    BILLION_DOLLAR: "Build Billion-Dollar Infrastructure",
    COST_EFFICIENCY: "Maximize Cost Efficiency",
}

# Mapping: engineering finding category -> most-aligned outcomes
CATEGORY_OUTCOME_MAP: dict[str, list[str]] = {
    "security": [HELP_JOB_SEEKERS, BILLION_DOLLAR],
    "privacy": [HELP_JOB_SEEKERS, BILLION_DOLLAR],
    "performance": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "test_quality": [BILLION_DOLLAR, COST_EFFICIENCY],
    "architecture": [BILLION_DOLLAR, COST_EFFICIENCY],
    "dependencies": [BILLION_DOLLAR, COST_EFFICIENCY],
    "documentation": [COST_EFFICIENCY],
    "code_quality": [BILLION_DOLLAR, COST_EFFICIENCY],
    "database": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "ai_matching": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "marketplace": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "csv_processing": [HELP_NETWORK_BUILDERS, COST_EFFICIENCY],
    # Data team categories
    "data_quality": [HELP_JOB_SEEKERS, BILLION_DOLLAR],
    "instrumentation": [BILLION_DOLLAR, COST_EFFICIENCY],
    "model_calibration": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "schema_coverage": [BILLION_DOLLAR, COST_EFFICIENCY],
    "privacy_compliance": [HELP_JOB_SEEKERS, BILLION_DOLLAR],
    # Product team categories
    "ux_quality": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "design_system": [BILLION_DOLLAR, COST_EFFICIENCY],
    "feature_coverage": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "user_research": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "product_strategy": [BILLION_DOLLAR, HELP_JOB_SEEKERS],
    # Ops team categories
    "coaching_effectiveness": [HELP_JOB_SEEKERS],
    "supply_activation": [HELP_NETWORK_BUILDERS],
    "user_satisfaction": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "marketplace_health": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    "ops_efficiency": [COST_EFFICIENCY],
    "streaming": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "api_quality": [HELP_JOB_SEEKERS, BILLION_DOLLAR],
    "error_handling": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "empty_state": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "journey_milestone": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "feedback_collection": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "coaching_quality": [HELP_JOB_SEEKERS],
    "nh_journey": [HELP_NETWORK_BUILDERS],
    "sharing_controls": [HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    "intro_facilitation": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "credit_economy": [HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    "marketplace_coverage": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    # Finance team categories
    "stripe_integration": [BILLION_DOLLAR, COST_EFFICIENCY],
    "credit_regulation": [BILLION_DOLLAR, HELP_NETWORK_BUILDERS],
    "cost_tracking": [COST_EFFICIENCY],
    "billing": [BILLION_DOLLAR, COST_EFFICIENCY],
    "compliance": [BILLION_DOLLAR, HELP_JOB_SEEKERS],
    "money_transmitter": [BILLION_DOLLAR],
    "investor_readiness": [BILLION_DOLLAR],
    "financial_model": [BILLION_DOLLAR, COST_EFFICIENCY],
    # GTM team categories
    "competitive_positioning": [BILLION_DOLLAR, HELP_JOB_SEEKERS],
    "market_entry": [BILLION_DOLLAR, HELP_JOB_SEEKERS],
    "pricing_strategy": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "customer_acquisition": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "supply_recruitment": [HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    "marketing_compliance": [BILLION_DOLLAR, COST_EFFICIENCY],
    "channel_readiness": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "partnership_pipeline": [HELP_NETWORK_BUILDERS, BILLION_DOLLAR],
    "brand_messaging": [HELP_JOB_SEEKERS, HELP_NETWORK_BUILDERS],
    "content_strategy": [HELP_JOB_SEEKERS, COST_EFFICIENCY],
    "revenue_model": [BILLION_DOLLAR, COST_EFFICIENCY],
    "credit_strategy": [HELP_NETWORK_BUILDERS, COST_EFFICIENCY],
}

# Business impact templates by category + severity
_IMPACT_TEMPLATES: dict[str, dict[str, str]] = {
    "security": {
        "critical": "Existential risk — data breach could destroy user trust and trigger regulatory action",
        "high": "User data at risk — could erode trust and violate PDPA/GDPR obligations",
        "medium": "Security gap that sophisticated attackers could exploit",
        "low": "Minor hardening opportunity",
    },
    "privacy": {
        "critical": "PII exposure risk — violates core vault-boundary promise to all 4 parties",
        "high": "Privacy architecture gap that could leak contact identity across vaults",
        "medium": "Privacy control that needs strengthening for compliance",
        "low": "Privacy best-practice improvement",
    },
    "performance": {
        "critical": "Platform unusable — job seekers will churn before finding referrals",
        "high": "Slow experience degrades search-to-referral conversion",
        "medium": "Performance drag that affects user satisfaction",
        "low": "Optimization opportunity for cost/speed",
    },
    "test_quality": {
        "critical": "Test gaps in critical paths — deploys could break referral flow",
        "high": "Insufficient coverage on key features",
        "medium": "Test quality issue that increases regression risk",
        "low": "Test improvement opportunity",
    },
    "data_quality": {
        "critical": "Data integrity risk — analytics decisions based on incorrect/incomplete data",
        "high": "Data quality gap that will produce misleading metrics when analytics goes live",
        "medium": "Data quality issue to fix before scaling analytics",
        "low": "Data hygiene improvement",
    },
    "model_calibration": {
        "critical": "Warm score unreliable — job seekers routed to wrong contacts, destroying trust",
        "high": "Model calibration gap that degrades match quality for job seekers",
        "medium": "Calibration opportunity that would improve referral success rates",
        "low": "Minor model tuning opportunity",
    },
    "ux_quality": {
        "critical": "Major UX barrier — users cannot complete core referral flow",
        "high": "UX friction causing drop-off in search-to-referral conversion",
        "medium": "UX issue that degrades user experience and satisfaction",
        "low": "Minor UX improvement opportunity",
    },
    "feature_coverage": {
        "critical": "Core feature missing — critical user journey is broken",
        "high": "Feature gap that prevents users from completing key workflows",
        "medium": "Feature coverage gap affecting secondary workflows",
        "low": "Minor feature enhancement opportunity",
    },
    # Ops team impact templates
    "coaching_effectiveness": {
        "critical": "Coaching service broken — job seekers get no guidance on referral strategy",
        "high": "Coach response quality gap degrading job seeker conversion",
        "medium": "Coaching improvement that would lift referral success rates",
        "low": "Minor coaching quality enhancement",
    },
    "supply_activation": {
        "critical": "NH journey broken — network holders cannot activate or earn from their network",
        "high": "Supply-side gap reducing NH engagement and retention",
        "medium": "NH experience issue affecting activation or retention",
        "low": "Minor NH journey improvement",
    },
    "user_satisfaction": {
        "critical": "User experience fundamentally broken — driving churn on both sides",
        "high": "Satisfaction gap causing measurable drop-off in retention",
        "medium": "Satisfaction issue affecting user NPS and engagement",
        "low": "Minor satisfaction improvement opportunity",
    },
    "marketplace_health": {
        "critical": "Marketplace economics broken — supply/demand imbalance threatens viability",
        "high": "Marketplace health gap affecting liquidity or coverage",
        "medium": "Marketplace metric that needs attention for healthy growth",
        "low": "Minor marketplace optimization",
    },
    "ops_efficiency": {
        "critical": "Operations overhead unsustainable at current scale",
        "high": "Ops efficiency gap that increases manual intervention burden",
        "medium": "Ops process that could be automated or streamlined",
        "low": "Minor ops efficiency improvement",
    },
    # Finance team impact templates
    "stripe_integration": {
        "critical": "Payment infrastructure broken — cannot collect revenue",
        "high": "Stripe integration gap that could cause missed payments or webhook failures",
        "medium": "Stripe integration issue that needs attention before scaling",
        "low": "Minor Stripe integration improvement",
    },
    "credit_regulation": {
        "critical": "Credit economy classified as money transmission — regulatory shutdown risk",
        "high": "Credit economy gap that could trigger FinCEN/PSA scrutiny",
        "medium": "Credit economy compliance issue to address before launch",
        "low": "Minor credit regulation improvement",
    },
    "compliance": {
        "critical": "Regulatory violation — GDPR/CCPA/PDPA non-compliance exposes legal liability",
        "high": "Compliance gap that could result in enforcement action",
        "medium": "Compliance issue to address for regulatory readiness",
        "low": "Minor compliance improvement opportunity",
    },
    "investor_readiness": {
        "critical": "Data room claims materially misrepresent codebase — fundraise risk",
        "high": "Investor-facing claims have significant gaps vs reality",
        "medium": "Investor readiness issue that could affect due diligence",
        "low": "Minor investor readiness improvement",
    },
    # GTM team impact templates
    "competitive_positioning": {
        "critical": "No competitive positioning — GTM execution has no strategic foundation",
        "high": "Significant competitive blind spots undermining positioning decisions",
        "medium": "Competitive coverage gap that could lead to missed threats",
        "low": "Minor competitive intelligence improvement",
    },
    "market_entry": {
        "critical": "No market entry strategy — geographic expansion is unplanned",
        "high": "Market entry gaps that could cause failed launches or regulatory issues",
        "medium": "Market entry planning gap to address before expansion",
        "low": "Minor market entry documentation improvement",
    },
    "pricing_strategy": {
        "critical": "Pricing model undefined — cannot monetize or communicate value",
        "high": "Pricing implementation gap between strategy docs and codebase",
        "medium": "Pricing optimization opportunity for better conversion",
        "low": "Minor pricing documentation improvement",
    },
    "brand_messaging": {
        "critical": "Brand messaging absent — users cannot understand the value proposition",
        "high": "Messaging inconsistency degrading user trust and conversion",
        "medium": "Brand messaging gap between strategy and frontend",
        "low": "Minor messaging alignment opportunity",
    },
    "channel_readiness": {
        "critical": "No acquisition channels ready — cannot drive user growth",
        "high": "Key acquisition channel has significant gaps",
        "medium": "Channel readiness issue to address before scaling",
        "low": "Minor channel optimization opportunity",
    },
    "partnership_pipeline": {
        "critical": "No partnership infrastructure — supply side recruitment blocked",
        "high": "Partnership pipeline gap limiting supply side growth",
        "medium": "Partnership readiness issue to address for network expansion",
        "low": "Minor partnership process improvement",
    },
}

_DEFAULT_IMPACT: dict[str, str] = {
    "critical": "Critical issue affecting platform reliability",
    "high": "Significant issue that needs prompt attention",
    "medium": "Moderate issue to address in normal workflow",
    "low": "Minor improvement opportunity",
}


def score_alignment(outcomes: list[str]) -> float:
    """Score 0.0-1.0 based on how many high-priority outcomes are served.

    Earlier items in OUTCOME_PRIORITY have higher weight.
    """
    if not outcomes:
        return 0.0
    total = 0.0
    for outcome in outcomes:
        if outcome in OUTCOME_PRIORITY:
            idx = OUTCOME_PRIORITY.index(outcome)
            # Weight: 1.0 for first, 0.75 for second, 0.5, 0.25
            total += 1.0 - (idx * 0.25)
    return min(1.0, total / len(OUTCOME_PRIORITY))


def get_business_impact(category: str, severity: str) -> str:
    """Generate a business impact statement from finding category + severity."""
    templates = _IMPACT_TEMPLATES.get(category, _DEFAULT_IMPACT)
    return templates.get(
        severity, _DEFAULT_IMPACT.get(severity, "Impact to be assessed")
    )


def get_aligned_outcomes(category: str) -> list[str]:
    """Return business outcomes aligned with a finding category."""
    return CATEGORY_OUTCOME_MAP.get(category, [COST_EFFICIENCY])
