# Keevs -- Job Seeker Coach & Quality Auditor

## Role

Keevs audits the in-app coaching service quality and job seeker journey coverage.
The coaching service (coach_service.py) powers the Keevs AI coach persona that
gives job seekers personalised briefings, chat responses, and career guidance
based on their full platform context (network, applications, preferences, credits,
market trends).

This agent scans the coaching service, API layer, and frontend pages to verify
that every job seeker scenario is covered, context assembly is complete, mock
mode is robust, and streaming is hardened.

## Owns

- `ops_team/keevs/coach_service.py` -- the in-app coaching service (moved from
  `app/services/`). Contains system prompt, context assembly, Claude chat,
  mock chat, briefing generation, and streaming.

## Scans

| Source                         | Purpose                                |
|--------------------------------|----------------------------------------|
| `ops_team/keevs/coach_service.py` | System prompt, context assembly, mock handlers |
| `app/api/coach.py`            | SSE streaming, concurrency, timeout    |
| `frontend/src/pages/*.jsx`    | Coaching integration, journey steps    |

## Check Areas

1. **System prompt coverage** -- Does `_KEEVS_SYSTEM_PROMPT` mention referrals,
   privacy rules (no naming contacts), link formatting, no-filler rules? Count
   rules found vs expected.

2. **Context assembly completeness** -- Does `_assemble_context` pull all
   required data sources: user profile, preferences, network analysis, pipeline
   (applications), searches, credits, market trends? Count sources found.

3. **Mock mode response quality** -- Does `_mock_chat_response` have keyword
   handlers for the core job seeker scenarios: follow-up, network, company,
   credit, start, pipeline? Compare handler count to
   `COACH_KEYWORD_COVERAGE_TARGET`.

4. **Job seeker journey coverage** -- For each step in `COACH_JOURNEY_STEPS`
   (signup, upload, search, message, track, interview), verify there is a
   frontend page referencing that step or concept. Count covered steps.

5. **Frontend coaching integration** -- Check JSX pages for `/coach` or
   `/briefing` API calls, coaching-related imports or component references.

6. **SSE streaming robustness** -- Verify `app/api/coach.py` handles: SSE
   timeout (`_SSE_TIMEOUT_SECONDS`), concurrent stream limit
   (`_MAX_CONCURRENT_STREAMS`), content sanitisation, `CancelledError` handling.

## Output

`OpsTeamReport` with:
- `findings` -- cross-compatible `Finding` objects (from `agents.shared.report`)
- `ops_insights` -- `OpsInsight` objects with coaching quality observations
- `metrics` -- coaching quality numbers (prompt rule coverage, context source
  count, mock handler coverage ratio, journey step coverage, streaming checks)
- `learning_updates` -- summary of scan results for CoS consumption

## Learning

`OpsLearningState` (from `ops_team.shared.learning`) tracks:
- Coaching quality trends across scans
- Hot spots (files with recurring findings)
- KPI trends: `prompt_rule_coverage`, `context_source_count`,
  `mock_handler_coverage`, `journey_coverage`
- Severity calibration and fix effectiveness

## Usage

```bash
# Run via orchestrator
python3 -m ops_team.orchestrator --agent keevs

# Or import directly
from ops_team.keevs.keevs import scan, save_report
report = scan()
save_report(report)
```
