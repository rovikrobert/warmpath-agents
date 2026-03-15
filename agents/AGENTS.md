# WarmPath Agentic Engineering Team

## Overview

The `agents/` directory contains an automated engineering team that scans the WarmPath codebase for issues across seven domains: code architecture, test quality, performance, dependencies, documentation, security, and privacy. A lead agent aggregates findings into prioritized daily briefs.

## Architecture

```
agents/
├── orchestrator.py           # CLI entry point
├── AGENTS.md                 # This file
├── __init__.py
├── shared/
│   ├── config.py             # Paths, thresholds, severity weights
│   ├── report.py             # Finding + AgentReport dataclasses, merge logic
│   ├── learning.py           # Self-learning: state persistence, trends, attention weights
│   ├── intelligence.py       # External intelligence: pip-audit, dep versions, API status
│   └── intel_cache.json      # Cached intelligence data (auto-generated)
├── lead/
│   ├── AGENT.md              # Lead agent specification
│   ├── lead.py               # Brief generation, report aggregation
│   └── state.json            # Learning state (auto-generated)
├── architect/
│   ├── AGENT.md              # Architect agent specification
│   ├── architect.py          # Lint, format, file sizes, functions, conventions, N+1
│   └── state.json            # Learning state (auto-generated)
├── test_engineer/
│   ├── AGENT.md              # Test engineer specification
│   ├── test_engineer.py      # Coverage, assertion density, error-path tests
│   └── state.json            # Learning state (auto-generated)
├── perf_monitor/
│   ├── AGENT.md              # Performance monitor specification
│   ├── perf_monitor.py       # AI costs, indexes, N+1, LIMIT, table growth
│   └── state.json            # Learning state (auto-generated)
├── deps_manager/
│   ├── AGENT.md              # Dependency manager specification
│   ├── deps_manager.py       # Pinning, CVEs, imports, licenses, Dockerfile
│   └── state.json            # Learning state (auto-generated)
├── doc_keeper/
│   ├── AGENT.md              # Documentation keeper specification
│   ├── doc_keeper.py         # CLAUDE.md sync, docstrings, privacy claims, conventions
│   └── state.json            # Learning state (auto-generated)
├── security/
│   ├── AGENT.md              # Security agent specification
│   ├── security.py           # Wraps scripts/security_scan.py → AgentReport
│   └── state.json            # Learning state (auto-generated)
├── privy/
│   ├── AGENT.md              # Privacy agent specification
│   ├── privy.py              # Wraps scripts/privacy_scan.py → AgentReport
│   └── state.json            # Learning state (auto-generated)
└── reports/
    └── *_latest.json         # Latest report from each agent (auto-generated)
```

## Shared Infrastructure Ownership

The engineering team owns monitoring for these cross-cutting services:

| Service | Owner Agent | What to Monitor | Health Check |
|---------|------------|-----------------|--------------|
| **MCP Server** | perf_monitor | Response times, error rates, Railway service health | `check_health` MCP tool, Railway dashboard |
| **W&B Weave** | security | Trace volume vs 100K/month free-tier cap, PII redaction compliance | W&B dashboard usage page |
| **Auto-repair PRs** | code_quality (architect) | PR merge/revert rate, fix quality scores | `gh pr list --label auto-repair` |

## Quick Start

```bash
# Run all agents and generate daily brief
python -m agents.orchestrator --all

# Run a single agent
python -m agents.orchestrator --agent architect

# Generate brief from cached reports (no scanning)
python -m agents.orchestrator --lead-only

# Weekly trend report
python -m agents.orchestrator --weekly

# Refresh external intelligence (pip-audit, dep versions)
python -m agents.orchestrator --intel-update

# Skip test_engineer for faster runs (it runs pytest)
python -m agents.orchestrator --all --skip-tests

# Verbose logging
python -m agents.orchestrator --all -v
```

## Agents

