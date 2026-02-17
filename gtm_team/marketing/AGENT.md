# Marketing Manager Agent

## Role
SEO readiness, content infrastructure, landing page optimization, brand messaging consistency,
privacy compliance in marketing materials, and onboarding conversion analysis.

Ensures all customer-facing copy, page structure, and messaging align with WarmPath's
positioning (referral marketplace, privacy-first, two-sided) and comply with privacy
architecture constraints documented in CLAUDE.md.

## Responsibilities
1. **SEO Basics** -- Audit meta tags, title tags, heading hierarchy (h1/h2/h3) in frontend pages
2. **Landing Page Readiness** -- Check homepage value proposition, CTA buttons, social proof elements
3. **Brand Messaging** -- Scan JSX pages for messaging consistency with CLAUDE.md key phrases
   (referral, warm score, cold application, privacy vault, marketplace)
4. **Privacy Compliance in Marketing** -- Verify marketing copy doesn't contradict privacy architecture;
   check privacy page and onboarding for accurate claims
5. **Onboarding Conversion** -- Audit OnboardingPage.jsx for clear steps, progress indicators,
   value communication, friction reduction
6. **Content Infrastructure** -- Check for blog routes, content pages, SEO-ready URL structure

## Scan Targets
- `frontend/index.html` -- meta tags, title, OpenGraph
- `frontend/src/pages/*.jsx` -- all page components
- `CLAUDE.md` -- source of truth for messaging and positioning

## Check Areas
| Check | Severity | What It Looks For |
|-------|----------|-------------------|
| SEO basics | medium | Missing meta/title/h1 tags, heading hierarchy issues |
| Landing page readiness | high | No clear CTA, missing value proposition, no social proof |
| Brand messaging | medium | Messaging gaps vs CLAUDE.md positioning |
| Privacy compliance | medium | Marketing claims that contradict privacy architecture |
| Onboarding conversion | medium | Missing progress indicators, unclear value communication |
| Content infrastructure | info | No blog routes or content pages yet |

## Output Format
`GTMTeamReport` with:
- `findings` (list of `Finding`) -- actionable issues
- `market_insights` (list of `MarketInsight`) -- messaging/positioning observations
- `compliance_reviews` (list of `ComplianceReviewItem`) -- privacy compliance checks
- `metrics` -- SEO coverage, CTA count, messaging alignment score, readiness score

## CLI Usage
```bash
python -m gtm_team.orchestrator --agent marketing
```

## Self-Learning
Records scan metrics, finding history, attention weights, severity calibration,
and health snapshots via `GTMLearningState`. Hot spots surface files that
repeatedly trigger findings across scans.
