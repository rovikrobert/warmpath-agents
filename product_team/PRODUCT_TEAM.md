# Product Team

The product team is the **user's voice** in WarmPath's automated engineering ecosystem. It scans the frontend codebase for UX/accessibility/design issues, audits feature coverage, generates research frameworks, and coordinates product decisions. All reports flow through CoS into founder briefs.

## Architecture

```
product_team/
  shared/
    config.py          — Paths, personas, RICE weights, learning constants
    privacy_guard.py   — Research privacy enforcement (no PII in outputs)
    report.py          — ProductInsight, UXFinding, DesignFinding, ProductTeamReport
    learning.py        — ProductLearningState (same API as DataLearningState)
    intelligence.py    — 12 product-specific intel categories
  user_researcher/     — Journey mapping, persona management, research frameworks
  product_manager/     — Feature mapping, API-frontend coverage, acceptance criteria
  ux_lead/             — Accessibility, loading/error/empty states, responsive, heuristic eval
  design_lead/         — Color/spacing/typography, Tailwind analysis, design system score
  product_lead/        — Coordination, daily/weekly/monthly briefs, cross-team requests
  orchestrator.py      — CLI entry point
  reports/             — Agent output (JSON, gitignored)
```

## Agents

### UserResearcher
Scans `frontend/src/pages/*.jsx` and persona definitions to:
- Map user journeys for job seekers and network holders
- Identify journey gaps (missing pages per persona)
- Check supply/demand feature balance
- Catalog intelligence sources for user research

### ProductManager
Scans `app/api/*.py`, `tests/`, and `frontend/src/pages/*.jsx` to:
- Map API endpoints to frontend pages (feature coverage)
- Detect orphan APIs (no frontend consumer) and orphan pages (no API backing)
- Audit test coverage per API module
- Identify integration gaps

### UXLead
Scans `frontend/src/**/*.jsx` for:
- Accessibility: aria-*, role, alt text, button labels
- Loading states: spinner/skeleton/loading patterns
- Error states: error handling and display
- Empty states: "no data" messaging
- Form validation: inline error patterns
- Responsive design: Tailwind responsive prefixes
- Privacy indicators: vault/consent references in UI

### DesignLead
Scans `frontend/src/**/*.jsx` and CSS files for:
- Color consistency: hardcoded hex vs Tailwind classes
- Spacing consistency: Tailwind spacing scale compliance
- Typography: text size and weight usage
- Component patterns: buttons, cards, modals
- Dark mode readiness: dark: prefix coverage
- Design system score: % styling via Tailwind vs inline

### ProductLead
Aggregates sub-agent reports to produce:
- **Daily brief**: scorecard, attention items, insights, learning updates
- **Weekly report**: readiness scorecard, category breakdown, intelligence status
- **Monthly review**: maturity assessment, persona refresh, roadmap
- **Cross-team requests**: escalations to Engineering and Data teams

## Privacy Guard

The product team's privacy guard validates research outputs (not SQL queries):
- No PII patterns (emails, phones, LinkedIn URLs) in findings
- No PII column references in research output
- Forbidden research actions (scraping, exporting PII, external posting)
- Same `PrivacyViolation` exception pattern as data team

## Learning System

`ProductLearningState` mirrors `DataLearningState` exactly:
- Finding recording + recurring pattern detection (5+/10+ thresholds)
- Fix effectiveness tracking within 30-day window
- Attention weights (EMA + time decay) for hot spot detection
- Severity calibration and tool accuracy tracking
- Health trajectory analysis
- Meta-learning report generation

State stored in `product_team/{agent}/state.json` (gitignored).

## Intelligence

12 product-specific categories grouped by agent:
- **UserResearcher** (6): user_forums, career_platforms, referral_culture, research_methods, persona_evolution, competitor_features
- **DesignLead** (2): design_systems, design_trends
- **UXLead** (2): accessibility_standards, ux_patterns
- **ProductManager** (2): pm_frameworks, marketplace_dynamics

Cache stored in `product_team/shared/intel_cache.json` (gitignored).

