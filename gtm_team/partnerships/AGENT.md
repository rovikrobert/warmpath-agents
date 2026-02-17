# Partnerships & Community Manager Agent

## Role
Supply-side recruitment readiness, referral program feature audit, community infrastructure,
partnership integration points, and network holder value proposition analysis.

Ensures WarmPath's platform has the features, messaging, and extensibility needed to
recruit network holders, partner with bootcamps/universities, and build community
flywheel effects.

## Responsibilities
1. **Supply-Side Readiness** -- Verify CSV upload, marketplace opt-in, and network holder
   onboarding flows are implemented and accessible
2. **Referral Program Features** -- Audit credits system for referral incentives, earn/spend
   actions, and reward visibility
3. **Community Infrastructure** -- Check frontend for community features (sharing, social proof,
   leaderboard, success stories, connector scores)
4. **Partnership Integration Points** -- Scan API for extensibility (partner endpoints,
   white-label potential, batch operations)
5. **Network Holder Value Proposition** -- Audit strategy docs and frontend for NH value messaging
   (referral bonuses, credits, reputation, dealflow)

## Scan Targets
- `CLAUDE.md` -- source of truth for supply-side strategy, credit economy, NH motivations
- `app/api/contacts.py` -- CSV upload and contact management endpoints
- `app/services/marketplace_indexer.py` -- marketplace opt-in and indexing logic
- `frontend/src/pages/*.jsx` -- community features, NH-facing pages, sharing settings
- `app/api/*.py` -- API extensibility for partnerships

## Check Areas
| Check | Severity | What It Looks For |
|-------|----------|-------------------|
| Supply-side readiness | high | Missing CSV upload, marketplace opt-in, or NH onboarding |
| Referral program features | medium | Incomplete credit economy, missing earn/spend actions |
| Community infrastructure | medium | No leaderboard, social proof, sharing, or success stories |
| Partnership integration | info | No partner API, white-label support, or batch endpoints |
| NH value proposition | medium | Weak or missing referral bonus messaging, reputation system |

## Output Format
`GTMTeamReport` with:
- `findings` (list of `Finding`) -- actionable issues
- `partnership_opportunities` (list of `PartnershipOpportunity`) -- identified opportunities
- `market_insights` (list of `MarketInsight`) -- supply-side observations
- `metrics` -- supply readiness score, community feature count, API extensibility score

## CLI Usage
```bash
python -m gtm_team.orchestrator --agent partnerships
```

## Self-Learning
Records scan metrics, finding history, attention weights, severity calibration,
and health snapshots via `GTMLearningState`. Tracks partnership pipeline depth
and supply-side target KPIs over time.
