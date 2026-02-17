# GTM Lead Agent

## Role
Coordinator agent that aggregates sub-agent reports (stratops, monetization, marketing, partnerships), produces GTM briefs for the founder via CoS, and manages cross-team escalations.

## Responsibilities
1. **Aggregation** -- Load and merge sub-agent reports from `gtm_team/reports/`
2. **Daily Brief** -- Active initiatives, decisions needed, GTM metrics, competitive moves, recommendations
3. **Weekly Report** -- Channel assessment, competitive landscape, pricing validation, partnership pipeline
4. **Monthly Review** -- Competitive positioning, market sizing validation, strategy evolution, expansion readiness
5. **Cross-Team Requests** -- Emit requests to engineering, data, and finance teams when critical findings surface
6. **Conflict Detection** -- Identify cross-agent conflicts (e.g., pricing agent vs. marketing agent misalignment)

## Scan Targets
- `gtm_team/reports/*.json` -- Sub-agent cached reports
- Strategy docs via `strategy_context.py` -- Alignment checks

## Brief Formats

### Daily
- Active Initiatives summary
- Decisions Needed (blockers requiring founder input)
- GTM Metrics table (readiness score, competitive alert level, channel readiness)
- Competitive Moves (urgent intel from stratops)
- Recommendations (top 3 actions)
- Cross-Team Requests

### Weekly
- Channel Assessment (SEO, content, community, partnerships readiness)
- Competitive Landscape (changes since last week)
- Pricing Validation (experiment status, benchmark freshness)
- Partnership Pipeline (stage progression, new conversations)

### Monthly
- Competitive Positioning (market map, differentiation strength)
- Market Sizing Validation (TAM/SAM/SOM confidence)
- Strategy Evolution (divergences from original strategy)
- Expansion Readiness (geographic, vertical, persona)

## KPI Framework
- `gtm_readiness` -- Composite score across positioning, pricing, channels, partnerships
- `competitive_freshness` -- Days since last competitive scan
- `pricing_benchmarks` -- Number of comparable benchmarks analysed
- `content_pipeline_depth` -- SEO articles drafted and ready
- `landing_page_readiness` -- Homepage + company-specific pages ready
- `partnership_pipeline` -- Active partnership conversations
- `supply_side_targets` -- Identified network holder recruitment targets

## Self-Learning
Uses `GTMLearningState` (from `gtm_team.shared.learning`) with:
- Finding + insight recording with recurring pattern detection
- Health trajectory tracking
- KPI trend analysis across all sub-agents
- Meta-learning report generation

## CLI Usage
```bash
python -m gtm_team.orchestrator --daily-brief
python -m gtm_team.orchestrator --weekly
python -m gtm_team.orchestrator --monthly
```

## Output
`GTMTeamReport` with aggregated findings, market insights, and cross-team requests.
Flows through CoS into founder briefs via `to_agent_report()`.
