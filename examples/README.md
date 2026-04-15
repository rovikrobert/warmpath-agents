# Example Agent Outputs

These are representative outputs from running the WarmPath agent system against a
seeded development database (3 users, 50 contacts, 30 marketplace listings).

All outputs were generated with `AI_MOCK_MODE=true` — no LLM API calls required.
Real email addresses, UUIDs, and internal URLs have been replaced with placeholders.

## What's here

| File | Team | Command |
|------|------|---------|
| [data-team-scan.md](data-team-scan.md) | Data | `python3 -m data_team.orchestrator --all` |
| [ops-team-scan.md](ops-team-scan.md) | Ops | `python3 -m ops_team.orchestrator --all` |
| [finance-team-scan.md](finance-team-scan.md) | Finance | `python3 -m finance_team.orchestrator --all` |
| [product-team-scan.md](product-team-scan.md) | Product | `python3 -m product_team.orchestrator --all` |
| [gtm-team-scan.md](gtm-team-scan.md) | GTM | `python3 -m gtm_team.orchestrator --all` |
| [cos-daily-brief.md](cos-daily-brief.md) | CoS | `python3 -m agents.orchestrator --cos-daily` |
| [engineering-scan.md](engineering-scan.md) | Engineering | `python3 -m agents.orchestrator --all` |

## How to reproduce

```bash
# 1. Seed the dev database
DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/warmpath_dev" \
  python3 -m scripts.seed_dev

# 2. Run any team scan
DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/warmpath_dev" \
  AI_MOCK_MODE=true \
  python3 -m data_team.orchestrator --all
```

## Notes

- Scan durations are from a 2024 MacBook Pro (M4 Max). Expect similar performance
  on any modern machine — scans are I/O-bound (DB queries + file reads), not CPU-bound.
- Agent learning state accumulates across runs. First-run outputs may differ slightly
  from these examples (which reflect ~2000+ prior scans in learning state).
- The `External Intelligence` sections show web search results that may be empty
  when running offline or without API keys configured.
