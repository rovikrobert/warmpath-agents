# Treb -- Network Holder Partner Auditor

## Role

Treb audits the **network holder (supply-side) experience** end-to-end: CSV upload,
marketplace sharing controls, intro facilitation, engagement touchpoints, and the
earn/reward loop. Its goal is to ensure the supply side of the WarmPath marketplace
is well-instrumented, complete, and frictionless -- because without healthy supply,
the marketplace has nothing to search.

## Persona

Treb maps to the `network_holder` ops persona (tier: supply). It is the supply-side
counterpart to Keevs, which covers the demand-side (job seeker) experience.

## Files Scanned

| Path | Purpose |
|------|---------|
| `app/api/contacts.py` | CSV upload, contact CRUD, relationship endpoints |
| `app/api/marketplace.py` | Opt-in, sharing controls, intro facilitation endpoints |
| `app/services/marketplace_indexer.py` | Anonymised listing generation, category filtering |
| `frontend/src/pages/*.jsx` | Supply-side pages, engagement UI, upload flow |

## Check Areas

### 1. NH Journey Completeness

Verifies each step of the network holder journey has backend support:

1. **Signup** -- `/signup` endpoint in auth routes
2. **Upload CSV** -- `/upload` endpoint in contacts routes
3. **Opt-in to marketplace** -- `opt_in` or `sharing` references in marketplace routes
4. **Review intros** -- `approve` / `decline` endpoints in marketplace routes
5. **Earn** -- Credit references (earn, credit, bonus) in contacts/marketplace routes

Missing journey steps are flagged as **high** severity.

### 2. Sharing Controls

Checks marketplace API and service code for the four sharing controls from CLAUDE.md:

- `opt_in_marketplace` toggle
- Category filters (e.g. "share tech but not banking")
- Individual exclusions
- Pause / unpause sharing

Missing controls are flagged as **medium** severity.

### 3. Intro Facilitation Flow

Validates the intro lifecycle endpoints exist and track status:

- `request_intro` endpoint
- `approve_intro` endpoint
- `decline_intro` endpoint
- Status tracking (`pending`, `approved`, `declined`)

Missing facilitation endpoints are flagged as **high** severity.

### 4. Frontend Supply-Side Pages

Scans JSX pages for supply-side keywords: contacts, sharing, marketplace, upload,
referral bonus, connector. Counts how many pages serve the network holder persona.

### 5. Engagement Touchpoints

Checks for engagement/notification patterns that keep network holders active:

- Welcome email / onboarding
- Upload confirmation
- Intro notification (new request alert)
- Earn notification (credit earned)
- Reputation / connector score display
- Leaderboard presence

Missing touchpoints are flagged as **medium** severity.

## Output

`OpsTeamReport` with:
- `findings` -- cross-compatible with engineering `Finding` schema
- `ops_insights` -- supply-side operational insights
- `metrics` -- NH journey coverage, sharing controls count, supply page count, etc.

Report saved to `ops_team/reports/treb_latest.json`.

## Learning

`OpsLearningState("treb")` tracks:
- Finding history with recurring pattern detection (5+ escalation, 10+ systemic)
- Attention weights (EMA + decay) on scanned files
- Severity calibration
- KPI trends (nh_journey_coverage, sharing_controls_found, supply_pages)
- Health trajectory over time
