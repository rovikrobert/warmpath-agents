# Operations Team — WarmPath Ops Agents

## Overview

The Operations team is the **user-facing auditor layer** for WarmPath. It scans the codebase to verify that both sides of the marketplace — job seekers and network holders — have high-quality, complete, privacy-respecting experiences.

Five agents work together: four leaf auditors (Keevs, Treb, Naiv, Marsh) and one coordinator (OpsLead). All reports flow through the Chief of Staff into founder briefs.

## Agent Roster

| Agent | Role | Scans |
|-------|------|-------|
| **Keevs** | Job Seeker Coach Auditor | `ops_team/keevs/coach_service.py`, `app/api/coach.py`, frontend pages |
| **Treb** | Network Holder Partner Auditor | `app/api/contacts.py`, `app/api/marketplace.py`, `app/services/marketplace_indexer.py`, frontend pages |
| **Naiv** | Customer Satisfaction Auditor | All API endpoints, frontend pages, `app/middleware/usage.py` |
| **Marsh** | Marketplace Health Auditor | `app/models/marketplace.py`, `app/services/credits.py`, `app/api/marketplace.py`, `app/api/credits.py` |
| **OpsLead** | Coordinator | `ops_team/reports/` (cached sub-agent reports) |

## What Each Agent Does

### Keevs (Job Seeker Coach)
Owns the in-app coaching service (moved from `app/services/coach.py`). Audits:
- System prompt coverage across all job seeker scenarios
- Context assembly completeness (`_assemble_context` data sources)
- Mock mode response quality and keyword handler coverage
- Job seeker journey: signup > upload > search > message > track > interview
- Frontend coaching integration points
- SSE streaming robustness (timeout, concurrency, sanitization)

### Treb (Network Holder Partner Auditor)
Audits the supply side of the marketplace:
- NH journey: signup > upload CSV > opt-in > review intros > earn
- Sharing controls (opt_in, category filters, individual exclusions, pause)
- Intro facilitation flow (request/approve/decline endpoints)
- Frontend supply-side pages and engagement touchpoints

### Naiv (Customer Satisfaction Auditor)
Audits user experience quality across both sides:
- Error message quality across all API endpoints
- Feedback collection points (polls, ratings, NPS hooks)
- Journey milestone celebration/acknowledgment patterns
- Usage tracking coverage for satisfaction correlation
- Empty state UX quality
- MCP server health monitoring (deployed Railway service at `mcp-server-production-23a9.up.railway.app`)
- Email circuit breaker compliance (3/week marketing cap per user)
- Stuck upload watchdog coverage (15-min Celery Beat task → auto-fail + notification)

### Marsh (Marketplace Health Auditor)
Audits marketplace infrastructure and economics:
- Marketplace model completeness (supply/demand/coverage fields)
- Credit economy (earn/spend actions, expiry, non-transferability)
- Intro pipeline metrics (pending/approved/declined trackability)
- Suppression list marketplace impact, coverage signals
- Velocity rate limit auditing (`velocity_limit_hit` audit events, 3 daily caps from Phase 4: intro requests, intro approvals, manual intro confirmations)
- Feed generator performance (runs 3x daily for all active users via Celery Beat)

### OpsLead (Coordinator)
Aggregates all sub-agent reports and produces:
- **Daily brief:** Ecosystem health scorecard, top findings, cross-team requests
- **Weekly report:** Trend analysis, supply-demand balance, satisfaction trajectory
- **Monthly review:** KPI progress vs targets, strategic recommendations
- **Cross-team requests:** Emits structured requests to engineering/data/product

## Architecture

```
ops_team/
  __init__.py
  orchestrator.py          # CLI entry point
  OPS_TEAM.md              # This file
  shared/
    __init__.py
    config.py              # Paths, personas, KPI targets, thresholds
    privacy_guard.py       # PII + forbidden actions + aggregate threshold
    report.py              # OpsInsight, OpsTeamReport
    intelligence.py        # 12 ops intel categories
    learning.py            # OpsLearningState (self-learning)
  keevs/
    __init__.py
    AGENT.md
    coach_service.py       # In-app coaching service (moved from app/services/)
    keevs.py               # Agent scanner
  treb/
    __init__.py
    AGENT.md
    treb.py                # Agent scanner
  naiv/
    __init__.py
    AGENT.md
    naiv.py                # Agent scanner
  marsh/
    __init__.py
    AGENT.md
    marsh.py               # Agent scanner
  ops_lead/
    __init__.py
    AGENT.md
    ops_lead.py            # Coordinator + brief generators
  reports/
    .gitkeep               # Scan output directory
```