| Agent | Scans For | Key Checks |
|-------|-----------|------------|
| **architect** | Code quality & structure | ruff lint/format, file sizes, function lengths, conventions, N+1 queries, hardcoded secrets |
| **test_engineer** | Test coverage & quality | pytest --cov, assertion density, error-path coverage, coverage trends |
| **perf_monitor** | Performance & costs | Claude API token costs, missing DB indexes, N+1 patterns, unbounded queries, table growth projections |
| **deps_manager** | Dependency health | Version pinning, CVEs (pip-audit), dead/missing deps, licenses, Dockerfile |
| **doc_keeper** | Documentation accuracy | CLAUDE.md sync (test/table counts), API docstrings, privacy policy claims, conventions |
| **security** | Security vulnerabilities | Dependency CVEs (OSV), dangerous code patterns, config safety, auth coverage, input validation |
| **privy** | Privacy compliance | PII encryption, suppression list, consent/DSAR, data retention, vault isolation, marketplace anonymization |
| **lead** | Aggregation & prioritization | Deduplicates cross-agent findings, generates daily briefs, tracks trends |

## Self-Learning System

Each agent maintains a `state.json` with:
- **Finding history** (last 500 entries) — tracks recurrence of issues
- **Attention weights** — files with more findings get higher scrutiny
- **Metrics history** (last 90 entries) — enables trend analysis (up/down/stable)
- **Resolution tracking** — records how findings are resolved (fixed/deferred/ignored)

The lead agent uses these to:
- Escalate chronic issues (seen 3+ times)
- Detect regressions (metric trending in wrong direction)
- Recommend strategic actions based on patterns

## Severity Levels

| Level | Weight | Meaning |
|-------|--------|---------|
| critical | 10 | Act immediately — security breach, data loss risk |
| high | 5 | Fix soon — CVEs, N+1 queries, privacy violations |
| medium | 2 | Plan to fix — large files, missing coverage, doc drift |
| low | 1 | Nice to have — formatting, missing docstrings |
| info | 0 | Informational only |

## Configuration

Key thresholds in `agents/shared/config.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `COVERAGE_WARN_THRESHOLD` | 80% | Flag modules below this coverage |
| `COVERAGE_CRITICAL_MODULES` | 90% | Stricter threshold for security/finance modules |
| `FILE_SIZE_WARN_LINES` | 300 | Flag files larger than this |
| `FUNCTION_SIZE_WARN_LINES` | 30 | Flag functions longer than this |
| `TEST_SLOW_THRESHOLD_SECONDS` | 2.0 | Flag slow tests |
| `QUERIES_PER_REQUEST_WARN` | 5 | Potential N+1 threshold |
| `DEP_STALE_DAYS` | 365 | Flag deps not updated in this long |
| `MAX_FINDINGS_PER_BRIEF` | 10 | Cap low-priority items in brief |
| `INTEL_CACHE_TTL_HOURS` | 24 | Intelligence cache lifetime |

## Output Format

### Daily Brief (generated by lead agent)

```
## Engineering Brief — 2026-02-17

### Critical (act now)
{0-2 items max}

### Attention Needed
{3-5 prioritized items}

