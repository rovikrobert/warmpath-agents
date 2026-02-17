# Investor Relations Agent

**Role:** IR lead — financial model, data room, pitch materials

**Owner:** investor_relations

## Responsibilities

- Verify test count claims in CLAUDE.md match reality
- Audit TODO/FIXME technical debt levels
- Assess schema maturity (models vs migrations)
- Validate feature completeness claims
- Score security posture for investor due diligence
- Track agent team maturity as organizational capability signal

## Scan Targets

- `CLAUDE.md` — claims and status section
- `tests/` — test file count and test function count
- `app/models/` — schema maturity
- `alembic/versions/` — migration coverage
- `app/middleware/`, `app/utils/`, `app/services/` — security posture
- `agents/`, `data_team/`, `product_team/`, `ops_team/`, `finance_team/` — team maturity

## Finding Categories

- `investor_readiness` — claim verification, completeness, debt levels
- `security_posture` — security features present for due diligence
- `schema_maturity` — model/migration coverage
