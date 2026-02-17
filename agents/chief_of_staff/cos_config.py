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
        "alert_threshold_pct": 150,
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

# Severity weights (reuse from shared config, but accessible here for scoring)
SEVERITY_WEIGHT: dict[str, float] = {
    "critical": 10.0,
    "high": 5.0,
    "medium": 2.0,
    "low": 1.0,
    "info": 0.0,
}

# Decision principle hierarchy — first item wins in a tie
DECISION_PRINCIPLES = [
    "safety_privacy",      # Safety/Privacy always wins
    "help_job_seekers",    # Core mission — demand side
    "network_builders",    # Supply side
    "billion_dollar",      # Scale infrastructure
    "cost_efficiency",     # Optimize spend
]
