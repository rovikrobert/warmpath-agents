# Product Monetization Manager Agent

## Role
Pricing architecture, credit economy strategy, feature gating, revenue modeling,
and marketplace monetization for WarmPath's GTM team.

The Monetization Manager validates that pricing, credit economy, and revenue
models documented in strategy docs are correctly reflected in the codebase.
It scans both strategy documents and implementation files to surface gaps
between planned monetization and actual implementation.

## Responsibilities
1. **Pricing Architecture** -- Verify pricing tiers are documented and Stripe/payment integration exists in the codebase. No pricing model is high severity.
2. **Credit Economy** -- Validate credit earn/spend actions, expiry rules, and non-transferability in `app/services/credits.py`. Gaps are medium severity.
3. **Feature Gating** -- Scan API files for free vs paid tier checks (access control patterns). No gating found is medium severity.
4. **Revenue Model** -- Check strategy docs for revenue projections and model documentation. Missing model is medium severity.
5. **Marketplace Monetization** -- Scan marketplace models/API for monetization hooks (credit deduction, billing triggers). Gaps are medium severity.

## Scan Targets
- `CLAUDE.md` -- business model and credit economy source of truth
- `app/services/credits.py` -- credit economy implementation
- `app/api/credits.py` -- credit API endpoints
- `app/models/marketplace.py` -- marketplace data model
- `app/api/marketplace.py` -- marketplace API endpoints
- `app/api/*.py` -- all API files for feature gating patterns
- Strategy docs via `load_strategy_docs()`

## Check Areas
| Check | Severity (if gap) | Key signals |
|-------|-------------------|-------------|
| Pricing architecture | high | No pricing tiers documented or no Stripe integration |
| Credit economy | medium | Missing earn/spend/expiry rules in credits service |
| Feature gating | medium | No free vs paid tier access control in API |
| Revenue model | medium | No revenue projections in strategy docs |
| Marketplace monetization | medium | No credit deduction or billing in marketplace |

## Output
`GTMTeamReport` with:
- `findings` -- monetization gaps requiring action
- `market_insights` -- pricing and revenue observations
- `metrics` -- monetization readiness score, credit actions count, gating coverage
- `learning_updates` -- hot spots, scan count, KPI trends

## Learning State
Stored at `gtm_team/monetization/state.json`:
- Finding history with recurring pattern detection (5+ auto-escalate, 10+ systemic)
- Attention weights (EMA + time decay) on monetization file hot spots
- Severity calibration tracking
- KPI trends: `monetization_readiness`, `credit_actions`, `gating_coverage`
- Health trajectory for monetization readiness over time

## CLI Usage
```bash
python -m gtm_team.orchestrator --agent monetization
```
