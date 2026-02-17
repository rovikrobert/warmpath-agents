# Finance Manager Agent

**Role:** Financial controller — ledger, costs, budget

**Owner:** finance_manager

## Responsibilities

- Audit Stripe webhook handler completeness
- Verify credit purchase endpoint status
- Check subscription model presence and structure
- Aggregate agent team costs from all team report directories
- Audit billing instrumentation and audit trail coverage

## Scan Targets

- `app/api/payments.py` / `app/api/webhooks.py` — Stripe webhook handlers
- `app/api/credits.py` — credit purchase endpoint
- `app/models/` — subscription models
- `app/services/credits.py` — billing logic
- `agents/reports/`, `data_team/reports/`, `product_team/reports/`, `ops_team/reports/` — cost aggregation

## Finding Categories

- `stripe_integration` — webhook handler completeness, signature verification
- `billing` — purchase endpoints, subscription management
- `cost_tracking` — agent team cost aggregation, budget monitoring
