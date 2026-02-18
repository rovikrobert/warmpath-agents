"""Credit economy constants and financial reference data.

This module defines the credit economy rules, Stripe events, financial tables,
and money transmitter risk signals that finance agents validate code against.
These are constants, not a live ledger.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Credit economy rules (from CLAUDE.md)
# ---------------------------------------------------------------------------

CREDIT_EARN_RULES: dict[str, int] = {
    "csv_upload": 100,
    "intro_facilitation": 50,
    "data_freshness": 10,  # per quarter
    "welcome_bonus": 0,  # optional, defined per campaign
    "purchase": -1,  # variable ($1 = 5 credits)
}

CREDIT_SPEND_RULES: dict[str, int] = {
    "cross_network_search": 5,
    "marketplace_search": 5,
    "request_intro": 20,
    "intro_request": 20,  # alias
}

CREDIT_EXPIRY_MONTHS = 12
CREDIT_PURCHASE_RATE = 5  # credits per dollar
CREDIT_NON_TRANSFERABLE = True  # critical — money transmitter boundary

# ---------------------------------------------------------------------------
# Stripe webhook events
# ---------------------------------------------------------------------------

STRIPE_WEBHOOK_EVENTS: list[str] = [
    "checkout.session.completed",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
]

STRIPE_CRITICAL_EVENTS: list[str] = [
    "checkout.session.completed",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
]

# ---------------------------------------------------------------------------
# Subscription tiers (from business model)
# ---------------------------------------------------------------------------

SUBSCRIPTION_TIERS: dict[str, dict] = {
    "free": {
        "price_monthly": 0,
        "marketplace_access": False,
        "description": "Search own uploaded contacts only",
    },
    "pro": {
        "price_monthly": 20,
        "marketplace_access": True,
        "description": "Full marketplace search access",
    },
    "premium": {
        "price_monthly": 30,
        "marketplace_access": True,
        "description": "Full marketplace access + priority support",
    },
}

# ---------------------------------------------------------------------------
# Financial tables (for schema validation)
# ---------------------------------------------------------------------------

FINANCIAL_TABLES: list[str] = [
    "credit_transactions",
    "usage_logs",
    "audit_logs",
]

FINANCIAL_MODEL_FILES: list[str] = [
    "app/models/credits.py",
    "app/models/usage.py",
    "app/models/audit.py",
]

# ---------------------------------------------------------------------------
# Money transmitter risk signals
# ---------------------------------------------------------------------------

MONEY_TRANSMITTER_RISK_SIGNALS: list[str] = [
    "transfer_credits",  # credits must be non-transferable
    "cash_out",  # no cash-out allowed
    "exchange_rate",  # no exchange rates
    "convert_to_cash",  # no cash conversion
    "withdraw",  # no withdrawals
    "peer_to_peer",  # no P2P transfers
    "money_transmit",  # explicit money transmission
]

SAFE_CREDIT_PATTERNS: list[str] = [
    "non_transferable",
    "loyalty_program",
    "expires_at",
    "expiry",
    "functional_accounting",
]

# ---------------------------------------------------------------------------
# Regulatory frameworks
# ---------------------------------------------------------------------------

REGULATORY_FRAMEWORKS: dict[str, dict] = {
    "GDPR": {
        "region": "EU",
        "deletion_required": True,
        "consent_required": True,
        "data_portability": True,
    },
    "CCPA": {
        "region": "California, USA",
        "deletion_required": True,
        "consent_required": False,
        "data_portability": True,
    },
    "PDPA": {
        "region": "Singapore",
        "deletion_required": True,
        "consent_required": True,
        "data_portability": False,
    },
    "FinCEN": {
        "region": "USA",
        "applies_to": "money_transmitters",
        "risk": "Credits classified as virtual currency",
    },
    "PSA": {
        "region": "Singapore",
        "applies_to": "payment_services",
        "risk": "Credits classified as e-money",
    },
}
