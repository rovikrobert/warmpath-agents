"""Product team configuration — paths, agent names, persona definitions, RICE weights, learning constants."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
PRODUCT_TEAM_DIR = _THIS.parent.parent  # product_team/
PROJECT_ROOT = PRODUCT_TEAM_DIR.parent  # warmpath/
REPORTS_DIR = PRODUCT_TEAM_DIR / "reports"
INTEL_CACHE = PRODUCT_TEAM_DIR / "shared" / "intel_cache.json"

FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_SRC = FRONTEND_DIR / "src"
PAGES_DIR = FRONTEND_SRC / "pages"
COMPONENTS_DIR = FRONTEND_SRC / "components"
APP_DIR = PROJECT_ROOT / "app"
API_DIR = APP_DIR / "api"
TESTS_DIR = PROJECT_ROOT / "tests"

# ---------------------------------------------------------------------------
# Agent names
# ---------------------------------------------------------------------------

PRODUCT_AGENT_NAMES: list[str] = [
    "user_researcher",
    "product_manager",
    "ux_lead",
    "design_lead",
    "product_lead",
]

# ---------------------------------------------------------------------------
# Personas (from CLAUDE.md business model)
# ---------------------------------------------------------------------------

PERSONAS: dict[str, dict] = {
    "job_seeker": {
        "label": "Job Seeker",
        "description": "Mid-career tech professional (3-10 yr exp) actively hunting",
        "motivation": "Get employee referrals instead of applying cold",
        "key_pages": [
            "Dashboard",
            "FindReferrals",
            "ReferralResults",
            "ApplicationsPage",
            "NewSearch",
            "SearchResults",
        ],
        "tier": "demand",
    },
    "network_holder": {
        "label": "Network Holder",
        "description": "Employee at desirable company with LinkedIn connections to share",
        "motivation": "Capture referral bonuses, build reputation, bank credits",
        "key_pages": [
            "Dashboard",
            "ContactsPage",
            "SharingSettings",
            "MarketplaceDashboard",
            "CreditsPage",
        ],
        "tier": "supply",
    },
}

# ---------------------------------------------------------------------------
# RICE scoring weights (for feature prioritization)
# ---------------------------------------------------------------------------

RICE_WEIGHTS: dict[str, float] = {
    "reach": 0.3,
    "impact": 0.3,
    "confidence": 0.2,
    "effort_inverse": 0.2,  # Lower effort → higher score
}

# ---------------------------------------------------------------------------
# UX heuristic weights
# ---------------------------------------------------------------------------

UX_HEURISTIC_WEIGHTS: dict[str, float] = {
    "accessibility": 0.25,
    "loading_states": 0.15,
    "error_states": 0.15,
    "empty_states": 0.10,
    "form_validation": 0.10,
    "responsive_design": 0.10,
    "privacy_indicators": 0.10,
    "flow_efficiency": 0.05,
}

# ---------------------------------------------------------------------------
# Design system targets
# ---------------------------------------------------------------------------

DESIGN_SYSTEM_TARGETS: dict[str, float] = {
    "tailwind_usage_pct": 0.90,  # 90%+ styling via Tailwind
    "max_unique_colors": 12,
    "max_unique_text_sizes": 8,
    "dark_mode_coverage_pct": 0.0,  # Not required yet, but tracked
}

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
    "user_researcher": 20,
    "product_manager": 25,
    "ux_lead": 25,
    "design_lead": 15,
    "product_lead": 15,
}
