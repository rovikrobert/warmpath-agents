"""Finance team configuration — paths, agent names, KPI targets, thresholds."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
FINANCE_TEAM_DIR = _THIS.parent.parent  # finance_team/
PROJECT_ROOT = FINANCE_TEAM_DIR.parent  # warmpath/
REPORTS_DIR = FINANCE_TEAM_DIR / "reports"
INTEL_CACHE = FINANCE_TEAM_DIR / "shared" / "intel_cache.json"

APP_DIR = PROJECT_ROOT / "app"
API_DIR = APP_DIR / "api"
SERVICES_DIR = APP_DIR / "services"
MODELS_DIR = APP_DIR / "models"
MIDDLEWARE_DIR = APP_DIR / "middleware"
TESTS_DIR = PROJECT_ROOT / "tests"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_SRC = FRONTEND_DIR / "src"

# ---------------------------------------------------------------------------
# Agent names
# ---------------------------------------------------------------------------

FINANCE_AGENT_NAMES: list[str] = [
    "finance_manager",
    "credits_manager",
    "investor_relations",
    "legal_compliance",
    "finance_lead",
]

# ---------------------------------------------------------------------------
# KPI targets
# ---------------------------------------------------------------------------

KPI_TARGETS: dict[str, dict] = {
    "burn_rate_accuracy": {
        "target": 0.10,
        "unit": "variance",
        "description": "Budget-vs-actual variance kept within 10%",
    },
    "cost_per_user": {
        "target": 2.0,
        "unit": "usd",
        "description": "Fully-loaded cost per active user per month",
    },
    "agent_cost_daily": {
        "target": 3.0,
        "unit": "usd",
        "description": "Total daily spend across all agent operations",
    },
    "ai_cost_per_action": {
        "target": 0.05,
        "unit": "usd",
        "description": "Average AI token cost per user-facing action",
    },
    "arpu": {
        "target": 20.0,
        "unit": "usd",
        "description": "Average revenue per paying user per month",
    },
    "cash_runway_months": {
        "target": 6,
        "unit": "months",
        "description": "Months of runway remaining at current burn rate",
    },
    "earn_spend_ratio": {
        "target": 1.0,
        "unit": "ratio",
        "description": "Credit earn-to-spend ratio (healthy range 0.8-1.2)",
    },
    "credit_velocity_days": {
        "target": 30,
        "unit": "days",
        "description": "Average days from credit earn to spend",
    },
    "zero_balance_rate": {
        "target": 0.30,
        "unit": "ratio",
        "description": "Fraction of active users with zero credit balance",
    },
    "credit_gini": {
        "target": 0.6,
        "unit": "coefficient",
        "description": "Gini coefficient of credit distribution (lower = more equal)",
    },
    "expiry_rate": {
        "target": 0.15,
        "unit": "ratio",
        "description": "Fraction of earned credits that expire unused",
    },
    "abuse_false_positive_rate": {
        "target": 0.05,
        "unit": "ratio",
        "description": "False positive rate for credit abuse detection",
    },
    "fundraise_readiness": {
        "target": 7,
        "unit": "score",
        "description": "Investor readiness score (1-10 scale)",
    },
    "model_accuracy": {
        "target": 0.15,
        "unit": "variance",
        "description": "Financial model forecast accuracy (max 15% deviation)",
    },
    "compliance_gap_critical": {
        "target": 0,
        "unit": "count",
        "description": "Number of critical compliance gaps (must be zero)",
    },
    "dsar_response_days": {
        "target": 30,
        "unit": "days",
        "description": "Max days to respond to data subject access requests",
    },
}

# ---------------------------------------------------------------------------
# Self-learning thresholds
# ---------------------------------------------------------------------------

RECURRING_PATTERN_THRESHOLD = 5  # auto-escalate at 5+ occurrences
SYSTEMIC_PATTERN_THRESHOLD = 10  # flag as systemic at 10+
ATTENTION_WEIGHT_DECAY = 0.05  # per-day decay for quiet files
FIX_EFFECTIVENESS_WINDOW_DAYS = 30  # look-back window for fix effectiveness
INTEL_CACHE_TTL_HOURS = 24  # default intelligence cache TTL

# ---------------------------------------------------------------------------
# Health score weights per agent (total = 100)
# ---------------------------------------------------------------------------

HEALTH_WEIGHTS: dict[str, int] = {
    "finance_manager": 25,
    "credits_manager": 25,
    "investor_relations": 20,
    "legal_compliance": 20,
    "finance_lead": 10,
}

# ---------------------------------------------------------------------------
# Budget categories
# ---------------------------------------------------------------------------

BUDGET_CATEGORIES: list[str] = [
    "infrastructure",
    "ai_tokens",
    "agent_operations",
    "third_party_apis",
    "saas_tools",
    "legal_compliance",
    "marketing",
]

# ---------------------------------------------------------------------------
# Credit economy parameters
# ---------------------------------------------------------------------------

CREDIT_ECONOMY_PARAMS: dict[str, int] = {
    "upload_csv_bonus": 100,  # credits earned per CSV upload
    "facilitation_bonus": 50,  # credits earned per successful intro facilitation
    "freshness_bonus": 10,  # credits earned per quarter for keeping data fresh
    "search_cost": 5,  # credits spent per cross-network search
    "intro_cost": 20,  # credits spent per intro request
    "purchase_rate": 5,  # credits per dollar purchased
    "expiry_months": 12,  # months before unused credits expire
}

# ---------------------------------------------------------------------------
# Expected Stripe events (for webhook handler verification)
# ---------------------------------------------------------------------------

EXPECTED_STRIPE_EVENTS: list[str] = [
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
]

# ---------------------------------------------------------------------------
# Expected credit actions (for economy completeness verification)
# ---------------------------------------------------------------------------

EXPECTED_CREDIT_EARN_ACTIONS: list[str] = [
    "csv_upload",
    "welcome_bonus",
    "intro_facilitation",
    "data_freshness",
    "purchase",
    "enrichment_milestone",
    "referral_bonus",
    "feed_engagement",
]

EXPECTED_CREDIT_SPEND_ACTIONS: list[str] = [
    "marketplace_search",
    "intro_request",
]

# ---------------------------------------------------------------------------
# Financial tables (for schema verification)
# ---------------------------------------------------------------------------

FINANCIAL_TABLES: list[str] = [
    "credit_transactions",
    "usage_logs",
    "users",
]

# ---------------------------------------------------------------------------
# Privacy deletion paths (for legal compliance verification)
# ---------------------------------------------------------------------------

PRIVACY_DELETION_PATHS: list[str] = [
    "delete-account",
    "suppression",
    "data-request",
    "data_export",
]

# ---------------------------------------------------------------------------
# Monthly fixed costs (updated manually)
# ---------------------------------------------------------------------------

MONTHLY_FIXED_COSTS: dict[str, float] = {
    "infrastructure": 20.0,  # Railway Starter plan
    "domain": 1.0,  # Domain registration amortized
    "email": 0.0,  # Resend free tier
    "monitoring": 0.0,  # Railway built-in
}

CASH_ON_HAND: float = 0.0  # Update with actual amount when known
