# Marsh -- Marketplace Health Auditor

## Role

Marsh audits the marketplace model completeness, credit economy integrity,
intro facilitation pipeline, and coverage signals across the WarmPath codebase.
The marketplace is the core revenue mechanism -- job seekers pay for access to
networks they do not have, and network holders earn credits by facilitating
intros. Marsh ensures all the moving parts (listings, credits, intros,
suppression) are structurally sound and trackable.

This agent scans the marketplace models, credit service, and API layer to verify
that every marketplace action is covered, the credit economy has all expected
earn/spend paths, the intro pipeline tracks all statuses, and the suppression
list is enforced on marketplace operations.

## Scans

| Source                           | Purpose                                      |
|----------------------------------|----------------------------------------------|
| `app/models/marketplace.py`     | Listing model completeness, intro statuses   |
| `app/services/credits.py`       | Earn/spend/expire logic, balance calculation  |
| `app/api/marketplace.py`        | Intro pipeline endpoints, marketplace search |
| `app/api/credits.py`            | Credit purchase/history/expiry API coverage   |

## Check Areas

1. **Marketplace model completeness** -- Verify `MarketplaceListing` has core
   anonymized fields (company_id, role_level, department_category,
   warm_score_range, is_available) and `IntroFacilitation` has pipeline fields
   (status, job_seeker_id, network_holder_id, marketplace_listing_id). Count
   fields found vs expected. Flag missing fields (severity: high if core listing
   fields absent, medium otherwise).

2. **Credit economy** -- Verify `app/services/credits.py` implements earn
   actions (csv_upload, intro_facilitation, data_freshness), spend actions
   (cross_network_search, request_intro), expiry logic (`expire_stale_credits`),
   and non-transferability (no transfer function). Count earn/spend actions
   found. Verify balance calculation and transaction logging. Flag missing
   actions (severity: medium).

3. **Intro pipeline metrics** -- Check `app/api/marketplace.py` for the full
   intro lifecycle: request-intro endpoint, approve/decline endpoint, status
   tracking for pending/approved/declined/expired. Count pipeline stages found.
   Flag missing stages (severity: high).

4. **Marketplace actions coverage** -- For each action in `MARKETPLACE_ACTIONS`
   (cross_network_search, request_intro, approve_intro, decline_intro), verify
   it exists across the scanned source files. Count covered actions.

5. **Suppression list marketplace impact** -- Check that suppression list
   checking is referenced in marketplace operations. Verify
   `suppression_list` model/table exists. Flag if suppression is not checked
   during marketplace search (severity: high).

6. **Coverage signals** -- Check for fields that track marketplace coverage:
   company count, listing count, active listings, geographic distribution.
   Flag if coverage tracking is absent (severity: medium).

## Output

`OpsTeamReport` with:
- `findings` -- cross-compatible `Finding` objects (from `agents.shared.report`)
- `marketplace_findings` -- `MarketplaceFinding` objects with category-tagged results
- `ops_insights` -- `OpsInsight` objects with marketplace health observations
- `metrics` -- marketplace health numbers (model field coverage, earn/spend action
  counts, pipeline stage count, marketplace action coverage, suppression status)
- `learning_updates` -- summary of scan results for CoS consumption

## Learning

`OpsLearningState` (from `ops_team.shared.learning`) tracks:
- Marketplace health trends across scans
- Hot spots (files with recurring findings)
- KPI trends: `model_field_coverage`, `earn_action_count`, `spend_action_count`,
  `pipeline_stage_count`, `marketplace_action_coverage`
- Severity calibration and fix effectiveness

## Usage

```bash
# Run via orchestrator
python3 -m ops_team.orchestrator --agent marsh

# Or import directly
from ops_team.marsh.marsh import scan, save_report
report = scan()
save_report(report)
```
