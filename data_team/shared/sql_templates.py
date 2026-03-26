"""Pre-approved parameterized SQL query templates for data team analytics.

Every template is validated by PrivacyGuard at module load time.
Templates use :param_name style placeholders for parameterized execution.
"""

from __future__ import annotations

from data_team.shared.privacy_guard import guard

# ---------------------------------------------------------------------------
# FUNNEL QUERIES
# ---------------------------------------------------------------------------

DAILY_SIGNUPS = """
SELECT
    DATE(created_at) AS signup_date,
    COUNT(*) AS signups
FROM users
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY DATE(created_at)
HAVING COUNT(*) >= 5
ORDER BY signup_date
"""

DAILY_UPLOADS = """
SELECT
    DATE(created_at) AS upload_date,
    COUNT(*) AS uploads,
    SUM(total_contacts) AS total_contacts
FROM csv_uploads
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY DATE(created_at)
HAVING COUNT(*) >= 5
ORDER BY upload_date
"""

ACTIVATION_FUNNEL = """
SELECT
    COUNT(*) AS total_users,
    COUNT(CASE WHEN csv_upload_count > 0 THEN 1 END) AS uploaded,
    COUNT(CASE WHEN search_count > 0 THEN 1 END) AS searched,
    COUNT(CASE WHEN intro_request_count > 0 THEN 1 END) AS requested_intro
FROM (
    SELECT
        u.id AS user_id,
        COUNT(DISTINCT cu.id) AS csv_upload_count,
        COUNT(DISTINCT sr.id) AS search_count,
        COUNT(DISTINCT inf.id) AS intro_request_count
    FROM users u
    LEFT JOIN csv_uploads cu ON cu.user_id = u.id
    LEFT JOIN search_requests sr ON sr.user_id = u.id
    LEFT JOIN intro_facilitations inf ON inf.requester_id = u.id
    WHERE u.created_at >= :start_date
        AND u.created_at < :end_date
    GROUP BY u.id
) sub
"""

ACTIVATION_FUNNEL_ADMIN = """
SELECT  -- ADMIN ONLY: no k-anonymity filter
    COUNT(*) AS total_users,
    COUNT(CASE WHEN csv_upload_count > 0 THEN 1 END) AS uploaded,
    COUNT(CASE WHEN search_count > 0 THEN 1 END) AS searched,
    COUNT(CASE WHEN intro_request_count > 0 THEN 1 END) AS requested_intro
FROM (
    SELECT
        u.id AS user_id,
        COUNT(DISTINCT cu.id) AS csv_upload_count,
        COUNT(DISTINCT sr.id) AS search_count,
        COUNT(DISTINCT inf.id) AS intro_request_count
    FROM users u
    LEFT JOIN csv_uploads cu ON cu.user_id = u.id
    LEFT JOIN search_requests sr ON sr.user_id = u.id
    LEFT JOIN intro_facilitations inf ON inf.requester_id = u.id
    WHERE u.created_at >= :start_date
        AND u.created_at < :end_date
    GROUP BY u.id
) sub
"""

TIME_TO_FIRST_VALUE = """
SELECT
    AVG(EXTRACT(EPOCH FROM (first_search - u.created_at)) / 3600) AS avg_hours_to_first_search
FROM users u
JOIN LATERAL (
    SELECT MIN(created_at) AS first_search
    FROM search_requests sr
    WHERE sr.user_id = u.id
) fs ON TRUE
WHERE u.created_at >= :start_date
    AND first_search IS NOT NULL
"""

# ---------------------------------------------------------------------------
# MARKETPLACE QUERIES
# ---------------------------------------------------------------------------

MARKETPLACE_HEALTH = """
SELECT
    COUNT(*) AS total_listings,
    COUNT(CASE WHEN is_active = TRUE THEN 1 END) AS active_listings,
    COUNT(DISTINCT company_id) AS companies_represented
FROM marketplace_listings
WHERE created_at >= :start_date
"""

SUPPLY_BY_COMPANY = """
SELECT
    company_id,
    COUNT(*) AS listing_count,
    AVG(warm_score_range_low) AS avg_warm_low,
    AVG(warm_score_range_high) AS avg_warm_high
FROM marketplace_listings
WHERE is_active = TRUE
GROUP BY company_id
HAVING COUNT(*) >= 5
ORDER BY listing_count DESC
"""

INTRO_APPROVAL_RATE = """
SELECT
    COUNT(*) AS total_requests,
    COUNT(CASE WHEN status = 'approved' THEN 1 END) AS approved,
    COUNT(CASE WHEN status = 'declined' THEN 1 END) AS declined,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) AS pending
FROM intro_facilitations
WHERE created_at >= :start_date
    AND created_at < :end_date
"""

CREDIT_FLOW = """
SELECT
    transaction_type,
    COUNT(*) AS tx_count,
    SUM(amount) AS total_amount
FROM credit_transactions
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY transaction_type
HAVING COUNT(*) >= 5
ORDER BY total_amount DESC
"""

# ---------------------------------------------------------------------------
# OUTCOME QUERIES
# ---------------------------------------------------------------------------

APPLICATION_FUNNEL = """
SELECT
    status,
    COUNT(*) AS count
FROM applications
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY status
HAVING COUNT(*) >= 5
ORDER BY count DESC
"""

