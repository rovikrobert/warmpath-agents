# OpsLead — Operations Team Coordinator

## Role

OpsLead aggregates reports from the four leaf agents (Keevs, Treb, Naiv, Marsh) and produces
daily/weekly/monthly briefs with an ecosystem health scorecard. It also emits cross-team
requests to engineering, data, and product teams via CoS.

## Scans

- `ops_team/reports/` — cached sub-agent reports (`keevs_latest.json`, `treb_latest.json`, etc.)

## Outputs

### Daily Brief
- Ecosystem health scorecard (coaching, supply, satisfaction, marketplace)
- Top findings across all agents (critical/high first)
- Cross-team requests (e.g., "engineering: fix SSE timeout", "product: add empty state")
- Agent status summary

### Weekly Report
- Trend analysis across all ops dimensions
- Supply-demand balance assessment
- Satisfaction trajectory
- Learning updates from all agents

### Monthly Review
- KPI progress vs targets
- Strategic recommendations
- Ecosystem maturity assessment

## Cross-Team Requests

OpsLead emits structured requests to other teams:
- `target_team`: engineering | data | product
- `urgency`: critical | high | medium | low
- `request`: description of what's needed
- `source_agent`: which ops agent identified the need
- `finding_id`: linked finding for traceability

## Learning

Uses `OpsLearningState` to track:
- Brief quality over time
- Cross-team request resolution rates
- Ecosystem health trajectory

## CoS Integration

Reports flow into the Chief of Staff daily brief under "Operations Team" section.
OpsLead's cross_team_requests surface as CrossTeamRequest objects in founder briefs.
