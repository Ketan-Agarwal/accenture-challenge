from __future__ import annotations

import os
import secrets
from decimal import Decimal
from typing import Literal, NoReturn

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.action_gateway import (
    ActionGateway,
    ActionNotFound,
    ActionRecord,
    ActionReview,
    AuthorizationExpired,
    GatewayError,
    InvalidActionState,
    InvalidAuthorization,
    ProposalError,
)
from app.models import EvaluationRequest, EvaluationResult, ReviewRequest
from app.pipeline import ControlPlane
from app.policy import PolicyError
from app.policy_simulator import (
    PolicySimulationRequest,
    PolicySimulator,
)


app = FastAPI(
    title="ControlPlane.ai",
    version="0.1.0",
    description="Evidence-aware runtime governance middleware for enterprise AI",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
control_plane = ControlPlane()
policy_simulator = PolicySimulator.from_control_plane(control_plane)
action_gateway = ActionGateway(
    control_plane.audit.path,
    control_plane.data,
    os.getenv("CONTROLPLANE_ACTION_SECRET") or secrets.token_bytes(32),
    token_ttl_seconds=300,
)


class ActionProposalRequest(BaseModel):
    use_case: str = "refund_agent"
    region: str = "IN"
    session_id: str = "action-gateway-demo"
    order_id: str = Field(pattern=r"^ORD-\d{4}$")
    amount_inr: Decimal = Field(gt=0, decimal_places=2)
    reason: str = Field(min_length=1, max_length=500)


class ActionExecutionRequest(BaseModel):
    authorization_token: str = Field(min_length=20, max_length=4096)


class ActionReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    corrected_amount_inr: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    note: str = Field(default="", max_length=1000)


class PolicySimulationApiRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    proposed_response: str = Field(min_length=1, max_length=10_000)
    action: str = "answer"
    region: str = "IN"
    profiles: list[str] = Field(default_factory=list, max_length=10)


def _action_payload(action: ActionRecord, authorization_token: str | None = None) -> dict:
    """Join the immutable gateway record to its explainable audit receipt."""

    audit = control_plane.audit.get(action.audit_id) or {}
    return {
        "action_id": action.action_id,
        "audit_id": action.audit_id,
        "action_type": action.action_type,
        "order_id": action.order_id,
        "amount_inr": float(action.amount_inr),
        "use_case": audit.get("use_case", "refund_agent"),
        "region": audit.get("region", "IN"),
        "session_id": audit.get("session_id", "unknown"),
        "reason": audit.get("prompt", ""),
        "decision": audit.get("decision", "block"),
        "risk_score": audit.get("risk_score", 100),
        "reason_codes": audit.get("reason_codes", []),
        "signals": audit.get("signals", []),
        "decision_summary": audit.get("decision_summary", ""),
        "policy_version": action.policy_version,
        "status": action.status,
        "authorization_token": authorization_token,
        "token_expires_at": action.expires_at,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
        "review_note": action.review_note,
    }


def _raise_gateway_http(exc: GatewayError) -> NoReturn:
    if isinstance(exc, ActionNotFound):
        raise HTTPException(status_code=404, detail="Action not found") from exc
    if isinstance(exc, AuthorizationExpired):
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    if isinstance(exc, InvalidAuthorization):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, InvalidActionState):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ProposalError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version, "mode": "deterministic-demo"}


@app.get("/api/scenarios")
async def scenarios() -> list[dict]:
    return control_plane.data.demo_scenarios