WARM_SCORE_VS_OUTCOME = """
SELECT
    CASE
        WHEN ws.total_score >= 80 THEN 'high'
        WHEN ws.total_score >= 50 THEN 'medium'
        ELSE 'low'
    END AS score_band,
    COUNT(*) AS total_intros,
    COUNT(CASE WHEN inf.status = 'approved' THEN 1 END) AS approved
FROM warm_scores ws
JOIN intro_facilitations inf ON inf.contact_id = ws.contact_id
    AND inf.requester_id = ws.user_id
WHERE ws.user_id = :user_id
GROUP BY score_band
HAVING COUNT(*) >= 5
"""

CULTURAL_CONTEXT_EFFECTIVENESS = """
SELECT
    mr.cultural_context->>'approach_style' AS approach_style,
    COUNT(*) AS total_matches,
    AVG(CASE WHEN mr.user_feedback = 'positive' THEN 1.0 ELSE 0.0 END) AS positive_rate
FROM match_results mr
WHERE mr.user_id = :user_id
    AND mr.cultural_context IS NOT NULL
    AND mr.user_feedback IS NOT NULL
GROUP BY mr.cultural_context->>'approach_style'
HAVING COUNT(*) >= 5
"""

# ---------------------------------------------------------------------------
# ENGAGEMENT QUERIES
# ---------------------------------------------------------------------------

WEEKLY_ACTIVE_USERS = """
SELECT
    DATE_TRUNC('week', created_at) AS week,
    COUNT(DISTINCT user_id) AS active_users
FROM usage_logs
WHERE created_at >= :start_date
GROUP BY DATE_TRUNC('week', created_at)
HAVING COUNT(DISTINCT user_id) >= 5
ORDER BY week
"""

FEATURE_USAGE = """
SELECT
    action,
    COUNT(*) AS usage_count,
    COUNT(DISTINCT user_id) AS unique_users
FROM usage_logs
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY action
HAVING COUNT(*) >= 5
ORDER BY usage_count DESC
"""

# ---------------------------------------------------------------------------
# COHORT QUERIES
# ---------------------------------------------------------------------------

SIGNUP_COHORT_RETENTION = """
SELECT
    DATE_TRUNC('week', u.created_at) AS cohort_week,
    COUNT(DISTINCT u.id) AS cohort_size,
    COUNT(DISTINCT CASE
        WHEN ul.created_at >= u.created_at + INTERVAL '7 days'
            AND ul.created_at < u.created_at + INTERVAL '14 days'
        THEN u.id
    END) AS retained_week_2
FROM users u
LEFT JOIN usage_logs ul ON ul.user_id = u.id
WHERE u.created_at >= :start_date
GROUP BY DATE_TRUNC('week', u.created_at)
HAVING COUNT(DISTINCT u.id) >= 5
ORDER BY cohort_week
"""

SIGNUP_COHORT_ACTIVATION = """
SELECT
    DATE_TRUNC('week', u.created_at) AS cohort_week,
    COUNT(DISTINCT u.id) AS cohort_size,
    COUNT(DISTINCT CASE WHEN cu.id IS NOT NULL THEN u.id END) AS activated
FROM users u
LEFT JOIN csv_uploads cu ON cu.user_id = u.id
WHERE u.created_at >= :start_date
GROUP BY DATE_TRUNC('week', u.created_at)
HAVING COUNT(DISTINCT u.id) >= 5
ORDER BY cohort_week
"""

# ---------------------------------------------------------------------------
# Template registry (for validation + enumeration)
# ---------------------------------------------------------------------------

ALL_TEMPLATES: dict[str, str] = {
    "daily_signups": DAILY_SIGNUPS,
    "daily_uploads": DAILY_UPLOADS,
    "activation_funnel": ACTIVATION_FUNNEL,
    "activation_funnel_admin": ACTIVATION_FUNNEL_ADMIN,
    "time_to_first_value": TIME_TO_FIRST_VALUE,
    "marketplace_health": MARKETPLACE_HEALTH,
    "supply_by_company": SUPPLY_BY_COMPANY,
    "intro_approval_rate": INTRO_APPROVAL_RATE,
    "credit_flow": CREDIT_FLOW,
    "application_funnel": APPLICATION_FUNNEL,
    "warm_score_vs_outcome": WARM_SCORE_VS_OUTCOME,
    "cultural_context_effectiveness": CULTURAL_CONTEXT_EFFECTIVENESS,
    "weekly_active_users": WEEKLY_ACTIVE_USERS,
    "feature_usage": FEATURE_USAGE,
    "signup_cohort_retention": SIGNUP_COHORT_RETENTION,
    "signup_cohort_activation": SIGNUP_COHORT_ACTIVATION,
}


def validate_all_templates() -> list[str]:
    """Validate every template against PrivacyGuard. Returns list of errors."""
    errors: list[str] = []
    for name, sql in ALL_TEMPLATES.items():
        try:
            if "group by" in sql.lower():
                guard.validate_aggregation(sql, context=f"template:{name}")
            else:
                guard.validate_query(sql, context=f"template:{name}")
        except Exception as e:
            errors.append(f"{name}: {e}")
    return errors


# Validate at import time — hard fail if any template violates privacy
_errors = validate_all_templates()
if _errors:
    raise RuntimeError("SQL template privacy violations:\n" + "\n".join(_errors))
