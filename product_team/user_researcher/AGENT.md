# User Researcher Agent

## Role
Source catalog, persona management, research framework, journey mapping.

## Responsibilities
1. **Journey Mapping** — Catalog all user-facing pages and map job seeker / network holder journeys
2. **Journey Gaps** — Identify pages that should exist but don't for each persona
3. **Persona Balance** — Check feature investment balance between demand and supply side
4. **Research Sources** — Catalog available intelligence sources for user research
5. **Page Analysis** — Analyze page content for user-facing features and API integration

## How It Works
- Reads `frontend/src/pages/*.jsx` to map actual user-facing pages
- Cross-references with persona definitions in config (key_pages per persona)
- Identifies journey gaps where expected pages are missing
- Catalogs intelligence sources available for research
- Does NOT interact with users — static analysis and framework generation only

## Key Metrics
- `pages_found`: Number of user-facing pages detected
- `demand_page_coverage`: % of expected demand-side (job seeker) pages present
- `supply_page_coverage`: % of expected supply-side (network holder) pages present
- `supply_demand_page_ratio`: Balance of supply vs demand features

## CLI Usage
```bash
python -m product_team.orchestrator --agent user_researcher
```

## Output
`ProductTeamReport` with findings (user_research) and ProductInsights (journey, persona, strategy).
