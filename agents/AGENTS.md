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
