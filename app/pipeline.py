from __future__ import annotations

import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.audit import AuditRepository
from app.checks import (
    blast_radius, cascade_check, disagreement_check, grounding_check, injection_check,
    numeric_check, pii_check, redact_pii,
)
from app.data_store import BusinessData
from app.models import (
    BlastRadius, Decision, EvidenceSignal, EvidenceStatus, EvaluationRequest, EvaluationResult,
)
from app.policy import PolicyStore
from app.provider import DeterministicDemoProvider, ModelProvider
from app.reason_codes import ReasonCode


DECISION_ORDER = {
    Decision.ALLOW: 0,
    Decision.WARN_OR_EDIT: 1,
    Decision.HOLD_FOR_HUMAN: 2,
    Decision.BLOCK: 3,
}


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
        policy = self.policies.resolve(request.use_case, request.region)
        radius = blast_radius(request.action)
        signals: list[EvidenceSignal] = []
        checks_run: list[str] = []

        if radius == BlastRadius.R3:
            signals.append(EvidenceSignal(
                check_id="blast_radius", code=ReasonCode.ACTION_BLAST_RADIUS_HIGH,
                labels=["agentic_risk", "financial"], severity=0, confidence=1,
                status=EvidenceStatus.DETECTED,
                summary="The requested action has irreversible financial impact.",
                evidence=["R3 actions require deterministic verification and conservative fallback behavior."],
                limitations="Blast radius describes consequence, not evidence that the request is harmful.",
            ))
        checks_run.append("blast_radius")

        if request.action not in policy.permitted_actions:
            signals.append(EvidenceSignal(
                check_id="authorization", code=ReasonCode.ACTION_BLAST_RADIUS_HIGH,
                labels=["authorization", "agentic_risk"], severity=100, confidence=1,
                status=EvidenceStatus.CONTRADICTED,
                summary=f"Action '{request.action}' is not permitted for {policy.profile}.",
                evidence=[f"Permitted actions: {', '.join(policy.permitted_actions)}"],
                limitations="Prototype authorization is policy-profile based, not user-identity based.",
            ))
            checks_run.append("authorization")
        injection = injection_check(request.prompt, radius) if "injection" in policy.checks else None
        input_pii = pii_check(request.prompt, "input", policy.pii_categories) if "pii" in policy.checks else None
        if "injection" in policy.checks:
            checks_run.append("injection")
        if "pii" in policy.checks:
            checks_run.append("pii_input")
        signals.extend(signal for signal in (injection, input_pii) if signal)

        hard_preflight_block = any(signal.check_id == "authorization" for signal in signals) or bool(
            injection and radius in (BlastRadius.R2, BlastRadius.R3)
        )
        response: str | None = None
        model_called = False
        if not hard_preflight_block:
            response = request.proposed_response
            if response is None:
                response = self.provider.generate(request)
                model_called = True

            task_specs = []
            if "pii" in policy.checks:
                task_specs.append(("pii_output", lambda: pii_check(response, "output", policy.pii_categories)))
            if "grounding" in policy.checks:
                task_specs.append(("grounding", lambda: grounding_check(response, self.data.policy_chunks)))
            if "numeric" in policy.checks:
                checked_request = request.model_copy(update={"proposed_response": response})
                task_specs.append(("numeric", lambda: numeric_check(checked_request, self.data)))
            checks_run.extend(name for name, _ in task_specs)
            completed: dict[str, EvidenceSignal | None] = {}
            with ThreadPoolExecutor(max_workers=max(1, len(task_specs))) as executor:
                futures = [(name, executor.submit(check)) for name, check in task_specs]
                for name, future in futures:
                    completed[name] = future.result()
            for name, _ in task_specs:
                if completed[name]:
                    signals.append(completed[name])
            grounding = completed.get("grounding")

            evidence_unavailable = grounding is not None and grounding.status == EvidenceStatus.UNAVAILABLE
            sample_budget = policy.disagreement_samples.get(str(radius), 0)
            if "disagreement" in policy.checks and evidence_unavailable and sample_budget >= 2:
                checks_run.append("disagreement")
                disagreement = disagreement_check(request.samples[:sample_budget])
                if disagreement:
                    signals.append(disagreement)

            prior_risk = request.prior_session_risk
            if prior_risk is None:
                prior_risk = self.audit.session_risk(request.session_id)
            cascade = cascade_check(prior_risk, radius) if "cascade" in policy.checks else None
            if "cascade" in policy.checks:
                checks_run.append("cascade")
            if cascade:
                signals.append(cascade)

        risk_score = self._score(signals, policy.weights)
        decision = self._decide(signals, risk_score, policy.thresholds, policy.uncertainty_default, radius, response)
        safe_response = redact_pii(response, policy.pii_categories)
        if decision in (Decision.HOLD_FOR_HUMAN, Decision.BLOCK):
            safe_response = None
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        reason_codes = list(dict.fromkeys(signal.code for signal in signals))
        verification_sample_calls = min(len(request.samples), policy.disagreement_samples.get(str(radius), 0)) \
            if "disagreement" in checks_run else 0
        primary_model_calls = int(model_called)
        result = EvaluationResult(
            audit_id=f"cp_{uuid.uuid4().hex[:12]}", scenario_id=request.scenario_id,
            use_case=request.use_case, region=request.region, action=request.action,
            session_id=request.session_id, blast_radius=radius, policy=policy,
            decision=decision, risk_score=risk_score, reason_codes=reason_codes,
            signals=signals, original_response=response, safe_response=safe_response,
            model_called=model_called, total_latency_ms=elapsed,
            check_cost={
                "model_calls": primary_model_calls + verification_sample_calls,
                "primary_model_calls": primary_model_calls,
                "verification_sample_calls": verification_sample_calls,
                "checks_run": list(dict.fromkeys(checks_run)),
            },
        )
        self.audit.save(request, result, source=source)
        return result

    @staticmethod
    def _score(signals: list[EvidenceSignal], weights: dict[str, float]) -> float:
        score = sum(signal.severity * signal.confidence * weights.get(signal.check_id, 1) for signal in signals)
        return round(min(100, score), 1)

    @staticmethod
    def _decide(
        signals: list[EvidenceSignal], risk_score: float, thresholds: dict[str, float],
        uncertainty_default: Decision, radius: BlastRadius, response: str | None,
    ) -> Decision:
        codes = {signal.code for signal in signals}
        if ReasonCode.NUMERIC_MISMATCH in codes:
            return Decision.BLOCK
        if any(signal.check_id == "authorization" for signal in signals):
            return Decision.BLOCK
        if ReasonCode.INJECTION_SUSPECTED in codes and radius in (BlastRadius.R2, BlastRadius.R3):
            return Decision.BLOCK
        if ReasonCode.CASCADE_RISK_ELEVATED in codes and radius == BlastRadius.R3:
            return Decision.HOLD_FOR_HUMAN
        if ReasonCode.EVIDENCE_UNAVAILABLE in codes and ReasonCode.HIGH_DISAGREEMENT in codes:
            # Instability without authoritative evidence justifies abstention, not a claim of known harm.
            return uncertainty_default

        if risk_score >= thresholds["block"]:
            decision = Decision.BLOCK
        elif risk_score >= thresholds["hold_for_human"]:
            decision = Decision.HOLD_FOR_HUMAN
        elif risk_score >= thresholds["warn_or_edit"]:
            decision = Decision.WARN_OR_EDIT
        else:
            decision = Decision.ALLOW

        if ReasonCode.EVIDENCE_UNAVAILABLE in codes and DECISION_ORDER[uncertainty_default] > DECISION_ORDER[decision]:
            decision = uncertainty_default

        if radius == BlastRadius.R3 and response:
            amount = re.search(r"(?:INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", response, re.IGNORECASE)
            if amount and float(amount.group(1).replace(",", "")) > 5000 and DECISION_ORDER[decision] < DECISION_ORDER[Decision.HOLD_FOR_HUMAN]:
                decision = Decision.HOLD_FOR_HUMAN
        return decision
