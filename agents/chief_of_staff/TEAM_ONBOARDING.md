# Team Onboarding Checklist

Reusable protocol for adding any new team or agent to the CoS ecosystem.
Every addition must complete all 10 items before merging.

## Checklist

### 1. Privacy Guard Compliance
- [ ] All SQL queries validated by `privacy_guard.py` (or equivalent)
- [ ] All 10 Privy categories addressed: vault_isolation, encryption, suppression, anonymization, consent, retention, dsar, pii_leak, audit_immutability, info_leak
- [ ] PrivacyViolation is a hard fail (not a warning)

### 2. Business Outcome Alignment
- [ ] Finding categories added to `CATEGORY_OUTCOME_MAP` in `agents/shared/business_outcomes.py`
- [ ] Impact templates added to `_IMPACT_TEMPLATES` for critical categories
- [ ] Categories map to at least one of: help_job_seekers, network_builders, billion_dollar, cost_efficiency

### 3. Report Schema Compatibility
- [ ] Agent reports use `Finding` from `agents.shared.report` (cross-compatible)
- [ ] Report class has `to_agent_report()` method (or is already `AgentReport`)
- [ ] Reports serialize/deserialize cleanly via JSON

### 4. Cost Tracking Compatibility
- [ ] Report exposes `scan_duration_seconds` field (same name as `AgentReport`)
- [ ] Cost estimation flows through `cost_tracker.py:get_team_cost_summary()` automatically

### 5. Team Registry Activation
- [ ] Team added to `COS_CONFIG["teams"]` in `agents/chief_of_staff/cos_config.py`
- [ ] `active: True` and `report_dir` set to the team's reports directory
- [ ] Budget entry added to `COS_CONFIG["cost_budget"]`

### 6. Team Reliability Baseline
- [ ] Team pre-registered in `agents/chief_of_staff/cos_learning.py:_default_state()`
- [ ] `update_team_reliability(team_name, reports)` works for the new team

### 7. Cross-Team Request Protocol
- [ ] If applicable: agent emits `cross_team_requests` in report
- [ ] Requests follow `CrossTeamRequest` schema: `{team, request, urgency, blocking}`
- [ ] Requests surface in CoS daily brief's "Decisions Needed" section

### 8. Founder Brief Integration
- [ ] `cos_agent.py:_load_reports()` reads from the team's report directory
- [ ] Run `python3 -m agents.orchestrator --cos-daily` and verify team findings appear
- [ ] Run `python3 -m agents.orchestrator --cos-status` and verify team section appears

### 9. Tests Pass
- [ ] All existing tests pass (`pytest -n auto`)
- [ ] New team has dedicated test file in `tests/`
- [ ] Privacy guard tests cover all relevant Privy categories
- [ ] CoS integration tests verify config activation and business outcome mapping

### 10. Documentation
- [ ] Each agent has an `AGENT.md` specification
- [ ] Team has a master documentation file (e.g., `DATA_TEAM.md`)
- [ ] CLAUDE.md updated with team status and test count

## Validation Commands

```bash
# Run all tests (zero regressions)
pytest -n auto

# Run team-specific tests
pytest tests/test_data_team.py -v

# Verify CoS integration
python3 -m agents.orchestrator --cos-status
python3 -m agents.orchestrator --cos-daily

# Run the new team
python3 -m data_team.orchestrator --all
```

## When to Use This Checklist

Any time a new team, agent cluster, or significant agent addition is proposed:
1. Author fills out the checklist in the PR description
2. CoS review verifies each item
3. All 10 items must be checked before merge
