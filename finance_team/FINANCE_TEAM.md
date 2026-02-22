# WarmPath Finance Agent Team

## Mission

Audit WarmPath's financial infrastructure, credit economy integrity, billing readiness, regulatory compliance, and investor-readiness posture -- all by analyzing the **codebase**, not live financial systems.

## Financial Principles

Every scan enforces WarmPath's credit economy and compliance architecture:

1. **Credits are not currency** -- Non-transferable, 12-month expiry, no cash-out. Stays in "loyalty program" territory to avoid money transmitter regulations (FinCEN, Singapore Payment Services Act).
2. **Referral bonus flow** -- Currently employer referral bonuses flow employer-to-employee outside our system. Revenue-sharing may be explored post-traction.
3. **Revenue from demand side** -- Job seekers pay for marketplace access ($20-30/month). Network holders are currently free to use.
4. **Payment card isolation** -- All card data goes directly to Stripe. We never see, transmit, or store card numbers (outside PCI DSS scope).
5. **Webhook integrity** -- All Stripe webhooks verified against `STRIPE_WEBHOOK_SECRET`. Unsigned/replayed events rejected.
6. **Audit immutability** -- `audit_logs` table is append-only (no UPDATE/DELETE). Credit transactions are immutable records.
7. **Privacy-first billing** -- No PII in billing metadata. Credit transactions reference user_id, never contact PII.

## Team Structure

| Agent | Role | Key Output |
|-------|------|------------|
| **FinanceManager** | Stripe webhooks, billing endpoints, subscription model, cost tracking | Billing readiness score, webhook coverage |
| **CreditsManager** | Credit earn/spend, non-transferability, expiry, abuse detection | Credit economy health, regulatory risk flags |
| **InvestorRelations** | Test count, tech debt, schema health, feature completion, security | Investor data room readiness score |
| **LegalCompliance** | GDPR/PDPA/FinCEN, consent gates, suppression list, data deletion | Compliance posture, gap inventory |
| **FinanceLead** | Aggregation, cross-cutting patterns, team health | Daily/weekly briefs, team health score |

## Scan Domains

### Billing & Payments (FinanceManager)
- Stripe webhook event handler coverage (checkout.session.completed, invoice.paid, customer.subscription.*)
- Credit purchase endpoint validation (amount limits, idempotency, error handling)
- Subscription model schema (plan tiers, billing cycles, trial periods)
- Billing audit trail completeness (credit_transactions, usage_logs, audit_logs)
- Agent team cost tracking (scan_duration_seconds across all teams)

### Credit Economy (CreditsManager)
- Earn/spend completeness: CSV upload (100), intro facilitation (50), data freshness (10/quarter), cross-network search (5), intro request (20)
- Non-transferability enforcement (no transfer endpoints, no user-to-user credit flow)
- Money transmitter signal detection (no cash-out, no exchange rate, no float)
- 12-month expiry logic and archived_credit_transactions sweep
- Abuse patterns: bulk earn exploits, negative balance, duplicate earn events

### Investor Readiness (InvestorRelations)
- Test count accuracy (pytest collection vs. documented count in CLAUDE.md)
- Technical debt inventory (TODO/FIXME/HACK markers, deprecated code paths)
- Schema/migration health (Alembic single-head, model-migration parity)
- Feature completion audit (CLAUDE.md checklist vs. implemented endpoints)
- Security posture summary (encryption, auth, headers, audit logging)

### Legal & Compliance (LegalCompliance)
- GDPR: data export, deletion paths, consent tracking, DSAR table
- PDPA: business contact exception, anonymization measures
- CCPA: deletion via suppression sweep, no sale of personal data
- FinCEN: credit economy stays non-currency, no transmitter triggers
- Consent gates: suppression list, marketplace opt-in, per-contact visibility
- Privacy policy presence (warmpath_privacy_policy.docx, in-app rendering)

## KPI Framework

| KPI | Target | Category |
|-----|--------|----------|
| Stripe webhook coverage | 100% of events handled | Billing |
| Credit balance accuracy | Zero drift | Economy |
| Non-transferability violations | 0 | Regulatory |
| Test count match | Exact (CLAUDE.md = pytest) | Investor |
| Alembic head count | 1 | Investor |
| GDPR/PDPA gap count | 0 critical | Compliance |
| Suppression list enforcement | 100% at import | Compliance |
| Agent scan cost (all teams) | < $2/day | Operations |

## Shared Modules

Located in `finance_team/shared/`:

| Module | Purpose |
|--------|---------|
| `config.py` | Paths, agent names, KPI targets, thresholds, budget categories, credit economy params |
| `report.py` | `FinanceTeamReport`, `FinancialInsight`, `CreditEconomyFinding`, `ComplianceFinding`, `CostSnapshot` |
| `learning.py` | `FinanceLearningState` -- self-learning with fix effectiveness tracking, severity calibration, recurring pattern escalation (5+/10+ thresholds) |
| `intelligence.py` | `FinanceIntelligence` -- 7 intel categories with urgency/adoption tracking and per-category TTL |
| `ledger.py` | Credit economy constants, Stripe event catalog, regulatory framework definitions |

## How to Run

```bash
# Full scan (all agents)
python3 -m finance_team.orchestrator --all

# Single agent
python3 -m finance_team.orchestrator --agent finance_manager

# Brief from cached reports (no scanning)
python3 -m finance_team.orchestrator --daily-brief

# Weekly deep dive
python3 -m finance_team.orchestrator --weekly

# Self-learning report
python3 -m finance_team.orchestrator --learning-report

# External intelligence freshness
python3 -m finance_team.orchestrator --intel-report

# Research agenda generation
python3 -m finance_team.orchestrator --research-agenda

# Full compliance audit (all regulatory frameworks)
python3 -m finance_team.orchestrator --compliance-audit
```

## CoS Integration

The finance team is a first-class citizen in the Chief of Staff ecosystem:
- Reports are loaded by `cos_agent.py:_load_reports()` from `finance_team/reports/`
- Reports convert via `to_agent_report()` for CoS consumption
- Finding categories mapped to business outcomes in `business_outcomes.py`
- Cost tracked via `scan_duration_seconds` field on `FinanceTeamReport`
- Team reliability tracked by `cos_learning.py:update_team_reliability("finance", ...)`
- Cross-team requests surface in CoS founder briefs
- Finance team findings appear in `--cos-daily` alongside engineering and data findings

## Coordination Model

- **Engineering team** -- Finance identifies billing/payment code gaps, engineering implements fixes
- **Data team** -- Shared interest in credit economy metrics, funnel instrumentation, and usage_logs integrity
- **Product team** -- Finance validates subscription model aligns with pricing strategy and onboarding flows
- **CoS** -- Finance reports feed into founder briefs; compliance findings escalate through CoS
- **Founder** -- Weekly reviews provide financial health assessment, compliance posture, and investor readiness
