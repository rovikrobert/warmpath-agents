# WarmPath Data Science Agent Team

## Mission

Audit WarmPath's data infrastructure readiness, prepare query templates, identify instrumentation gaps, and design KPI frameworks — all by analyzing the **codebase**, not a live database.

## Privacy Principles (CoS-Mandated)

Every query template is validated by `privacy_guard.py` at import time. Violations are hard failures.

1. **Vault isolation** — No cross-vault JOINs without consent gate
2. **PII encryption** — 13 PII columns registered and blocked from SELECT clauses
3. **Suppression list** — Must query by SHA-256 hash, never plaintext
4. **Anonymization** — Marketplace data only (no names/emails cross vault boundary)
5. **Consent tracking** — consent_records table is immutable (no UPDATE/DELETE)
6. **Data retention** — 12-month usage_logs, 24-month credit archive awareness
7. **DSAR compliance** — data_requests table awareness
8. **PII leak prevention** — validate_no_pii_in_output() on all result columns
9. **Audit immutability** — audit_logs and consent_records are append-only
10. **k-anonymity** — GROUP BY must include HAVING COUNT(*) >= 5

## Team Structure

| Agent | Role | Key Output |
|-------|------|------------|
| **DataLead** | Strategy, KPIs, coordination | Daily/weekly/monthly briefs |
| **Pipeline** | Schema audit, data quality | Table registry, index gaps |
| **Analyst** | Funnel mapping, engagement | Instrumentation coverage |
| **ModelEngineer** | Warm score, cultural context | Calibration readiness |

## Data Strategy (3 Phases)

### Phase 1: Infrastructure Audit (Current)
- Scan codebase for schema completeness, instrumentation gaps
- Build pre-approved SQL query templates with privacy validation
- Assess warm score algorithm for calibration readiness
- Map full user funnel and identify tracking gaps

### Phase 2: Live Analytics (Post-Launch)
- Connect to production DB (read replica)
- Stand up KPI dashboards using validated query templates
- Implement cohort analysis and retention tracking
- Build A/B testing framework for warm score calibration

### Phase 3: ML Pipeline (Scale)
- Automated warm score recalibration based on outcome data
- Anomaly detection for marketplace health
- Predictive models for churn and activation

## KPI Framework

| KPI | Target | Category |
|-----|--------|----------|
| Activation rate | 40% | Funnel |
| Upload-to-search rate | 60% | Funnel |
| Search-to-intro rate | 15% | Funnel |
| Intro approval rate | 50% | Marketplace |
| Marketplace supply coverage | 100 companies | Marketplace |
| Warm score accuracy | 80% | Model |
| Credit velocity | 500/week | Economy |

## How to Run

```bash
# Full scan (all agents)
python3 -m data_team.orchestrator --all

# Single agent
python3 -m data_team.orchestrator --agent pipeline

# Brief from cached reports (no scanning)
python3 -m data_team.orchestrator --lead-only

# Weekly deep dive
python3 -m data_team.orchestrator --weekly

# Monthly strategy review
python3 -m data_team.orchestrator --monthly

# Intelligence freshness check
python3 -m data_team.orchestrator --intel
```

## CoS Integration

The data team is a first-class citizen in the Chief of Staff ecosystem:
- Reports are loaded by `cos_agent.py:_load_reports()` from `data_team/reports/`
- Finding categories mapped to business outcomes in `business_outcomes.py`
- Cost tracked via `scan_duration_seconds` field on `DataTeamReport`
- Team reliability tracked by `cos_learning.py:update_team_reliability("data", ...)`
- Cross-team requests surface in CoS founder briefs
- Data team findings appear in `--cos-daily` alongside engineering findings

## Coordination Model

- **Engineering team** — Data team identifies instrumentation gaps, engineering implements the tracking code
- **CoS** — Data team reports feed into founder briefs; cross-team requests route through CoS
- **Founder** — Monthly reviews provide data maturity assessment and roadmap
