from __future__ import annotations

from dataclasses import dataclass

from app.models import BlastRadius, PolicyView


@dataclass(frozen=True)
class CheckPlan:
    """Blast-radius-aware check schedule for one evaluation."""

    run_injection: bool
    run_pii_input: bool
    run_pii_output: bool
    run_grounding: bool
    run_numeric: bool
    run_disagreement: bool
    run_cascade: bool
    disagreement_sample_budget: int


def build_check_plan(policy: PolicyView, radius: BlastRadius, action: str) -> CheckPlan:
    """Resolve which checks run and how hard, per policy profile and blast radius."""
    enabled = set(policy.checks)
    sample_budget = policy.disagreement_samples.get(radius.value, 0)

    # Cost-aware routing (proposal §6a): lighter tiers skip expensive verification.
    run_grounding = "grounding" in enabled and radius != BlastRadius.R0
    run_numeric = "numeric" in enabled and (
        radius == BlastRadius.R3 or (radius == BlastRadius.R2 and action == "issue_refund")
    )
    run_disagreement = "disagreement" in enabled and sample_budget > 0
    run_cascade = "cascade" in enabled and radius in (BlastRadius.R2, BlastRadius.R3)

    # High-impact profiles still ground read-only policy answers (demo scenario 3).
    if "grounding" in enabled and radius == BlastRadius.R0 and policy.profile in ("refund_agent", "internal_copilot"):
        run_grounding = True

    # Support-bot R0 still grounds delivery/policy FAQ answers (demo scenario 1).
    if "grounding" in enabled and radius == BlastRadius.R0 and policy.profile == "support_bot":
        run_grounding = True

    return CheckPlan(
        run_injection="injection" in enabled,
        run_pii_input="pii" in enabled,
        run_pii_output="pii" in enabled,
        run_grounding=run_grounding,
        run_numeric=run_numeric,
        run_disagreement=run_disagreement,
        run_cascade=run_cascade,
        disagreement_sample_budget=sample_budget,
    )