## Shared Modules

### Privacy Guard (`shared/privacy_guard.py`)
- **PII patterns:** email, phone, LinkedIn URL regex
- **Forbidden actions:** `expose_user_activity`, `share_individual_metrics`, `identify_job_seekers`, `leak_vault_data`, `surface_employer_info`, `export_pii`, `contact_users_directly`
- **Aggregate threshold:** Findings referencing <5 users are rejected
- `PrivacyViolation` exception = hard fail

### Report Schema (`shared/report.py`)
- `OpsTeamReport`: agent, timestamp, findings, ops_insights, satisfaction_findings, marketplace_findings, metrics, cross_team_requests, learning_updates
- `to_agent_report()` converts to `AgentReport` for CoS compatibility

### Intelligence (`shared/intelligence.py`)
12 ops-specific categories with per-agent relevance and TTL-based staleness:

| Category | Agents | Refresh |
|----------|--------|---------|
| job_market_trends | keevs, ops_lead | 7d |
| referral_best_practices | keevs | 14d |
| cultural_communication | keevs | 14d |
| competitor_ux | keevs, naiv | 7d |
| referral_bonus_benchmarks | treb | 14d |
| employee_engagement | treb | 14d |
| marketplace_retention | treb, marsh | 14d |
| company_hiring_signals | treb, marsh | 7d |
| nps_benchmarks | naiv | 14d |
| survey_design | naiv, ops_lead | 14d |
| marketplace_economics | marsh, ops_lead | 14d |
| credit_economy_benchmarks | marsh | 14d |

### Learning (`shared/learning.py`)
`OpsLearningState` — same API as engineering/data/product learning:
- Fix effectiveness tracking
- Recurring pattern escalation (5+/10+ thresholds)
- Attention weights (EMA + decay)
- Severity calibration
- Health trajectory snapshots
- KPI trend tracking
- Meta-learning reports

## CLI Commands

```bash
# Run all ops agents (leaf agents then OpsLead)
python3 -m ops_team.orchestrator --all

# Run single agent
python3 -m ops_team.orchestrator --agent keevs

# Briefs from cached reports (no scanning)
python3 -m ops_team.orchestrator --daily-brief
python3 -m ops_team.orchestrator --weekly
python3 -m ops_team.orchestrator --monthly

# Intelligence
python3 -m ops_team.orchestrator --intel              # Freshness check
python3 -m ops_team.orchestrator --intel-report        # Full summary
python3 -m ops_team.orchestrator --research-agenda     # Prioritized questions

# Learning
python3 -m ops_team.orchestrator --learning-report     # Meta-learning reports
```

## CoS Integration

Reports flow into the Chief of Staff daily brief under the "Operations Team" section:
- OpsLead's `cross_team_requests` surface as structured requests in founder briefs
- Team reliability tracked in `cos_learning.py`
- Cost tracking via `scan_duration_seconds` on every report
- 5 business outcome categories mapped in `business_outcomes.py`

## Business Outcome Alignment

| Category | Outcomes |
|----------|----------|
| coaching_effectiveness | Help Job Seekers |
| supply_activation | Help Network Holders |
| user_satisfaction | Help Job Seekers, Help Network Holders |
| marketplace_health | Help Job Seekers, Help Network Holders, Billion Dollar |
| ops_efficiency | Cost Efficiency |

## KPI Targets

| KPI | Target | Owner |
|-----|--------|-------|
| coaching_response_quality | 0.85 | Keevs |
| nh_journey_completion | 0.70 | Treb |
| intro_approval_rate | 0.60 | Treb, Marsh |
| satisfaction_score | 0.75 | Naiv |
| marketplace_coverage | 0.50 | Marsh |
