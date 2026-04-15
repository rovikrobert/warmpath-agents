# warmpath-agents

> **This project was sunset on April 28, 2026.** The code is preserved here
> for reference and learning. PRs and issues will not be reviewed.

Six specialist AI agent teams + a Chief of Staff supervisor, built with
LangGraph and Claude SDK. Extracted from a real production product
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
| **Chief of Staff** | LangGraph supervisor graph | Classifies, routes, dispatches, synthesizes across all teams |

## What's Interesting Here

- **LangGraph CoS supervisor** — classify, route, dispatch, synthesize,
  evaluate, escalate/end
- **Trust model** — agents earn trust levels: Observer, Recommender,
  Contributor, Deployer
- **Unified Memory Service** — Postgres (BM25 tsvector) + Qdrant (vector)
  hybrid retrieval with temporal decay + MMR re-ranking
- **MCP server** — 19 tools for querying production state with privacy
  enforcement (PrivacyGuard)
- **Daily cost guard** — automatic Haiku fallback when daily spend exceeds
  budget
- **Auto-repair pipeline** — ruff lint + pytest gate + PR for human review

## Examples

See [`examples/`](examples/) for real outputs from these agent teams
scanning the WarmPath codebase with synthetic seed data.

## Quick Start

```bash
# 1. Clone the product repo (the thing the agents analyze)
git clone https://github.com/Rovik/warmpath.git
cd warmpath && make dev && make seed && cd ..

# 2. Clone this repo
git clone https://github.com/Rovik/warmpath-agents.git
cd warmpath-agents

# 3. Run a scan
python3 -m agents.orchestrator --all
```

## Bundled Support Code

The `_support/` directory contains a minimal subset of the WarmPath
product code (database, config, ORM base) that the agent framework
depends on. See [`_support/README.md`](_support/README.md) for details.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
