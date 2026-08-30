from __future__ import annotations

import re

from app.models import BlastRadius, Decision, EvidenceSignal
from app.reason_codes import ReasonCode


DECISION_ORDER = {
    Decision.ALLOW: 0,
    Decision.WARN_OR_EDIT: 1,
    Decision.HOLD_FOR_HUMAN: 2,
    Decision.BLOCK: 3,
}

DECISION_LABELS = {
    Decision.ALLOW: "allow",
    Decision.WARN_OR_EDIT: "warn or edit",
    Decision.HOLD_FOR_HUMAN: "hold for human review",
    Decision.BLOCK: "block",
}


def score_signals(signals: list[EvidenceSignal], weights: dict[str, float]) -> float:
    total = sum(
        signal.severity * signal.confidence * weights.get(signal.check_id, 1)
        for signal in signals
    )
    return round(min(100, total), 1)


def decide(
    signals: list[EvidenceSignal],
    risk_score: float,
    thresholds: dict[str, float],
    uncertainty_default: Decision,
    radius: BlastRadius,
    response: str | None,
) -> Decision:
    codes = {signal.code for signal in signals}

    # Layer 1 — hard constraints (cannot be overridden by weighted score).
    if ReasonCode.NUMERIC_MISMATCH in codes:
        return Decision.BLOCK
    if any(signal.check_id == "authorization" for signal in signals):
        return Decision.BLOCK
    if ReasonCode.INJECTION_SUSPECTED in codes and radius in (BlastRadius.R2, BlastRadius.R3):
        return Decision.BLOCK
    if ReasonCode.CASCADE_RISK_ELEVATED in codes and radius == BlastRadius.R3:
        return Decision.HOLD_FOR_HUMAN
    if ReasonCode.EVIDENCE_UNAVAILABLE in codes and ReasonCode.HIGH_DISAGREEMENT in codes:
        return uncertainty_default

    # Layer 2 — weighted evidence against profile thresholds.
    if risk_score >= thresholds["block"]:
        decision = Decision.BLOCK
    elif risk_score >= thresholds["hold_for_human"]:
        decision = Decision.HOLD_FOR_HUMAN
    elif risk_score >= thresholds["warn_or_edit"]:
        decision = Decision.WARN_OR_EDIT
    else:
        decision = Decision.ALLOW

    if (
        ReasonCode.EVIDENCE_UNAVAILABLE in codes
        and DECISION_ORDER[uncertainty_default] > DECISION_ORDER[decision]
    ):
        decision = uncertainty_default

    # High-impact floor: large unverified refunds defer to human review.
    if radius == BlastRadius.R3 and response:
        amount = re.search(r"(?:INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", response, re.IGNORECASE)
        if amount and float(amount.group(1).replace(",", "")) > 5000:
            if DECISION_ORDER[decision] < DECISION_ORDER[Decision.HOLD_FOR_HUMAN]:
                decision = Decision.HOLD_FOR_HUMAN

    return decision


def summarize_decision(decision: Decision, signals: list[EvidenceSignal], risk_score: float) -> str:
    """Plain-language explanation built from the decisive evidence signals."""
    label = DECISION_LABELS[decision]
    contributing = [signal for signal in signals if signal.severity > 0]
    contributing.sort(key=lambda signal: signal.severity * signal.confidence, reverse=True)

    if not contributing:
        return f"Decision: {label}. Risk score {risk_score:.1f} with no material findings."

    top = contributing[:3]
    reasons = "; ".join(signal.summary for signal in top)
    return f"Decision: {label} (risk score {risk_score:.1f}). {reasons}"
