"""Side-effect-free comparison of a request across policy contexts.

The simulator deliberately evaluates through :class:`ControlPlane` instead of
reimplementing its checks or decision rules.  Each candidate gets a private,
short-lived audit database so one candidate's session history cannot influence
another candidate and simulations never enter the production audit trail.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.audit import AuditRepository
from app.data_store import BusinessData
from app.models import Decision, EvaluationRequest
from app.pipeline import ControlPlane
from app.policy import PolicyStore
from app.provider import DeterministicDemoProvider, ModelProvider
from app.reason_codes import ReasonCode


class PolicySimulationRequest(BaseModel):
    """One evaluation and the policy contexts to compare.

    Empty profile or region lists mean "all configured values".  The
    ``use_case`` and ``region`` on ``evaluation`` are therefore only defaults
    when an explicit comparison dimension is not supplied.
    """

    evaluation: EvaluationRequest
    profiles: list[str] = Field(default_factory=list, max_length=10)
    regions: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("profiles", "regions")
    @classmethod
    def unique_non_empty_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("comparison values cannot be blank")
        return list(dict.fromkeys(normalized))


class PolicySimulationResult(BaseModel):
    profile: str
    region: str
    decision: Decision
    risk_score: float
    reason_codes: list[ReasonCode]
    policy_version: str
    thresholds: dict[str, float]
    checks: list[str]
    check_cost: dict[str, Any]
    decision_summary: str
    latency_ms: float


class PolicySimulationResponse(BaseModel):
    results: list[PolicySimulationResult]
    comparison_count: int


class PolicySimulator:
    """Run real evaluations without writing to the runtime audit repository."""

    def __init__(
        self,
        *,
        policies: PolicyStore | None = None,
        data: BusinessData | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self.policies = policies or PolicyStore()
        self.data = data or BusinessData()
        self.provider = provider or DeterministicDemoProvider()

    @classmethod
    def from_control_plane(cls, control_plane: ControlPlane) -> PolicySimulator:
        """Reuse runtime dependencies, intentionally excluding its audit repo."""

        return cls(
            policies=control_plane.policies,
            data=control_plane.data,
            provider=control_plane.provider,
        )

    def compare(self, simulation: PolicySimulationRequest) -> PolicySimulationResponse:
        configured = self.policies.version_info()
        profiles = simulation.profiles or list(configured["profiles"])
        regions = simulation.regions or list(configured["regions"])

        # Resolve every selection before doing any work, producing a useful
        # PolicyError for unknown profiles/regions without partial results.
        for profile in profiles:
            for region in regions:
                self.policies.resolve(
                    profile,
                    region,
                    requested_version=simulation.evaluation.policy_version,
                )

        results: list[PolicySimulationResult] = []
        run_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="controlplane-policy-sim-") as temp_dir:
            root = Path(temp_dir)
            for index, (profile, region) in enumerate(
                (profile, region) for profile in profiles for region in regions
            ):
                # A separate repository per candidate prevents cascade/session
                # state from leaking between policy alternatives.
                audit = AuditRepository(root / f"candidate-{index}.db")
                plane = ControlPlane(
                    policies=self.policies,
                    data=self.data,
                    audit=audit,
                    provider=self.provider,
                )
                candidate = simulation.evaluation.model_copy(
                    update={
                        "use_case": profile,
                        "region": region,
                        "session_id": f"simulation-{run_id}-{index}",
                    }
                )
                evaluated = plane.evaluate(candidate, source="policy_simulation")
                results.append(PolicySimulationResult(
                    profile=profile,
                    region=region,
                    decision=evaluated.decision,
                    risk_score=evaluated.risk_score,
                    reason_codes=evaluated.reason_codes,
                    policy_version=evaluated.policy.version,
                    thresholds=evaluated.policy.thresholds,
                    checks=evaluated.check_cost["checks_run"],
                    check_cost=evaluated.check_cost,
                    decision_summary=evaluated.decision_summary,
                    latency_ms=evaluated.total_latency_ms,
                ))

        return PolicySimulationResponse(
            results=results,
            comparison_count=len(results),
        )
