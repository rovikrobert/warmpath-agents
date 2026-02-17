"""Data team configuration — paths, table registry, KPI targets, privacy thresholds."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS = Path(__file__).resolve()
DATA_TEAM_DIR = _THIS.parent.parent           # data_team/
PROJECT_ROOT = DATA_TEAM_DIR.parent            # warmpath/
REPORTS_DIR = DATA_TEAM_DIR / "reports"
INTEL_CACHE = DATA_TEAM_DIR / "shared" / "intel_cache.json"

APP_DIR = PROJECT_ROOT / "app"
MODELS_DIR = APP_DIR / "models"
SERVICES_DIR = APP_DIR / "services"
API_DIR = APP_DIR / "api"
TESTS_DIR = PROJECT_ROOT / "tests"

# ---------------------------------------------------------------------------
# Database table registry (from CLAUDE.md: 27 tables)
# ---------------------------------------------------------------------------

DATABASE_TABLES: dict[str, list[str]] = {
    "core": [
        "users",
        "contacts",
        "companies",
        "search_requests",
        "match_results",
        "warm_scores",
        "usage_logs",
        "work_history",
        "csv_uploads",
        "applications",
        "linkedin_connections",
        "enrichment_cache",
        "job_listings",
        "referral_templates",
        "notifications",
        "user_preferences",
    ],
    "marketplace": [
        "marketplace_listings",
        "intro_facilitations",
        "credit_transactions",
        "suppression_list",
        "consent_records",
        "data_requests",
        "archived_credit_transactions",
        "subscription_plans",
        "subscription_records",
        "stripe_events",
    ],
    "security": [
        "audit_logs",
    ],
}

ALL_TABLES: list[str] = [
    t for group in DATABASE_TABLES.values() for t in group
]

# ---------------------------------------------------------------------------
# KPI targets
# ---------------------------------------------------------------------------

KPI_TARGETS: dict[str, dict] = {
    "activation_rate": {"target": 0.40, "yellow": 0.25, "unit": "ratio"},
    "upload_to_search_rate": {"target": 0.60, "yellow": 0.40, "unit": "ratio"},
    "search_to_intro_rate": {"target": 0.15, "yellow": 0.08, "unit": "ratio"},
    "intro_approval_rate": {"target": 0.50, "yellow": 0.30, "unit": "ratio"},
    "marketplace_supply_coverage": {"target": 100, "yellow": 50, "unit": "companies"},
    "warm_score_accuracy": {"target": 0.80, "yellow": 0.60, "unit": "ratio"},
    "credit_velocity": {"target": 500, "yellow": 200, "unit": "credits/week"},
}

# ---------------------------------------------------------------------------
# Privacy thresholds (CoS-mandated)
# ---------------------------------------------------------------------------

MIN_SAMPLE_SIZE = 30
MIN_GROUP_SIZE_PRIVACY = 5
WARM_SCORE_RECALIBRATION_THRESHOLD = 500

# ---------------------------------------------------------------------------
# Agent names
# ---------------------------------------------------------------------------

DATA_AGENT_NAMES: list[str] = [
    "pipeline",
    "analyst",
    "model_engineer",
    "data_lead",
]
