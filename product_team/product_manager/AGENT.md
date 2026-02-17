# Product Manager Agent

## Role
Feature mapping, PRD templates, acceptance criteria audit, backlog health.

## Responsibilities
1. **Feature Mapping** — Map API endpoints to frontend pages (coverage audit)
2. **Orphan Detection** — Identify API endpoints without frontend consumers and pages without API backing
3. **Test Coverage Audit** — Check test files for acceptance-criteria patterns per API module
4. **Integration Gaps** — Identify where API exists but no test, or page exists but no API
5. **Feature Scorecard** — Generate feature completeness scorecard

## How It Works
- Reads `app/api/*.py` to extract route definitions (@router.get, @router.post, etc.)
- Cross-references with `frontend/src/pages/*.jsx` for frontend coverage
- Scans `tests/test_*.py` for test coverage per API module
- Computes feature coverage scores
- Does NOT modify any code — read-only analysis

## Key Metrics
- `total_api_endpoints`: Number of API route definitions found
- `frontend_pages`: Number of page components found
- `feature_coverage_score`: API-to-frontend alignment (0-1.0)
- `api_test_coverage`: % of API modules with dedicated tests

## CLI Usage
```bash
python -m product_team.orchestrator --agent product_manager
```

## Output
`ProductTeamReport` with findings (feature_coverage) and ProductInsights (feature_coverage, strategy).