## CoS Integration

- Product team registered in `cos_config.py` with `active: True`
- Reports loaded by `cos_agent.py:_load_reports()` from `product_team/reports/`
- Team reliability tracked in `cos_learning.py`
- Product findings appear in `synthesize_status()` output
- 5 product categories in `CATEGORY_OUTCOME_MAP` for business alignment

## CLI Usage

```bash
# Full scan (all agents)
python -m product_team.orchestrator --all

# Single agent
python -m product_team.orchestrator --agent ux_lead

# Briefs (from cached reports)
python -m product_team.orchestrator --daily-brief
python -m product_team.orchestrator --weekly
python -m product_team.orchestrator --monthly

# Intelligence
python -m product_team.orchestrator --intel
python -m product_team.orchestrator --intel-report
python -m product_team.orchestrator --research-agenda

# Learning
python -m product_team.orchestrator --learning-report
```

## Tests

```bash
pytest tests/test_product_team.py -v
```

## Recent Changes: Feed System & Keevs AI Coach

**Product team agents should be aware of these new user-facing features:**

- **Keevs AI Coach Identity** — The AI coach now has a visual identity (`KeevsAvatar.jsx`) and is introduced during onboarding (step 8 of 10: "Meet Keevs"). Keevs appears across the app via `KeevsBar` (contextual nudge bar on every page) and the coach page header.
- **Proactive Engagement Feed** — Background-generated personalized insights (job alerts, enrichment prompts, follow-up nudges, marketplace signals, outcome checks, network insights). Surfaced in-app on coach page and via KeevsBar, plus twice-weekly smart digest email.
- **Enrichment Prompts** — Feed items that ask users to categorize their contacts (relationship type, would_refer). Inline response buttons in `FeedCard`. This is a key data collection mechanism — every response enriches the trust graph.
- **Feed Badge** — Unseen count shown in sidebar nav (desktop) and bottom tab bar (mobile). Refreshes every 2 minutes.
- **10-Step Onboarding** — Was 9 steps, now 10. Step 8 is "Meet Keevs" (between privacy explainer and CSV upload). Product team should track completion rates per step.
- **Outcome Attribution** — Applications now track `source_type` (own_network | manual). Future: marketplace, external. This enables conversion funnel analysis by acquisition channel.

## Recent Changes: Red-Team Hardening & Growth

**Product team agents should be aware of these platform hardening and growth changes:**

- **Phase 0: Credit Abuse Guardrails** — Non-admin direct credit minting via `/credits/purchase` blocked with audit logging. Manual LinkedIn `confirm-sent` credit awards behind `MANUAL_INTRO_CREDIT_AWARD_ENABLED` kill switch (deferred in production). Manual confirm path made idempotent.
- **Phase 1: Onboarding Gates** — Target role required before job-preferences step, CSV upload required to complete onboarding, at least one work-history entry required before finalization. Find Referrals blocks search when target role is missing with guided setup messaging.
- **Phase 2: Canonical Privacy Copy** — Reusable `MarketplaceVisibilityExplainer` component and `docs/privacy-copy-phrasebook.md` as canonical copy source. Standardized marketplace visibility wording across onboarding, join, marketplace overview, and privacy policy.
- **Phase 3: Adaptive Scope Experiment** — `warmpath_search_scope_v1` A/B experiment auto-selects marketplace scope when own-network coverage is low (< 20%), respects credit affordability. Scope conversion telemetry events for funnel analysis.
- **Phase 4: Velocity Rate Limits** — Daily caps on intro requests, approvals, and manual confirmations. User-friendly 429 copy in search, intro request, and manual confirm flows. `velocity_limit_hit` audit logging.
- **Growth Entry Points** — Dual-purpose `/join` page (intent-based for job seekers vs network holders), referral codes, public intro review page (token-gated, 90-day TTL, audit-logged, rate-limited).
- **Playwright E2E Smoke Harness** — `frontend/e2e/find-referrals-smoke.spec.ts` validates low-credit, low-coverage, and rate-limit UX paths with dev-only auth bypass.
