"""GTM team configuration — paths, agent names, personas, KPI targets, thresholds."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
GTM_TEAM_DIR = _THIS.parent.parent  # gtm_team/
PROJECT_ROOT = GTM_TEAM_DIR.parent  # warmpath/
REPORTS_DIR = GTM_TEAM_DIR / "reports"
INTEL_CACHE = GTM_TEAM_DIR / "shared" / "intel_cache.json"

FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_SRC = FRONTEND_DIR / "src"
PAGES_DIR = FRONTEND_SRC / "pages"
COMPONENTS_DIR = FRONTEND_SRC / "components"
APP_DIR = PROJECT_ROOT / "app"
API_DIR = APP_DIR / "api"
SERVICES_DIR = APP_DIR / "services"
MODELS_DIR = APP_DIR / "models"

# Strategy docs (source of truth for GTM team)
STRATEGY_DOCS_DIR = PROJECT_ROOT

# ---------------------------------------------------------------------------
# Agent names
# ---------------------------------------------------------------------------

GTM_AGENT_NAMES: list[str] = [
    "stratops",
    "monetization",
    "marketing",
    "partnerships",
    "gtm_lead",
]

# ---------------------------------------------------------------------------
# GTM personas
# ---------------------------------------------------------------------------

GTM_PERSONAS: dict[str, dict] = {
    "job_seeker": {
        "label": "Job Seeker",
        "description": "Mid-career tech professional (3-10 yr exp) actively hunting",
        "motivation": "Get employee referrals instead of applying cold",
        "tier": "demand",
        "price_sensitivity": "high (especially if unemployed)",
    },
    "network_holder": {
        "label": "Network Holder",
        "description": "Employee at desirable company with LinkedIn connections",
        "motivation": "Capture referral bonuses, build reputation, bank credits",
        "tier": "supply",
        "price_sensitivity": "free tier only",
    },
    "bootcamp_student": {
        "label": "Bootcamp Graduate",
        "description": "Career changer from coding bootcamp, limited network",
        "motivation": "Access networks at target companies they have zero connections to",
        "tier": "demand",
        "price_sensitivity": "medium (investing in career transition)",
    },
    "career_coach": {
        "label": "Career Coach",
        "description": "Professional coach managing multiple job-seeking clients",
        "motivation": "White-label referral tools for clients",
        "tier": "demand",
        "price_sensitivity": "low (business expense)",
    },
}

# ---------------------------------------------------------------------------
# KPI targets (pre-launch readiness)
# ---------------------------------------------------------------------------

KPI_TARGETS: dict[str, dict] = {
    "gtm_readiness": {
        "target": 1.0,
        "unit": "ratio",
        "description": "Composite: positioning + pricing + channels + partnerships",
    },
    "competitive_freshness": {
        "target": 7,
        "unit": "days",
        "description": "Days since last competitive scan",
    },
    "pricing_benchmarks": {
        "target": 10,
        "unit": "count",
        "description": "Number of comparable benchmarks analysed",
    },
    "content_pipeline_depth": {
        "target": 20,
        "unit": "count",
        "description": "SEO articles drafted and ready to publish",
    },
    "landing_page_readiness": {
        "target": 6,
        "unit": "count",
        "description": "Homepage + 5 company-specific pages ready",
    },
    "partnership_pipeline": {
        "target": 15,
        "unit": "count",
        "description": "Active partnership conversations",
    },
    "supply_side_targets": {
        "target": 50,
        "unit": "count",
        "description": "Identified network holder recruitment targets",
    },
}

# ---------------------------------------------------------------------------
# Strategy document filenames (checked in order, missing ones skipped)
# ---------------------------------------------------------------------------

STRATEGY_DOC_NAMES: list[str] = [
    "CLAUDE.md",
    "ARCHITECTURE.md",
    "README.md",
    "PRODUCT_STRATEGY_RECRUITMENT.md",
    "MARKET_ANALYSIS_RECRUITMENT.md",
    "COMPETITIVE_STRATEGY.md",
    "ROADMAP.md",
]

# ---------------------------------------------------------------------------
# Competitors tracked by StratOps
# ---------------------------------------------------------------------------

TRACKED_COMPETITORS: list[str] = [
    "The Swarm",
    "LinkedIn",
    "Handshake",
    "Blind",
    "Refer.me",
    "Teamable",
    "Drafted",
    "Lunchclub",
]

# ---------------------------------------------------------------------------
# Self-learning thresholds
# ---------------------------------------------------------------------------

RECURRING_PATTERN_THRESHOLD = 5  # auto-escalate at 5+ occurrences
SYSTEMIC_PATTERN_THRESHOLD = 10  # flag as systemic at 10+
ATTENTION_WEIGHT_DECAY = 0.05  # per-day decay for quiet files
FIX_EFFECTIVENESS_WINDOW_DAYS = 30  # look-back window for fix effectiveness
INTEL_CACHE_TTL_HOURS = 24  # default intelligence cache TTL

# Health score weights per agent (total = 100)
HEALTH_WEIGHTS: dict[str, int] = {
    "stratops": 25,
    "monetization": 20,
    "marketing": 25,
    "partnerships": 20,
    "gtm_lead": 10,
}
