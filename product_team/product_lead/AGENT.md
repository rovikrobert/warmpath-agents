# Product Lead Agent

## Role
Coordination, daily/weekly/monthly briefs, cross-team requests.

## Responsibilities
1. **Aggregation** — Load and merge sub-agent reports (user_researcher, product_manager, ux_lead, design_lead)
2. **Daily Brief** — Top insight, UX friction, design debt, competitive intel
3. **Weekly Report** — Feature scorecard, UX/design debt, research priorities
4. **Monthly Review** — Persona refresh, strategy assessment, roadmap
5. **Cross-Team Requests** — Emit requests to Engineering and Data teams

## How It Works
- Loads cached `*_latest.json` reports from `product_team/reports/`
- Aggregates findings, insights, and metrics from all sub-agents
- Generates briefs at daily/weekly/monthly cadence
- Emits cross-team requests when UX score is low or feature coverage has gaps
- Reports flow through CoS into founder briefs

## Key Metrics
- `sub_agents_reporting`: Number of sub-agent reports loaded
- `total_findings`: Aggregate finding count
- `total_insights`: Aggregate insight count

## CLI Usage
```bash
python -m product_team.orchestrator --daily-brief
python -m product_team.orchestrator --weekly
python -m product_team.orchestrator --monthly
```

## Output
`ProductTeamReport` with aggregated findings, insights, and cross-team requests.
