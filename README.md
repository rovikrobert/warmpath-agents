# warmpath-agents

> **This project was sunset on April 28, 2026.** The code is preserved here
> for reference and learning. PRs and issues will not be reviewed.

Six specialist AI agent teams + a Chief of Staff supervisor, built on the
Claude SDK. Extracted from a real production product
([WarmPath](https://github.com/Rovik/warmpath)) where these agents ran
daily scans, generated briefs, and surfaced operational insights.

## Agent Teams

| Team | Agents | What It Does |
|------|--------|------|
| **Engineering** | security scanner, N+1 detector, performance scanner, dep auditor | Code quality + security scanning |
| **Data** | warm score analyst, enrichment monitor, funnel analyst, query auditor | Data pipeline health + analytics |
| **Product** | PRD reviewer, activation analyst, UX scanner, feature prioritizer | Product quality + user activation |
| **Ops** | coaching quality, network holder activation, satisfaction monitor, marketplace health | Operational health + coaching |
| **Finance** | credit economist, revenue tracker, compliance auditor, cost monitor | Financial health + compliance |
| **GTM** | competitive intel, content pipeline, partnership tracker, pricing analyst | Go-to-market intelligence |
| **Chief of Staff** | classify/route/dispatch/synthesize pipeline | Cross-team supervisor |

## What's Interesting Here

- **Chief of Staff supervisor** — classify, route, dispatch, synthesize,
  evaluate, escalate/end (`agents/chief_of_staff/`)
- **Trust model** — agents earn trust levels: Observer, Recommender,
  Contributor, Deployer
- **Unified Memory Service** — Postgres (BM25 tsvector) + Qdrant (vector)
  hybrid retrieval with temporal decay + MMR re-ranking
- **MCP server** — 19 tools for querying production state with privacy
  enforcement (PrivacyGuard) under `mcp_server/`
- **Daily cost guard** — automatic Haiku fallback when daily spend exceeds
  budget
- **Auto-repair pipeline** — ruff lint + pytest gate + PR for human review

## Examples

See [`examples/`](examples/) for real outputs from these agent teams
scanning the WarmPath codebase with synthetic seed data.

## Relationship with `warmpath`

This repo is a **snapshot** of the agent directories as they lived inside
the [WarmPath product monorepo](https://github.com/Rovik/warmpath). Agent
code references the product via `app.*` imports (models, config,
services), and scan configs in `agents/shared/config.py` point at
`PROJECT_ROOT/app`, `PROJECT_ROOT/tests`, `PROJECT_ROOT/frontend/src`,
etc.

Consequences:

- This repo **cannot run a full scan on its own** — there is nothing for
  the agents to scan, and several modules (`_support/models/__init__.py`,
  `_support/database.py`, `_support/utils/encryption.py`, `agents/memory/`,
  `ops_team/keevs/`, `ops_team/treb/`, a few finance services) import
  `app.*` from the product.
- The bundled `_support/` directory is a thin shim — it re-exports from
  `app.*`; it is not a standalone replacement.
- What you **can** do standalone: read the code, run `--help`, lint, and
  import modules that don't touch `app.*` (most of `agents/shared/`,
  `mcp_server/`).

## Install

Requires Python 3.11+.

```bash
# From a clean clone of this repo:
python3 -m pip install -e ".[dev]"
```

`pyproject.toml` lists the direct imports this repo uses. A real scan
additionally pulls in the full WarmPath dependency set (langgraph,
postgres drivers, redis, qdrant, etc.) — see
[`warmpath/requirements.txt`](https://github.com/Rovik/warmpath/blob/main/requirements.txt).

## Sanity checks (work from a clean clone)

```bash
make help                                # list available targets
make lint                                # ruff over all agent packages
make check                               # orchestrator --help smoke test
python3 -m agents.orchestrator --help    # equivalent of `make check`
```

## Running a full scan (requires the product repo)

```bash
# 1. Clone and bring up the product the agents scan
git clone https://github.com/Rovik/warmpath.git
cd warmpath && make dev && make seed

# 2. Make this repo importable from inside the product repo.
#    Either drop these directories into the warmpath checkout (matching
#    the layout they were extracted from), or add this clone to
#    PYTHONPATH alongside warmpath so `app.*` and `agents.*` both resolve.
export PYTHONPATH="/path/to/warmpath:/path/to/warmpath-agents:$PYTHONPATH"

# 3. Run a scan (Claude API key required; mock mode is the default)
python3 -m agents.orchestrator --all
```

## Bundled Support Code

The `_support/` directory contains the thinnest layer of glue (Base ORM
class, Settings scaffold, async/sync engines) that the agent framework
uses. It re-exports models from `app.models.*` — you still need the
WarmPath product repo on `PYTHONPATH` for those imports to resolve.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
