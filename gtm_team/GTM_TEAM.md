# GTM Team

The GTM team is WarmPath's **go-to-market intelligence engine**. It scans strategy documents, competitive landscape, pricing benchmarks, marketing channels, and partnership opportunities to produce founder-facing GTM briefs. All reports flow through CoS into founder briefs.

## Mission & Outcomes

**Mission:** Ensure WarmPath launches with validated positioning, defensible pricing, ready channels, and activated partnerships -- reducing time-to-traction and avoiding costly GTM pivots.

**Key outcomes:**
- Competitive positioning validated against 8 tracked competitors
- Pricing validated with 10+ SaaS/marketplace benchmarks
- Content pipeline of 20+ SEO articles ready for launch
- 15+ active partnership conversations (bootcamps, universities, career coaches)
- 50+ identified network holder recruitment targets for supply seeding
- Geographic strategy aligned with Singapore-first, SEA expansion playbook

## Architecture

```
gtm_team/
  shared/
    config.py            -- Paths, agent names, personas, KPI targets, thresholds
    privacy_guard.py     -- Marketing output privacy enforcement (no PII, no false claims)
    report.py            -- MarketInsight, PartnershipOpportunity, PricingExperiment, GTMTeamReport
    learning.py          -- GTMLearningState (same API as DataLearningState/ProductLearningState)
    intelligence.py      -- 16 GTM-specific intel categories
    strategy_context.py  -- Strategy doc loader + content extractors (pricing, competitive, personas)
  stratops/              -- Competitive intelligence, market analysis, geographic strategy
  monetization/          -- Pricing validation, credit economy, experiments, conversion benchmarks
  marketing/             -- Content pipeline, SEO, landing pages, compliance, channel readiness
  partnerships/          -- Partnership pipeline, bootcamps, universities, community, co-marketing
  gtm_lead/              -- Coordination, daily/weekly/monthly briefs, cross-team requests
  orchestrator.py        -- CLI entry point
  reports/               -- Agent output (JSON, gitignored)
  cross_team_requests/   -- Cross-team escalation queue
```

## Agents

### StratOps (Strategic Operations)
Scans strategy documents and competitive landscape to:
- Track 8 competitors (The Swarm, LinkedIn, Handshake, Blind, Refer.me, Teamable, Drafted, Lunchclub)
- Validate positioning and differentiation strength
- Assess market sizing assumptions (TAM/SAM/SOM)
- Monitor geographic strategy alignment (Singapore-first, SEA expansion)
- Flag strategy divergences when recommendations conflict with docs

### Monetization
Scans pricing strategy and credit economy to:
- Validate pricing tiers ($20-30/month demand side, free supply side)
- Benchmark against SaaS/marketplace comparables
- Design and track pricing experiments
- Audit credit economy integrity (non-transferable, 12-month expiry, no cash-out)
- Monitor conversion funnel assumptions

### Marketing
Scans frontend, strategy docs, and content pipeline to:
- Audit landing page readiness (homepage + company-specific pages)
- Track SEO content pipeline depth
- Validate marketing compliance (no false privacy claims, no PII in marketing)
- Assess channel readiness (content, community, referral programs)
- Monitor marketing regulation changes across operating jurisdictions

### Partnerships
Scans partnership landscape and strategy docs to:
- Track partnership pipeline by stage (identified -> outreach -> conversation -> proposal -> negotiation -> signed)
- Identify bootcamp partnership opportunities (placement rate uplift value prop)
- Identify university career services partnerships
- Assess community building opportunities
- Track legal review status for partnership agreements

### GTM Lead
Aggregates sub-agent reports to produce:
- **Daily brief**: active initiatives, decisions needed, GTM metrics, competitive moves, recommendations
- **Weekly report**: channel assessment, competitive landscape, pricing validation, partnership pipeline
- **Monthly review**: competitive positioning, market sizing validation, strategy evolution, expansion readiness
- **Cross-team requests**: escalations to engineering, data, and finance teams

## Privacy Guard

The GTM team's privacy guard validates all marketing and commercial outputs:
- No PII patterns (emails, phones, LinkedIn URLs) in findings or marketing copy
- No PII column references from the vault model
- No false privacy/security claims in marketing materials
- No forbidden marketing actions (exposing user data, cross-vault claims, purchased email lists)
- Same `PrivacyViolation` exception pattern as data team and product team

## Learning System

`GTMLearningState` mirrors `DataLearningState` and `ProductLearningState` exactly:
- Finding + insight recording with recurring pattern detection (5+/10+ thresholds)
- Fix effectiveness tracking within 30-day window
- Attention weights (EMA + time decay) for hot spot detection
- Severity calibration and tool accuracy tracking
- Health trajectory analysis
- KPI trend analysis
- Meta-learning report generation

State stored in `gtm_team/{agent}/state.json` (gitignored).

## Intelligence

16 GTM-specific categories grouped by agent relevance:

**Competitive Landscape (4):**
- `competitor_products` -- Feature launches, product changes, new entrants
- `competitor_funding` -- Funding rounds, valuations
- `competitor_pricing` -- Pricing changes, tier structures
- `competitor_hiring` -- Hiring patterns as strategy signals

**Market Data (2):**
- `job_market_stats` -- Job market statistics affecting demand-side positioning
- `referral_effectiveness` -- Referral conversion data for content marketing

