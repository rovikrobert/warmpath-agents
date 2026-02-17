# ModelEngineer Agent

## Role
Warm score calibration audit, cultural context evaluation, A/B framework readiness.

## Responsibilities
1. **Warm Score Analysis** — Extract weights, bonuses, penalties from warm_scorer.py
2. **Outcome Tracking** — Check if warm_score can be correlated with referral outcomes
3. **Cultural Context** — Analyze approach styles and adaptation logic in ai_matcher.py
4. **AI Token Usage** — Estimate prompt sizes and check for cost awareness
5. **A/B Testing** — Check for experiment infrastructure (tables, variant columns)

## How It Works
- Reads `app/services/warm_scorer.py` for WEIGHT_* constants and scoring factors
- Reads `app/models/match_result.py` for user_feedback and score_factors columns
- Reads `app/services/ai_matcher.py` for cultural context variants
- Searches all model files for experiment/variant table patterns
- Does NOT connect to a live database or call any APIs

## Warm Score Algorithm (from codebase)
- 4 components: recency (35%), relationship (30%), role (20%), tenure (15%)
- Referral likelihood: high (>=70), medium (45-69), low (<45)
- Key differentiator: peers/ICs score higher than C-suite for referrals

## Key Metrics
- `warm_score_features_count`: Total scoring factors detected
- `warm_score_weights`: Extracted weight constants
- `cultural_context_variants`: Approach styles found
- `outcome_tracking_ready`: Whether A/B infrastructure exists

## CLI Usage
```bash
python -m data_team.orchestrator --agent model_engineer
```

## Output
`DataTeamReport` with findings (model_calibration) and insights (algorithm assessment).
