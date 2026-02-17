# UX Lead Agent

## Role
Accessibility audit, flow analysis, error/loading/empty state checks, heuristic evaluation.

## Responsibilities
1. **Accessibility** — Audit aria-* attributes, role attributes, alt text, button labels
2. **Loading States** — Check for spinner/skeleton/loading patterns in page components
3. **Error States** — Verify error handling, error display, try/catch blocks
4. **Empty States** — Check "no data" / "no results" messaging
5. **Form Validation** — Inline error patterns, required field indicators
6. **Responsive Design** — Tailwind responsive prefixes (sm:, md:, lg:, xl:)
7. **Privacy Indicators** — References to vault, private, anonymous, consent in UI
8. **Flow Efficiency** — Estimate clicks to complete critical paths

## How It Works
- Reads `frontend/src/**/*.jsx` using regex pattern matching
- Counts accessibility attributes, loading patterns, error handling
- Computes a weighted UX health score based on heuristic coverage
- Does NOT run the frontend or browser — static analysis only

## Key Metrics
- `ux_health_score`: Weighted composite of all heuristic scores (0-100)
- `accessibility_aria_coverage`: % of JSX files with aria-* attributes
- `loading_state_coverage`: % of pages with loading state patterns
- `error_state_coverage`: % of pages with error handling

## CLI Usage
```bash
python -m product_team.orchestrator --agent ux_lead
```

## Output
`ProductTeamReport` with findings (ux_quality) and UXFindings (accessibility, loading_state, error_state, etc.).
