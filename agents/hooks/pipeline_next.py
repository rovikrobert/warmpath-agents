"""Pipeline automation hook — runs after any subagent completes.

Checks the pipeline queue and suggests the next step in the workflow.
Triggered by the SubagentStop hook in .claude/settings.json.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# Pipeline definitions: agent → next step(s)
PIPELINES: dict[str, list[dict]] = {
    "ship-feature": [
        {"agent": "architect", "step": "Technical review", "next": "eng-lead"},
        {"agent": "eng-lead", "step": "Implementation plan", "next": "implementation"},
        {"agent": "test-engineer", "step": "Test verification", "next": "security-reviewer"},
        {"agent": "security-reviewer", "step": "Security scan", "next": "privy"},
        {"agent": "privy", "step": "Privacy audit", "next": "product-lead"},
        {"agent": "product-lead", "step": "Acceptance review", "next": "complete"},
    ],
}

QUEUE_FILE = Path("agents/hooks/.pipeline_queue.json")


def load_queue() -> dict:
    """Load the current pipeline queue state."""
    if QUEUE_FILE.exists():
        return json.loads(QUEUE_FILE.read_text())
    return {"active_pipeline": None, "current_step": 0, "feature": None}


def save_queue(state: dict) -> None:
    """Persist the pipeline queue state."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(state, indent=2))


def suggest_next(completed_agent: str) -> str | None:
    """Given a completed agent, suggest the next pipeline step."""
    state = load_queue()

    if not state.get("active_pipeline"):
        return None

    pipeline = PIPELINES.get(state["active_pipeline"], [])
    current_step = state.get("current_step", 0)

    if current_step < len(pipeline):
        step = pipeline[current_step]
        if step["agent"] == completed_agent:
            # Move to next step
            state["current_step"] = current_step + 1
            save_queue(state)

            if step["next"] == "complete":
                return f"Pipeline '{state['active_pipeline']}' complete for '{state['feature']}'."

            next_step_idx = current_step + 1
            if next_step_idx < len(pipeline):
                next_info = pipeline[next_step_idx]
                return (
                    f"Step '{step['step']}' complete. "
                    f"Next: invoke @{next_info['agent']} for '{next_info['step']}'."
                )

    return None


def main() -> None:
    """Entry point for the hook."""
    # The hook receives the completed agent name as an argument
    if len(sys.argv) < 2:
        return

    completed_agent = sys.argv[1]
    suggestion = suggest_next(completed_agent)

    if suggestion:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] Pipeline: {suggestion}")


if __name__ == "__main__":
    main()
