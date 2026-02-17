# Naiv -- Customer Satisfaction Auditor

## Role

Naiv audits the codebase for signals that affect customer satisfaction --
error message quality, feedback collection coverage, journey milestone
celebrations, and usage tracking completeness. The goal is to ensure every
user-facing touchpoint is instrumented for satisfaction correlation and
that the product feels intentional and polished at every step.

## Identity

| Field          | Value                              |
|----------------|------------------------------------|
| Agent name     | `naiv`                             |
| Team           | `ops_team`                         |
| Report type    | `OpsTeamReport`                    |
| Learning state | `OpsLearningState` (naiv/state.json) |

## Scan Targets

| Directory / File              | Purpose                                  |
|-------------------------------|------------------------------------------|
| `app/api/*.py`                | API error handling patterns              |
| `frontend/src/pages/*.jsx`    | Feedback widgets, milestones, empty states |
| `app/middleware/usage.py`     | Usage tracking coverage                  |

## Check Areas

### 1. Error Message Quality (`_check_error_message_quality`)

Scans every API endpoint file for `HTTPException` and `raise` patterns.
Flags endpoints that return bare 500s, generic "Internal Server Error"
strings, or raw tracebacks. User-friendly error messages should include
a clear description of what went wrong and, where possible, a next step.

- **Severity:** medium per API file lacking custom error handling

### 2. Feedback Collection Points (`_check_feedback_collection`)

Searches JSX pages for feedback-related UI patterns: rating components,
survey prompts, NPS widgets, thumbs-up/down, polls, review forms. Counts
pages with at least one feedback collection point.

- **Severity:** high if zero feedback collection points found across all pages

### 3. Journey Milestone Celebration (`_check_journey_milestones`)

Searches JSX pages for celebration and acknowledgment patterns:
congratulations, success messages, welcome screens, milestone badges,
achievement toasts, completion notifications. Flags missing celebrations
for critical first-time actions (first upload, first search).

- **Severity:** medium for missing milestone celebrations

### 4. Usage Tracking Coverage (`_check_usage_tracking`)

Checks API files for `UsageLog` references and cross-references against
`app/middleware/usage.py` for tracked actions. Counts endpoints with
tracking vs those without. Gaps in usage tracking mean blind spots in
satisfaction correlation analysis.

- **Severity:** low per untracked endpoint

### 5. Empty State Handling (`_check_empty_states`)

Checks JSX pages for empty state UX: "no results", "get started",
"nothing here" patterns. Pages without empty states leave users confused
when data has not been populated yet.

- **Severity:** medium per page missing empty state handling

## Output

`OpsTeamReport` containing:

- `findings` -- cross-compatible `Finding` objects (same schema as engineering agents)
- `satisfaction_findings` -- `SatisfactionFinding` objects with category, persona, and recommendation
- `metrics` -- counts for each check area (error handling ratio, feedback points, milestone coverage, tracking coverage, empty state coverage)
- `learning_updates` -- trend observations from `OpsLearningState`

## Learning

`OpsLearningState` persisted at `ops_team/naiv/state.json`:

- Records every finding for recurring pattern detection
- Tracks attention weights (EMA + decay) to highlight persistent hot spots
- Monitors satisfaction-related KPI trends across scans
- Records health snapshots for trajectory analysis
- Generates meta-learning reports on demand

## CLI

```bash
# Run Naiv standalone
python3 -m ops_team.orchestrator --agent naiv

# Run full ops team (includes Naiv)
python3 -m ops_team.orchestrator --all
```