### Healthy
{What's going well}

### Metrics
- Tech debt score: {N} ({trend})
- Test coverage: {%}
- Open findings: {count by severity}

### Recommendations
{1-2 strategic suggestions}
```

### Individual Agent Reports

Each agent produces an `AgentReport` containing:
- Timestamped findings with severity, file location, and recommendations
- Metrics (coverage %, finding counts, costs, etc.)
- Intelligence notes (what external data informed the scan)
- Learning updates (attention weight changes, trend observations)

## Recent System Additions (Feed / Keevs Engagement Engine)

**Agents should be aware of these new subsystems when scanning:**

- **`app/models/feed.py`** — 3 new tables: `feed_items`, `feed_item_interactions`, `contact_freshness_signals`. Feed items have dedup keys, lifecycle timestamps, and JSONB metadata. `contact_freshness_signals` uses SHA-256 `name_company_hash` for cross-user aggregation — privacy-sensitive.
- **`app/services/feed_generator.py`** — 6 generators producing feed items. Each generator queries the DB and creates items with SHA-256 dedup keys. Performance-sensitive: runs for ALL active users 3x daily. Watch for N+1 queries and missing indexes.
- **`app/tasks/feed_tasks.py`** — 3 Celery tasks: `generate_feed_all_users` (3x daily), `cleanup_expired_feed_items` (weekly), `send_smart_digest` (twice weekly). Uses async-to-sync bridge pattern (`_run_async`).
- **`app/api/feed.py`** — 8 endpoints. The `enrichment-response` endpoint writes to `contact_freshness_signals` AND updates `Contact.relationship_type` — cross-table write, test for consistency.
- **Frontend: `KeevsAvatar.jsx`, `FeedCard.jsx`, `KeevsBar.jsx`** — New components. `KeevsBar` fetches feed items on every route change — watch for excessive API calls. `FeedCard` handles inline enrichment responses.
- **`OnboardingPage.jsx`** — Now 10 steps (was 9). Step 8 is "Meet Keevs". Step numbering is important — step 3 is conditionally skipped for job seekers.
- **`Layout.jsx`** — Polls `feed/count` every 2 minutes for badge. `KeevsBar` rendered above `<Outlet>`.
- **`CoachPage.jsx`** — Feed section above chat. Loads top 5 feed items on mount.
- **Outcome attribution** — `Application.source_type` now populated (own_network | manual). `UsageLog` has `session_id` and `event_source` columns.

## Recent System Additions (Infrastructure & Hardening)

**Agents should be aware of these subsystems when scanning:**

- **Unified Memory Service** — `agents/shared/memory_bridge.py` provides sync `AgentMemory` class for agent teams. Postgres `memories` table with tsvector GIN index (BM25 keyword search) + Qdrant `warmpath_memory` collection (vector semantic search). Hybrid retrieval with temporal decay + MMR re-ranking. Feature-flagged: `MEMORY_SERVICE_ENABLED`. CLI: `python3 -m agents.memory search/save/recent/stats`.
- **MCP Server (`mcp_server/`)** — 19 tools for querying live backend state and managing agent memory. PrivacyGuard enforcement on all SQL. stdio (local) + SSE (deployed) transports. Deployed as Railway service at `https://mcp-server-production-23a9.up.railway.app/sse`, `SERVICE_ROLE=mcp`. DNS rebinding protection with Railway host whitelist. Now included in architect scan targets.
- **Vector Search** — Qdrant + OpenAI embeddings for semantic search across contacts, marketplace listings, and job matching. Feature-flagged: `VECTOR_SEARCH_ENABLED`. Single unified collection with `doc_type` filter, deterministic UUID5 point IDs, combined scoring (vector x 50 + warm x 0.5). Daily full reindex + incremental sync triggers. Graceful fallback to keyword search when Qdrant is unavailable.
- **Auto-repair pipeline (`agents/shared/repair.py`)** — Auto-fixes ruff lint+format findings, gates on pytest, creates PR for human review. `repair_status` field on `Finding` dataclass. Safety guardrails: only ruff commands, branch isolation, daily dedup marker, revert on test failure, never auto-merges. Repair results surface in daily Telegram brief.
- **W&B Weave AI observability** — `@weave.op()` on all 7 AI services (intro drafter, candidate blurb, AI matcher, CSV cleaner, provider pool, NLP search, resume parser). Conditional init gated on `AI_MOCK_MODE=false` + `WANDB_API_KEY`. PII stripped from AI prompts (contact names replaced with placeholders). PII redaction layer on trace logs. Kill switch: remove `WANDB_API_KEY`.
- **Multi-provider CSV Pipeline V2** — 4-stage Redis Streams pipeline (parse/clean/import/score) with 4 AI providers (Gemini, Claude, OpenAI, Groq). Deterministic post-processing. Feature-flagged: `CSV_PIPELINE_V2`. Watch for provider failover correctness and stream consumer lag.
- **Phase 0-4 red-team hardening** — Credit abuse guardrails (Phase 0: non-admin credit minting blocked, `MANUAL_INTRO_CREDIT_AWARD_ENABLED` kill switch). Truthful onboarding/search gates (Phase 1: mandatory target role, CSV upload, work history). Canonical privacy copy contract (Phase 2: `docs/privacy-copy-phrasebook.md`). Adaptive marketplace scope activation (Phase 3: `warmpath_search_scope_v1` experiment, auto-scope with credit affordability check). Anti-fraud velocity guardrails (Phase 4: daily rate limits on intro requests/approvals/confirms, `velocity_limit_hit` audit events, 429 responses via `RateLimitError`).
