# Pipeline Agent

## Role
Schema audit, index analysis, data quality checks, SQL template validation.

## Responsibilities
1. **Schema Completeness** — Verify all 27 expected tables exist in SQLAlchemy models
2. **Column Quality** — Check for standard columns (created_at, updated_at) across tables
3. **Index Coverage** — Identify analytics-critical tables missing indexes
4. **PII Protection** — Verify all encrypted columns are registered in PrivacyGuard
5. **Instrumentation** — Audit usage_log action coverage for analytics readiness
6. **Data Retention** — Verify retention policies exist in code
7. **SQL Templates** — Re-validate all query templates against PrivacyGuard

## How It Works
- Reads `app/models/*.py` via AST parsing to extract `__tablename__`, columns, indexes
- Scans `app/services/` and `app/api/` for usage_log action strings
- Validates all SQL templates in `data_team/shared/sql_templates.py`
- Does NOT connect to a live database

## Key Metrics
- `tables_in_models`: Number of tables found in model files
- `index_count`: Total indexes detected
- `instrumentation_coverage`: Ratio of expected actions found in code
- `sql_templates_valid`: Templates passing privacy validation

## CLI Usage
```bash
python -m data_team.orchestrator --agent pipeline
```

## Output
`DataTeamReport` with findings (schema_coverage, data_quality, instrumentation, privacy_compliance).