@app.post("/api/scenarios/{scenario_id}/run", response_model=EvaluationResult)
async def run_scenario(scenario_id: str) -> EvaluationResult:
    try:
        scenario = control_plane.data.scenario(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Scenario not found") from exc
    payload = {key: value for key, value in scenario.items() if key in EvaluationRequest.model_fields}
    payload["scenario_id"] = scenario_id
    return control_plane.evaluate(EvaluationRequest(**payload), source="demo")


@app.post("/api/evaluate", response_model=EvaluationResult)
async def evaluate(request: EvaluationRequest) -> EvaluationResult:
    try:
        return control_plane.evaluate(request)
    except PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/evaluation-suite/run")
async def run_evaluation_suite() -> dict:
    results = []
    for scenario in control_plane.data.evaluation_scenarios:
        payload = {key: value for key, value in scenario.items() if key in EvaluationRequest.model_fields}
        payload["scenario_id"] = scenario["id"]
        result = control_plane.evaluate(EvaluationRequest(**payload), source="evaluation")
        results.append({
            "scenario_id": scenario["id"],
            "decision": result.decision,
            "risk_score": result.risk_score,
            "expected_harmful": scenario["expected_harmful"],
        })
    return {"count": len(results), "results": results, "metrics": control_plane.audit.metrics()}


@app.get("/api/policies")
async def policies() -> list[dict]:
    return [policy.model_dump(mode="json") for policy in control_plane.policies.list_profiles()]


@app.get("/api/policies/versions")
async def policy_versions() -> dict:
    return control_plane.policies.version_info()


@app.post("/api/policy-simulator")
async def simulate_policies(request: PolicySimulationApiRequest) -> dict:
    """Compare policy contexts without contaminating the production audit log."""

    try:
        comparison = policy_simulator.compare(PolicySimulationRequest(
            evaluation=EvaluationRequest(
                use_case=request.profiles[0] if request.profiles else "support_bot",
                region=request.region,
                action=request.action,
                prompt=request.prompt,
                proposed_response=request.proposed_response,
                session_id="policy-simulator",
            ),
            profiles=request.profiles,
            regions=[request.region],
        ))
        rows = []
        for result in comparison.results:
            row = result.model_dump(mode="json")
            row["checks_run"] = row.pop("checks")
            rows.append(row)
        return {"results": rows, "comparison_count": comparison.comparison_count}
    except PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/commerce/orders")
async def commerce_orders() -> list[dict]:
    return [
        {
            **order.model_dump(mode="json"),
            "order_total_inr": float(order.order_total_inr),
            "refunded_amount_inr": (
                float(order.refunded_amount_inr) if order.refunded_amount_inr is not None else None
            ),
            "refund_status": "refunded" if order.refund_action_id else None,
        }
        for order in action_gateway.list_orders()
    ]


@app.get("/api/actions")
async def governed_actions() -> list[dict]:
    # Authorization capabilities are deliberately never exposed by ledger reads.
    return [_action_payload(action) for action in action_gateway.list_actions()]


@app.post("/api/actions/propose")
async def propose_action(request: ActionProposalRequest) -> dict:
    evaluation_request = EvaluationRequest(
        use_case=request.use_case,
        region=request.region,
        action="issue_refund",
        session_id=request.session_id,
        prompt=(
            f"Issue INR {request.amount_inr} for {request.order_id}. "
            f"Customer reason: {request.reason}."
        ),
        proposed_response=f"I will issue INR {request.amount_inr} for {request.order_id}.",
    )
    try:
        evaluation = control_plane.evaluate(evaluation_request, source="action_gateway")
        proposal = action_gateway.propose_from_evaluation(evaluation_request, evaluation)
        if proposal is None:  # Defensive: this adapter only emits executable actions.
            raise HTTPException(status_code=422, detail="No executable action was proposed")
        return {
            "action": _action_payload(proposal.action, proposal.authorization_token),
            "evaluation": evaluation,
            "authorization_token": proposal.authorization_token,
        }
    except PolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GatewayError as exc:
        _raise_gateway_http(exc)


@app.post("/api/actions/{action_id}/review")
async def review_action(action_id: str, request: ActionReviewRequest) -> dict:
    try:
        action = action_gateway.get_action(action_id)
        if request.decision == "approve" and request.corrected_amount_inr is not None:
            audit = control_plane.audit.get(action.audit_id) or {}
            correction = EvaluationRequest(
                use_case=audit.get("use_case", "refund_agent"),
                region=audit.get("region", "IN"),
                action="issue_refund",
                session_id=f"human-correction-{action_id}",
                prompt=(
                    f"Issue INR {request.corrected_amount_inr} for {action.order_id}. "
                    "Human reviewer correction."
                ),
                proposed_response=(
                    f"I will issue INR {request.corrected_amount_inr} for {action.order_id}."
                ),
            )
            validated = control_plane.evaluate(correction, source="human_review_validation")
            numeric_signal = next(
                (signal for signal in validated.signals if signal.check_id == "numeric"),
                None,
            )
            if numeric_signal is None or numeric_signal.code != "NUMERIC_VERIFIED":
                raise HTTPException(
                    status_code=409,
                    detail="Corrected amount did not pass deterministic commerce verification",
                )
        reviewed = action_gateway.review(
            action_id,
            ActionReview(
                approve=request.decision == "approve",
                corrected_amount_inr=request.corrected_amount_inr,
                note=request.note,
            ),
        )
        control_plane.audit.review(
            reviewed.action.audit_id,
            ReviewRequest(
                human_label="safe" if request.decision == "approve" else "unsafe",
                note=request.note,
            ),
        )
        return {
            "action": _action_payload(reviewed.action, reviewed.authorization_token),
            "authorization_token": reviewed.authorization_token,
        }
    except GatewayError as exc:
        _raise_gateway_http(exc)


@app.post("/api/actions/{action_id}/execute")
async def execute_action(action_id: str, request: ActionExecutionRequest) -> dict:
    try:
        receipt = action_gateway.execute(
            request.authorization_token,
            expected_action_id=action_id,
        )
        action = action_gateway.get_action(action_id)
        return {
            "action": {
                **_action_payload(action),
                "executed_at": receipt.executed_at,
                "refund_id": receipt.refund_id,
            },
            "receipt": receipt,
        }
    except GatewayError as exc:
        _raise_gateway_http(exc)


@app.get("/api/audits")
async def audits(limit: int = Query(default=25, ge=1, le=100)) -> list[dict]:
    return control_plane.audit.recent(limit)


@app.post("/api/audits/{audit_id}/review")
async def review(audit_id: str, request: ReviewRequest) -> dict:
    try:
        return control_plane.audit.review(audit_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Audit record not found") from exc


@app.get("/api/metrics")
async def metrics() -> dict:
    return control_plane.audit.metrics()
