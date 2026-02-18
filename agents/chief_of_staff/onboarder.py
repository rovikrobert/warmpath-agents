"""Team onboarding — validate team specs and generate scaffolding."""

from __future__ import annotations

import json

from agents.shared.business_outcomes import OUTCOME_PRIORITY
from agents.shared.config import AGENTS_DIR

_TEMPLATE_PATH = AGENTS_DIR / "templates" / "team_template.json"

_REQUIRED_TEAM_FIELDS = {"name", "lead_agent", "purpose", "business_outcomes_served"}
_REQUIRED_AGENT_FIELDS = {"name", "role"}
_REQUIRED_REPORTING_FIELDS = {"cadence", "format", "lead_submits_to"}
_REQUIRED_BUDGET_FIELDS = {"max_daily_tokens", "alert_threshold_pct"}


def load_template() -> dict:
    """Load the team onboarding template."""
    if _TEMPLATE_PATH.exists():
        return json.loads(_TEMPLATE_PATH.read_text())
    return {}


def validate_team_spec(spec: dict) -> list[str]:
    """Validate a team onboarding spec against required fields.

    Returns a list of validation errors (empty = valid).
    """
    errors: list[str] = []

    # Team section
    team = spec.get("team", {})
    missing_team = _REQUIRED_TEAM_FIELDS - set(team.keys())
    if missing_team:
        errors.append(f"Missing team fields: {', '.join(sorted(missing_team))}")

    # Check team.name is non-empty
    if not team.get("name"):
        errors.append("team.name must not be empty")

    # Check team.lead_agent is non-empty
    if not team.get("lead_agent"):
        errors.append("team.lead_agent must not be empty")

    # Check outcomes map to valid business outcomes
    outcomes = team.get("business_outcomes_served", [])
    if not outcomes:
        errors.append("team.business_outcomes_served must have at least one outcome")
    for outcome in outcomes:
        if outcome not in OUTCOME_PRIORITY:
            errors.append(
                f"Unknown business outcome: '{outcome}'. "
                f"Valid: {', '.join(OUTCOME_PRIORITY)}"
            )

    # Agents section
    agents = spec.get("agents", [])
    if not agents:
        errors.append("At least one agent must be defined")
    for i, agent in enumerate(agents):
        missing_agent = _REQUIRED_AGENT_FIELDS - set(agent.keys())
        if missing_agent:
            errors.append(
                f"Agent [{i}] missing fields: {', '.join(sorted(missing_agent))}"
            )

    # Reporting section
    reporting = spec.get("reporting", {})
    missing_reporting = _REQUIRED_REPORTING_FIELDS - set(reporting.keys())
    if missing_reporting:
        errors.append(
            f"Missing reporting fields: {', '.join(sorted(missing_reporting))}"
        )

    # Cost budget section
    budget = spec.get("cost_budget", {})
    missing_budget = _REQUIRED_BUDGET_FIELDS - set(budget.keys())
    if missing_budget:
        errors.append(
            f"Missing cost_budget fields: {', '.join(sorted(missing_budget))}"
        )

    return errors


def generate_team_scaffold(spec: dict, *, dry_run: bool = True) -> list[str]:
    """Generate directory structure for a new team.

    Returns list of file paths that would be (or were) created.
    """
    team_name = spec.get("team", {}).get("name", "unknown")
    lead_name = spec.get("team", {}).get("lead_agent", "lead")
    purpose = spec.get("team", {}).get("purpose", "")

    team_dir = AGENTS_DIR / team_name
    files_to_create: list[str] = []

    # __init__.py
    init_path = team_dir / "__init__.py"
    files_to_create.append(str(init_path))

    # AGENT.md
    agent_md_path = team_dir / "AGENT.md"
    files_to_create.append(str(agent_md_path))

    # Lead agent skeleton
    lead_path = team_dir / f"{lead_name}.py"
    files_to_create.append(str(lead_path))

    if not dry_run:
        team_dir.mkdir(parents=True, exist_ok=True)

        init_path.write_text("")

        agent_md_content = (
            f"# {team_name.replace('_', ' ').title()} Team\n\n"
            f"**Purpose:** {purpose}\n\n"
            f"**Lead Agent:** {lead_name}\n"
        )
        agent_md_path.write_text(agent_md_content)

        lead_content = (
            f'"""Lead agent for the {team_name} team."""\n\n'
            f"from __future__ import annotations\n\n\n"
            f"def scan():\n"
            f'    """Run the {team_name} team scan."""\n'
            f"    raise NotImplementedError(\n"
            f'        "{team_name} team scan not yet implemented"\n'
            f"    )\n"
        )
        lead_path.write_text(lead_content)

    return files_to_create
