"""Chief of Staff configuration constants."""

from __future__ import annotations

COS_CONFIG: dict = {
    "daily_brief_time": "08:00",
    "timezone": "Asia/Singapore",
    "weekly_synthesis_day": "monday",
    "thresholds": {
        "critical_requires_escalation": True,
        "max_brief_length_words": 500,
        "skip_brief_if_all_clear": True,
    },
    "cost_budget": {
        "cos_daily_max_tokens": 3000,
        "total_daily_max_tokens": 25000,
        "data_team_daily_max_tokens": 15000,
        "product_team_daily_max_tokens": 15000,
        "ops_team_daily_max_tokens": 15000,
        "finance_team_daily_max_tokens": 15000,
        "gtm_team_daily_max_tokens": 15000,
        "daily_cost_cap_usd": 3.0,
        "per_team_cost_cap_usd": {
            "engineering": 1.50,
            "data": 0.30,
            "product": 0.30,
            "ops": 0.30,
            "finance": 0.30,
            "gtm": 0.30,
        },
        "alert_threshold_pct": 150,
    },
    "notion": {
        "daily_briefs_db_env": "NOTION_DAILY_BRIEFS_DB",
        "decision_log_db_env": "NOTION_DECISION_LOG_DB",
        "founder_briefs_db_env": "NOTION_FOUNDER_BRIEFS_DB",
    },
    "whatsapp": {
        "morning_brief_time": "08:00",
        "weekly_summary_day": "sunday",
        "weekly_summary_time": "20:00",
        "max_message_lines": 15,
    },
    "teams": {
        "engineering": {
            "active": True,
            "report_dir": "agents/reports",
        },
        "data": {
            "active": True,
            "report_dir": "data_team/reports",
        },
        "product": {
            "active": True,
            "report_dir": "product_team/reports",
        },
        "ops": {
            "active": True,
            "report_dir": "ops_team/reports",
        },
        "finance": {
            "active": True,
            "report_dir": "finance_team/reports",
        },
        "gtm": {
            "active": True,
            "report_dir": "gtm_team/reports",
        },
        "strategy": {"active": False},
    },
}

# Team registry — canonical agent names per team for report classification
TEAM_REGISTRY: dict[str, list[str]] = {
    "engineering": [
        "architect",
        "test_engineer",
        "perf_monitor",
        "deps_manager",
        "doc_keeper",
    ],
    "data": ["pipeline", "analyst", "model_engineer", "data_lead"],
    "product": [
        "user_researcher",
        "product_manager",
        "ux_lead",
        "design_lead",
        "product_lead",
    ],
    "ops": ["keevs", "treb", "naiv", "marsh", "ops_lead"],
    "finance": [
        "finance_manager",
        "credits_manager",
        "investor_relations",
        "legal_compliance",
        "finance_lead",
    ],
    "gtm": ["stratops", "monetization", "marketing", "partnerships", "gtm_lead"],
}

# Severity weights (reuse from shared config, but accessible here for scoring)
SEVERITY_WEIGHT: dict[str, float] = {
    "critical": 10.0,
    "high": 5.0,
    "medium": 2.0,
    "low": 1.0,
    "info": 0.0,
}

# Recommended scan order — engineering first (fixes code), then downstream teams.
# Later teams benefit from seeing resolved engineering issues.
SCAN_ORDER: list[str] = [
    "engineering",  # Code fixes, dependency updates, security patches
    "data",         # Schema/instrumentation audits (see engineering fixes)
    "product",      # UX/journey audits (see fixed pages)
    "ops",          # Marketplace health, coaching (see updated services)
    "finance",      # Credit economy, compliance (see credit service updates)
    "gtm",          # Marketing, competitive (see positioning changes)
]

# Decision principle hierarchy — first item wins in a tie
DECISION_PRINCIPLES = [
    "safety_privacy",  # User safety and privacy — never compromise
    "data_integrity",  # Protect the vault model
    "user_experience",  # Job seekers first, then network holders
    "speed_to_market",  # Ship fast, iterate
    "cost_efficiency",  # Optimize, don't overspend
    "technical_elegance",  # Nice to have, never a blocker
]
