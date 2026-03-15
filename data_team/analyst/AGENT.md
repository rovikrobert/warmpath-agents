# Analyst Agent

## Role
Funnel analysis, engagement metrics, marketplace health, anomaly detection.

## Responsibilities
1. **Funnel Mapping** — Map the full user journey (signup to offer) and check instrumentation
2. **Engagement Tracking** — Verify engagement events are captured in usage_logs
3. **Application Funnel** — Check application status enum covers the full hiring pipeline
4. **Marketplace Coverage** — Verify marketplace API endpoints are instrumented
5. **Credit Analytics** — Check credit transaction types cover earn/spend scenarios
6. **Experiment Instrumentation** — Validate Phase 3 adaptive scope experiment events (search_scope_selected, search_scope_auto_selected, marketplace_nudge_shown, marketplace_nudge_accepted, search_scope_decision) are present in frontend source

## How It Works
- Scans API endpoint files via AST to map the full endpoint surface
- Searches for action strings in services and API code
- Maps 12 funnel steps to expected usage_log action names
- Checks marketplace.py for search/request/approve/decline patterns
- Does NOT connect to a live database

## Funnel Steps Tracked
signup -> email_verify -> csv_upload -> contacts_list -> search_create ->
smart_search -> marketplace_search -> intro_draft -> intro_request ->
intro_approve -> application_create -> application_update

## Key Metrics
- `funnel_steps_instrumented`: Steps with matching usage_log actions
- `funnel_coverage`: Ratio of instrumented steps
- `engagement_events_instrumented`: Engagement events found
- `marketplace_patterns_found`: Marketplace action patterns detected
- `experiment_events_expected`: Phase 3 experiment events to validate
- `experiment_events_instrumented`: Experiment events found in frontend source

## CLI Usage
```bash
python -m data_team.orchestrator --agent analyst
```

## Output
`DataTeamReport` with findings (instrumentation) and insights (funnel readiness).
