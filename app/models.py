from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.reason_codes import ReasonCode


class BlastRadius(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class Decision(StrEnum):
    ALLOW = "allow"
    WARN_OR_EDIT = "warn_or_edit"
    HOLD_FOR_HUMAN = "hold_for_human"
    BLOCK = "block"


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    DETECTED = "detected"
    VERIFIED = "verified"
    NOT_APPLICABLE = "not_applicable"


class EvaluationRequest(BaseModel):
    use_case: str = "support_bot"
    region: str = "IN"
    action: str = "answer"
    prompt: str = Field(min_length=1, max_length=10_000)
    session_id: str = "anonymous"
    proposed_response: str | None = None
    samples: list[str] = Field(default_factory=list)
    prior_session_risk: float | None = Field(default=None, ge=0, le=100)
    scenario_id: str | None = None
    expected_harmful: bool | None = None


class EvidenceSignal(BaseModel):
    check_id: str
    code: ReasonCode
    labels: list[str]
    severity: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    status: EvidenceStatus
    summary: str
    evidence: list[str] = Field(default_factory=list)
    limitations: str = ""
    latency_ms: float = 0


class PolicyView(BaseModel):
    profile: str
    owner: str
    version: str
    region: str
    region_label: str
    risk_appetite: str
    latency_budget_ms: int
    permitted_actions: list[str]
    checks: list[str]
    weights: dict[str, float]
    thresholds: dict[str, float]
    disagreement_samples: dict[str, int]
    uncertainty_default: Decision
    retention_days: int
    consent_required: bool
    pii_categories: list[str]


class EvaluationResult(BaseModel):
    audit_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenario_id: str | None
    use_case: str
    region: str
    action: str
    session_id: str
    blast_radius: BlastRadius
    policy: PolicyView
    decision: Decision
    risk_score: float
    reason_codes: list[ReasonCode]
    signals: list[EvidenceSignal]
    original_response: str | None
    safe_response: str | None
    model_called: bool
    total_latency_ms: float
    check_cost: dict[str, Any]


class ReviewRequest(BaseModel):
    human_label: str = Field(pattern="^(safe|unsafe)$")
    decision: Decision | None = None
    note: str = Field(default="", max_length=1000)

