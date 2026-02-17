"""Operations team configuration — paths, agent names, ops personas, KPI targets, thresholds."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
OPS_TEAM_DIR = _THIS.parent.parent            # ops_team/
PROJECT_ROOT = OPS_TEAM_DIR.parent             # warmpath/
REPORTS_DIR = OPS_TEAM_DIR / "reports"
INTEL_CACHE = OPS_TEAM_DIR / "shared" / "intel_cache.json"

FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_SRC = FRONTEND_DIR / "src"
PAGES_DIR = FRONTEND_SRC / "pages"
COMPONENTS_DIR = FRONTEND_SRC / "components"
APP_DIR = PROJECT_ROOT / "app"
API_DIR = APP_DIR / "api"
SERVICES_DIR = APP_DIR / "services"
MODELS_DIR = APP_DIR / "models"
MIDDLEWARE_DIR = APP_DIR / "middleware"
TESTS_DIR = PROJECT_ROOT / "tests"

# ---------------------------------------------------------------------------
# Agent names
# ---------------------------------------------------------------------------

OPS_AGENT_NAMES: list[str] = [
    "keevs",
    "treb",
    "naiv",
    "marsh",
    "ops_lead",
]

# ---------------------------------------------------------------------------
# Ops personas (user-facing layer)
# ---------------------------------------------------------------------------

OPS_PERSONAS: dict[str, dict] = {
    "job_seeker": {
        "label": "Job Seeker",
        "description": "Mid-career tech professional (3-10 yr exp) actively hunting",
        "motivation": "Get employee referrals instead of applying cold",
        "agent": "keevs",
        "tier": "demand",
    },
    "network_holder": {
        "label": "Network Holder",
        "description": "Employee at desirable company with LinkedIn connections to share",
        "motivation": "Capture referral bonuses, build reputation, bank credits",
        "agent": "treb",
        "tier": "supply",
    },
}

# ---------------------------------------------------------------------------
# KPI targets
# ---------------------------------------------------------------------------

KPI_TARGETS: dict[str, dict] = {
    "coaching_response_quality": {
        "target": 0.85,
        "unit": "ratio",
        "description": "Keevs responses that include actionable next steps",
    },
    "nh_journey_completion": {
        "target": 0.70,
        "unit": "ratio",
        "description": "Network holders completing upload > opt-in > first intro",
    },
    "intro_approval_rate": {
        "target": 0.60,
        "unit": "ratio",
        "description": "Intro requests approved by network holders",
    },
    "satisfaction_score": {
        "target": 0.80,
        "unit": "ratio",
        "description": "Overall user satisfaction (from journey signals)",
    },
    "marketplace_coverage": {
        "target": 0.50,
        "unit": "ratio",
        "description": "Percentage of target companies with supply-side presence",
    },
}

# ---------------------------------------------------------------------------
# Thresholds for agent checks
# ---------------------------------------------------------------------------

COACH_KEYWORD_COVERAGE_TARGET = 0.80   # % of job seeker scenarios with mock handlers
COACH_JOURNEY_STEPS = [
    "signup", "upload", "search", "message", "track", "interview",
]
NH_JOURNEY_STEPS = [
    "signup", "upload_csv", "opt_in", "review_intros", "earn",
]
MARKETPLACE_ACTIONS = [
    "cross_network_search", "request_intro", "approve_intro", "decline_intro",
]

# ---------------------------------------------------------------------------
# Self-learning thresholds
# ---------------------------------------------------------------------------

RECURRING_PATTERN_THRESHOLD = 5       # auto-escalate at 5+ occurrences
SYSTEMIC_PATTERN_THRESHOLD = 10       # flag as systemic at 10+
ATTENTION_WEIGHT_DECAY = 0.05         # per-day decay for quiet files
FIX_EFFECTIVENESS_WINDOW_DAYS = 30    # look-back window for fix effectiveness
INTEL_CACHE_TTL_HOURS = 24            # default intelligence cache TTL

# Health score weights per agent (total = 100)
HEALTH_WEIGHTS: dict[str, int] = {
    "keevs": 30,
    "treb": 25,
    "naiv": 20,
    "marsh": 15,
    "ops_lead": 10,
}
