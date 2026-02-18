"""Privacy-safe SQL templates for finance team agent analytics.

9 parameterized templates for credit economy, DSAR compliance, and revenue
analysis.  All templates enforce k-anonymity (HAVING COUNT(*) >= 5) on
GROUP BY queries, avoid PII columns in SELECT, and scope vault tables
appropriately.

NOTE: Unlike data_team/shared/sql_templates.py, these templates are NOT
validated against PrivacyGuard at import time.  Validation happens at query
execution time through the data_team QueryExecutor, avoiding circular
import issues.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CREDIT ECONOMY QUERIES
# ---------------------------------------------------------------------------

CREDIT_BALANCES = """
SELECT
    type AS transaction_type,
    COUNT(*) AS tx_count,
    SUM(amount) AS total_amount
FROM credit_transactions
WHERE created_at >= :start_date
GROUP BY type
HAVING COUNT(*) >= 5
ORDER BY total_amount DESC
"""

CREDIT_VELOCITY = """
SELECT
    AVG(days_to_first_spend) AS avg_days_to_first_spend,
    COUNT(*) AS user_count
FROM (
    SELECT
        ct_earn.user_id,
        EXTRACT(EPOCH FROM (
            MIN(ct_spend.created_at) - MIN(ct_earn.created_at)
        )) / 86400.0 AS days_to_first_spend
    FROM credit_transactions ct_earn
    JOIN credit_transactions ct_spend
        ON ct_spend.user_id = ct_earn.user_id
        AND ct_spend.amount < 0
    WHERE ct_earn.amount > 0
        AND ct_earn.created_at >= :start_date
    GROUP BY ct_earn.user_id
) sub
"""

CREDIT_DISTRIBUTION = """
SELECT
    balance_bucket,
    COUNT(*) AS user_count
FROM (
    SELECT
        user_id,
        CASE
            WHEN SUM(amount) <= 0 THEN '0'
            WHEN SUM(amount) BETWEEN 1 AND 50 THEN '1-50'
            WHEN SUM(amount) BETWEEN 51 AND 200 THEN '51-200'
            WHEN SUM(amount) BETWEEN 201 AND 500 THEN '201-500'
            ELSE '500+'
        END AS balance_bucket
    FROM credit_transactions
    WHERE expires_at IS NULL OR expires_at > NOW()
    GROUP BY user_id
) sub
GROUP BY balance_bucket
HAVING COUNT(*) >= 5
ORDER BY balance_bucket
"""

CREDIT_EXPIRY_RATE = """
SELECT
    COUNT(*) AS total_credits,
    SUM(CASE WHEN expires_at < NOW() AND amount > 0 THEN amount ELSE 0 END) AS expired_amount,
    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS total_earned
FROM credit_transactions
WHERE created_at >= :start_date
GROUP BY type
HAVING COUNT(*) >= 5
"""

EARN_SPEND_BY_TYPE = """
SELECT
    type AS transaction_type,
    DATE_TRUNC(:period, created_at) AS period_start,
    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS earned,
    SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) AS spent,
    COUNT(*) AS tx_count
FROM credit_transactions
WHERE created_at >= :start_date
    AND created_at < :end_date
GROUP BY type, DATE_TRUNC(:period, created_at)
HAVING COUNT(*) >= 5
ORDER BY period_start, transaction_type
"""

ZERO_BALANCE_USERS = """
SELECT
    COUNT(*) AS zero_balance_count
FROM (
    SELECT
        user_id,
        SUM(amount) AS balance
    FROM credit_transactions
    GROUP BY user_id
    HAVING SUM(amount) <= 0
) sub
"""

# ---------------------------------------------------------------------------
# COMPLIANCE / DSAR QUERIES
# ---------------------------------------------------------------------------

DSAR_PENDING = """
SELECT
    request_type,
    status,
    COUNT(*) AS request_count,
    MIN(deadline_at) AS earliest_deadline
FROM data_requests
WHERE status = 'pending'
    AND deadline_at <= NOW() + INTERVAL '7 days'
GROUP BY request_type, status
HAVING COUNT(*) >= 5
"""

DELETION_VERIFICATION = """
SELECT
    'contacts' AS table_name,
    COUNT(*) AS remaining_rows
FROM contacts
WHERE user_id = :user_id
UNION ALL
SELECT
    'warm_scores' AS table_name,
    COUNT(*) AS remaining_rows
FROM warm_scores
WHERE user_id = :user_id
UNION ALL
SELECT
    'match_results' AS table_name,
    COUNT(*) AS remaining_rows
FROM match_results
WHERE user_id = :user_id
UNION ALL
SELECT
    'applications' AS table_name,
    COUNT(*) AS remaining_rows
FROM applications
WHERE user_id = :user_id
UNION ALL
SELECT
    'marketplace_listings' AS table_name,
    COUNT(*) AS remaining_rows
FROM marketplace_listings
WHERE user_id = :user_id
UNION ALL
SELECT
    'csv_uploads' AS table_name,
    COUNT(*) AS remaining_rows
FROM csv_uploads
WHERE user_id = :user_id
"""

# ---------------------------------------------------------------------------
# REVENUE QUERIES
# ---------------------------------------------------------------------------

MONTHLY_REVENUE = """
SELECT
    DATE_TRUNC('month', created_at) AS revenue_month,
    COUNT(*) AS purchase_count,
    SUM(amount) AS total_credits_purchased
FROM credit_transactions
WHERE type = 'purchase'
    AND created_at >= :start_date
GROUP BY DATE_TRUNC('month', created_at)
HAVING COUNT(*) >= 5
ORDER BY revenue_month
"""

# ---------------------------------------------------------------------------
# Template registry
# ---------------------------------------------------------------------------

FINANCE_TEMPLATES: dict[str, str] = {
    "credit_balances": CREDIT_BALANCES,
    "credit_velocity": CREDIT_VELOCITY,
    "credit_distribution": CREDIT_DISTRIBUTION,
    "credit_expiry_rate": CREDIT_EXPIRY_RATE,
    "earn_spend_by_type": EARN_SPEND_BY_TYPE,
    "zero_balance_users": ZERO_BALANCE_USERS,
    "dsar_pending": DSAR_PENDING,
    "deletion_verification": DELETION_VERIFICATION,
    "monthly_revenue": MONTHLY_REVENUE,
}
