# DataLead Agent

## Role
Strategy, KPI framework, cross-team coordination, daily/weekly/monthly briefs.

## Responsibilities
1. **KPI Framework** — Define and track key performance indicators for the two-sided marketplace
2. **Brief Generation** — Daily insights, weekly deep dives, monthly strategy reviews
3. **Cross-Team Coordination** — Surface requests to engineering via CrossTeamRequest objects
4. **Insight Aggregation** — Merge pipeline, analyst, and model_engineer findings into actionable summaries

## How It Works
- Loads cached reports from `data_team/reports/` (pipeline, analyst, model_engineer)
- Aggregates findings, insights, and metrics
- Generates markdown briefs with KPI dashboards
- Emits `cross_team_requests` when data issues need engineering attention
- Reports feed into CoS founder briefs via `_load_reports()` expansion

## KPI Targets
| KPI | Target | Yellow |
|-----|--------|--------|
| activation_rate | 40% | 25% |
| upload_to_search_rate | 60% | 40% |
| search_to_intro_rate | 15% | 8% |
| intro_approval_rate | 50% | 30% |
| warm_score_accuracy | 80% | 60% |

## CLI Usage
```bash
python -m data_team.orchestrator --lead-only   # Daily brief from cached reports
python -m data_team.orchestrator --weekly       # Weekly deep dive
python -m data_team.orchestrator --monthly      # Monthly review
```

## Output
`DataTeamReport` with aggregated findings, insights, and cross-team requests.
