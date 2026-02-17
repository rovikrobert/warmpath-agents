# StratOps Manager Agent

## Role
Competitive intelligence, market entry strategy, geographic expansion readiness,
and referral rails thesis validation for WarmPath's GTM team.

The StratOps Manager is the strategic eyes of the GTM team. It scans strategy
documents and the codebase to assess competitive positioning, market entry
sequencing, geographic regulatory readiness, and the health of WarmPath's core
"referral rails" thesis.

## Responsibilities
1. **Competitive Coverage** -- Verify that tracked competitors are analysed and mentioned in strategy docs. Gaps in competitive awareness are high severity.
2. **Market Entry Analysis** -- Check for documented market entry strategy across target geographies (Singapore, US, APAC). Missing entry strategy is medium severity.
3. **Geographic Readiness** -- Validate regulatory/compliance notes exist for each target market (PDPA, GDPR, CCPA). Missing regulatory notes are medium severity.
4. **Positioning Strength** -- Confirm differentiation documentation, value propositions, and competitive advantages are articulated. No positioning documentation is high severity.
5. **Referral Rails Thesis** -- Check for platform evolution documentation (marketplace flywheel, network effects, referral bonus capture). Info-level observation.

## Scan Targets
- `CLAUDE.md` -- primary strategy source of truth
- `ARCHITECTURE.md` -- technical architecture decisions with strategic implications
- `README.md` -- public-facing positioning
- `COMPETITIVE_STRATEGY.md`, `MARKET_ANALYSIS_RECRUITMENT.md`, `PRODUCT_STRATEGY_RECRUITMENT.md` -- dedicated strategy docs (may not exist yet)
- All documents returned by `load_strategy_docs()`

## Check Areas
| Check | Severity (if gap) | Key signals |
|-------|-------------------|-------------|
| Competitive coverage | high | <50% of TRACKED_COMPETITORS mentioned |
| Market entry analysis | medium | No entry sequence or geographic strategy |
| Geographic readiness | medium | Missing regulatory notes for target markets |
| Positioning strength | high | No differentiation or value prop documentation |
| Referral rails thesis | info | Platform evolution documentation status |

## Output
`GTMTeamReport` with:
- `findings` -- operational gaps requiring action
- `market_insights` -- competitive and market observations
- `metrics` -- strategic readiness score, competitor coverage ratio, market count
- `learning_updates` -- hot spots, scan count, KPI trends

## Learning State
Stored at `gtm_team/stratops/state.json`:
- Finding history with recurring pattern detection (5+ auto-escalate, 10+ systemic)
- Attention weights (EMA + time decay) on strategy doc hot spots
- Severity calibration tracking
- KPI trends: `strategic_readiness`, `competitor_coverage`, `market_count`
- Health trajectory for strategic readiness over time

## CLI Usage
```bash
python -m gtm_team.orchestrator --agent stratops
```