**Pricing Benchmarks (2):**
- `saas_pricing_benchmarks` -- SaaS pricing, conversion rates, LTV/CAC
- `marketplace_economics` -- Take rates, liquidity, pricing evolution

**Channel Performance (2):**
- `seo_trends` -- SEO trends, keyword opportunities
- `content_benchmarks` -- Content marketing format effectiveness

**Community & Partnerships (3):**
- `community_building` -- Community strategies, engagement patterns
- `bootcamp_market` -- Bootcamp landscape, placement rates, partnership models
- `university_career_services` -- Career services trends, partnership opportunities

**APAC Market (2):**
- `sea_tech_ecosystem` -- Southeast Asia tech ecosystem dynamics
- `sea_job_market` -- SEA job market trends, salary benchmarks

**Marketing Compliance (1):**
- `marketing_regulations` -- FTC, PDPC Singapore, ICO EU marketing guidance

Cache stored in `gtm_team/shared/intel_cache.json` (gitignored).

## CoS Integration

- GTM team registered in CoS config with `active: True`
- Reports loaded by `cos_agent.py:_load_reports()` from `gtm_team/reports/`
- Team reliability tracked in `cos_learning.py`
- GTM findings appear in `synthesize_status()` output
- GTM categories in `CATEGORY_OUTCOME_MAP` for business alignment
- Cross-team requests surfaced in CoS daily brief

## Business Outcome Mapping

| GTM Category | Business Outcome |
|--------------|------------------|
| Competitive positioning | Market differentiation confidence |
| Pricing validation | Revenue model confidence |
| Channel readiness | Time-to-first-revenue |
| Partnership pipeline | Supply seeding velocity |
| Content pipeline | Organic acquisition readiness |
| Geographic strategy | Expansion optionality |

## KPI Targets

| KPI | Target | Unit | Description |
|-----|--------|------|-------------|
| gtm_readiness | 1.0 | ratio | Composite across positioning + pricing + channels + partnerships |
| competitive_freshness | 7 | days | Days since last competitive scan |
| pricing_benchmarks | 10 | count | Comparable benchmarks analysed |
| content_pipeline_depth | 20 | count | SEO articles drafted and ready |
| landing_page_readiness | 6 | count | Homepage + 5 company-specific pages |
| partnership_pipeline | 15 | count | Active partnership conversations |
| supply_side_targets | 50 | count | Identified network holder recruitment targets |

## Privacy Constraints for GTM

The GTM team operates under strict privacy constraints because marketing is the highest-risk surface for privacy violations:

1. **No PII in marketing materials** -- Never reference real user names, emails, or connection data
2. **No false privacy claims** -- Marketing copy must accurately represent vault model and anonymization
3. **No cross-vault claims** -- Never imply we can see across users' networks
4. **Suppression list respected** -- Marketing targeting must check suppression list
5. **Jurisdiction compliance** -- Marketing must comply with PDPA (Singapore), GDPR (EU), CCPA (US)
6. **Referral bonus framing** -- Never imply WarmPath pays referral bonuses. Currently they flow employer -> employee; do not promise this arrangement is permanent

## Cross-Team Coordination

| Trigger | Target Team | Request |
|---------|-------------|---------|
| Critical GTM findings | Engineering | Urgent fixes needed |
| Blocked compliance reviews | Finance (Legal) | Legal review required |
| Pending compliance reviews | Finance (Legal) | Legal review pending |
| Active pricing experiments | Engineering | Feature-flag or billing implementation |
| Missing funnel metrics | Data | Funnel conversion metrics for channel attribution |
| UX issues in landing pages | Product | Landing page UX improvements |

## CLI Usage

```bash
# Full scan (all agents)
python -m gtm_team.orchestrator --all

# Single agent
python -m gtm_team.orchestrator --agent stratops

# Briefs (from cached reports)
python -m gtm_team.orchestrator --daily-brief
python -m gtm_team.orchestrator --weekly
python -m gtm_team.orchestrator --monthly

# Intelligence
python -m gtm_team.orchestrator --intel
python -m gtm_team.orchestrator --intel-report
python -m gtm_team.orchestrator --research-agenda

# Learning
python -m gtm_team.orchestrator --learning-report

# KPI tracking
python -m gtm_team.orchestrator --kpi-check
```

## Recent Changes: Smart Digest & Feed Engagement

- **Smart Digest Email** — New email type `smart_digest` in `email_engagement.py`. Sends top 3 unseen feed items per active user via Resend. Runs Mon + Thu 8:30 AM UTC via Celery Beat (`feed-smart-digest-mon`, `feed-smart-digest-thu`). Deduped via `email_campaign_logs`. Replaces basic weekly digest with personalized, feed-powered content.
- **Feed System** — 6 feed generators produce personalized engagement items 3x daily. Key engagement metrics to track: feed item view rate, click-through rate, enrichment prompt response rate, smart digest open rate.
- **Keevs Branding** — AI coach has a visual identity now. Smart digest emails come "from Keevs" with subject lines like "Keevs found 3 new insights for you." This is the push-based engagement the GTM team should leverage in messaging.
- **Outcome Attribution** — `Application.source_type` tracks how users found their leads. GTM team should monitor conversion rates by source type (own_network vs manual vs marketplace).
