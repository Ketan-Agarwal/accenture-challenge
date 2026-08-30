from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.audit import AuditRepository
from app.check_routing import CheckPlan, build_check_plan
from app.checks import (
    blast_radius,
    cascade_check,
    disagreement_check,
    grounding_check,
    injection_check,
    numeric_check,
    pii_check,
    redact_pii,
)
from app.data_store import BusinessData
from app.decision_engine import decide, score_signals, summarize_decision
from app.models import (
    BlastRadius,
    Decision,
    EvidenceSignal,
    EvidenceStatus,
    EvaluationRequest,
    EvaluationResult,
    PolicyView,
)
from app.policy import PolicyStore
from app.provider import DeterministicDemoProvider, ModelProvider
from app.reason_codes import ReasonCode


@dataclass
class PipelineContext:
    request: EvaluationRequest
    policy: PolicyView
    radius: BlastRadius
    plan: CheckPlan
    signals: list[EvidenceSignal]
    checks_run: list[str]
    response: str | None = None
    model_called: bool = False


class ControlPlane:
    def __init__(
        self,
        policies: PolicyStore | None = None,
        data: BusinessData | None = None,
        audit: AuditRepository | None = None,
        provider: ModelProvider | None = None,
    ):
        self.policies = policies or PolicyStore()
        self.data = data or BusinessData()
        self.audit = audit or AuditRepository()
        self.provider = provider or DeterministicDemoProvider()

    def evaluate(self, request: EvaluationRequest, *, source: str = "runtime") -> EvaluationResult:
        started = time.perf_counter()
        ctx = self._resolve_context(request)
        self._run_preflight(ctx)
        if not self._hard_preflight_block(ctx):
            self._call_model(ctx)
            self._run_post_checks(ctx)

        risk_score = score_signals(ctx.signals, ctx.policy.weights)
        decision = decide(
            ctx.signals,
            risk_score,
            ctx.policy.thresholds,
            ctx.policy.uncertainty_default,
            ctx.radius,
            ctx.response,
        )
        result = self._build_result(ctx, decision, risk_score, started)
        self.audit.save(request, result, source=source)
        return result

    def _resolve_context(self, request: EvaluationRequest) -> PipelineContext:
        policy = self.policies.resolve(
            request.use_case,
            request.region,
            requested_version=request.policy_version,
        )
        radius = blast_radius(request.action)
        plan = build_check_plan(policy, radius, request.action)
        ctx = PipelineContext(
            request=request,
            policy=policy,
            radius=radius,
            plan=plan,
            signals=[],
            checks_run=[],
        )
        self._append_blast_radius_signal(ctx)
        if policy.version_stale:
            ctx.signals.append(EvidenceSignal(
                check_id="policy_version",
                code=ReasonCode.POLICY_VERSION_STALE,
                labels=["governance"],
                severity=15,
                confidence=1,
                status=EvidenceStatus.DETECTED,
                summary=(
                    f"Client requested policy version {policy.requested_version} "
                    f"but active version is {policy.version}."
                ),
                evidence=[f"Active version used for decision: {policy.version}"],
                limitations="Prototype replays stale requests against the current active policy.",
            ))
            ctx.checks_run.append("policy_version")
        return ctx

    @staticmethod
    def _append_blast_radius_signal(ctx: PipelineContext) -> None:
        ctx.checks_run.append("blast_radius")
        if ctx.radius != BlastRadius.R3:
            return
        ctx.signals.append(EvidenceSignal(
            check_id="blast_radius",
            code=ReasonCode.ACTION_BLAST_RADIUS_HIGH,
            labels=["agentic_risk", "financial"],
            severity=0,
            confidence=1,
            status=EvidenceStatus.DETECTED,
            summary="The requested action has irreversible financial impact.",
            evidence=["R3 actions require deterministic verification and conservative fallback behavior."],
            limitations="Blast radius describes consequence, not evidence that the request is harmful.",
        ))

    def _run_preflight(self, ctx: PipelineContext) -> None:
        if ctx.request.action not in ctx.policy.permitted_actions:
            ctx.signals.append(EvidenceSignal(
                check_id="authorization",
                code=ReasonCode.ACTION_BLAST_RADIUS_HIGH,
                labels=["authorization", "agentic_risk"],
                severity=100,
                confidence=1,
                status=EvidenceStatus.CONTRADICTED,
                summary=f"Action '{ctx.request.action}' is not permitted for {ctx.policy.profile}.",
                evidence=[f"Permitted actions: {', '.join(ctx.policy.permitted_actions)}"],
                limitations="Prototype authorization is policy-profile based, not user-identity based.",
            ))
            ctx.checks_run.append("authorization")

        if ctx.plan.run_injection:
            ctx.checks_run.append("injection")
            injection = injection_check(ctx.request.prompt, ctx.radius)
            if injection:
                ctx.signals.append(injection)

        if ctx.plan.run_pii_input:
            ctx.checks_run.append("pii_input")
            input_pii = pii_check(ctx.request.prompt, "input", ctx.policy.pii_categories)
            if input_pii:
                ctx.signals.append(input_pii)

    @staticmethod
    def _hard_preflight_block(ctx: PipelineContext) -> bool:
        unauthorized = any(signal.check_id == "authorization" for signal in ctx.signals)
        injection_block = any(
            signal.code == ReasonCode.INJECTION_SUSPECTED for signal in ctx.signals
        ) and ctx.radius in (BlastRadius.R2, BlastRadius.R3)
        return unauthorized or injection_block

    def _call_model(self, ctx: PipelineContext) -> None:
        ctx.response = ctx.request.proposed_response
        if ctx.response is None:
            ctx.response = self.provider.generate(ctx.request)
            ctx.model_called = True

    def _run_post_checks(self, ctx: PipelineContext) -> None:
        if ctx.response is None:
            return

        task_specs: list[tuple[str, object]] = []
        if ctx.plan.run_pii_output:
            task_specs.append((
                "pii_output",
                lambda: pii_check(ctx.response, "output", ctx.policy.pii_categories),
            ))
        if ctx.plan.run_grounding:
            task_specs.append((
                "grounding",
                lambda: grounding_check(ctx.response, self.data.policy_chunks),
            ))
        if ctx.plan.run_numeric:
            checked_request = ctx.request.model_copy(update={"proposed_response": ctx.response})
            task_specs.append(("numeric", lambda: numeric_check(checked_request, self.data)))

        ctx.checks_run.extend(name for name, _ in task_specs)
        completed: dict[str, EvidenceSignal | None] = {}
        if task_specs:
            with ThreadPoolExecutor(max_workers=max(1, len(task_specs))) as executor:
                futures = [(name, executor.submit(check)) for name, check in task_specs]
                for name, future in futures:
                    completed[name] = future.result()
            for name, _ in task_specs:
                if completed[name]:
                    ctx.signals.append(completed[name])

        grounding = completed.get("grounding")
        evidence_unavailable = grounding is not None and grounding.status == EvidenceStatus.UNAVAILABLE
        if ctx.plan.run_disagreement and evidence_unavailable:
            budget = ctx.plan.disagreement_sample_budget
            if budget > 0 and len(ctx.request.samples) >= 2:
                ctx.checks_run.append("disagreement")
                disagreement = disagreement_check(ctx.request.samples[:budget])
                if disagreement:
                    ctx.signals.append(disagreement)

        if ctx.plan.run_cascade:
            ctx.checks_run.append("cascade")
            prior_risk = ctx.request.prior_session_risk
            if prior_risk is None:
                prior_risk = self.audit.session_risk(ctx.request.session_id)
            cascade = cascade_check(prior_risk, ctx.radius)
            if cascade:
                ctx.signals.append(cascade)

    def _build_result(
        self,
        ctx: PipelineContext,
        decision: Decision,
        risk_score: float,
        started: float,
    ) -> EvaluationResult:
        safe_response = redact_pii(ctx.response, ctx.policy.pii_categories)
        if decision in (Decision.HOLD_FOR_HUMAN, Decision.BLOCK):
            safe_response = None

        verification_sample_calls = 0
        if "disagreement" in ctx.checks_run:
            verification_sample_calls = min(
                len(ctx.request.samples),
                ctx.plan.disagreement_sample_budget,
            )
        primary_model_calls = int(ctx.model_called)
        reason_codes = list(dict.fromkeys(signal.code for signal in ctx.signals))

        return EvaluationResult(
            audit_id=f"cp_{uuid.uuid4().hex[:12]}",
            scenario_id=ctx.request.scenario_id,
            use_case=ctx.request.use_case,
            region=ctx.request.region,
            action=ctx.request.action,
            session_id=ctx.request.session_id,
            blast_radius=ctx.radius,
            policy=ctx.policy,
            decision=decision,
            risk_score=risk_score,
            reason_codes=reason_codes,
            signals=ctx.signals,
            original_response=ctx.response,
            safe_response=safe_response,
            model_called=ctx.model_called,
            total_latency_ms=round((time.perf_counter() - started) * 1000, 2),
            check_cost={
                "model_calls": primary_model_calls + verification_sample_calls,
                "primary_model_calls": primary_model_calls,
                "verification_sample_calls": verification_sample_calls,
                "checks_run": list(dict.fromkeys(ctx.checks_run)),
                "blast_radius": ctx.radius.value,
            },
            decision_summary=summarize_decision(decision, ctx.signals, risk_score),
        )
