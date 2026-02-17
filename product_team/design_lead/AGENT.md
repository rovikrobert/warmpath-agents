# Design Lead Agent

## Role
Design system audit, color/spacing/typography consistency, Tailwind analysis.

## Responsibilities
1. **Color Consistency** — Extract all color values, check hardcoded hex vs Tailwind classes
2. **Spacing Consistency** — Audit Tailwind spacing class usage patterns
3. **Typography** — Count unique text sizes/weights, check for off-system usage
4. **Component Patterns** — Button variants, card patterns, modal patterns
5. **Dark Mode Readiness** — Check for dark: prefixes
6. **Animation/Transition Usage** — Count transition/animate classes
7. **Design System Score** — % of styling via Tailwind vs inline/hardcoded

## How It Works
- Reads `frontend/src/**/*.jsx` and CSS files using regex pattern matching
- Extracts Tailwind class usage, inline styles, hardcoded colors
- Computes design system compliance score
- Does NOT render the UI — static analysis only

## Key Metrics
- `design_system_score`: % of styling via Tailwind vs inline (target: 90%+)
- `unique_hardcoded_colors`: Count of hex colors (target: <=12)
- `unique_text_sizes`: Count of distinct text sizes (target: <=8)
- `dark_mode_coverage`: % of files with dark: prefixes

## CLI Usage
```bash
python -m product_team.orchestrator --agent design_lead
```

## Output
`ProductTeamReport` with findings (design_system) and DesignFindings (color, spacing, typography, etc.).
