from __future__ import annotations

import itertools
import math
import re
import time
from collections.abc import Callable

from app.data_store import BusinessData
from app.models import BlastRadius, EvidenceSignal, EvidenceStatus, EvaluationRequest
from app.reason_codes import ReasonCode


ACTION_RISK = {
    "answer": BlastRadius.R0,
    "lookup_order": BlastRadius.R0,
    "draft_email": BlastRadius.R1,
    "send_email": BlastRadius.R2,
    "issue_refund": BlastRadius.R3,
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "has", "in", "is", "it",
    "of", "on", "or", "the", "this", "to", "with", "will", "when", "every", "after",
}


def blast_radius(action: str) -> BlastRadius:
    return ACTION_RISK.get(action, BlastRadius.R2)


def _timed(build: Callable[[], EvidenceSignal]) -> EvidenceSignal:
    started = time.perf_counter()
    signal = build()
    signal.latency_ms = round((time.perf_counter() - started) * 1000, 3)
    return signal


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def _jaccard(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def injection_check(prompt: str, radius: BlastRadius) -> EvidenceSignal | None:
    patterns = [
        r"ignore (?:all |any )?(?:previous|prior) instructions",
        r"bypass (?:the )?(?:policy|safety|security) checks?",
        r"reveal (?:the )?(?:system|developer) prompt",
        r"you are now (?:unrestricted|in developer mode)",
    ]
    matches = [pattern for pattern in patterns if re.search(pattern, prompt, re.IGNORECASE)]
    if not matches:
        return None
    severity = {BlastRadius.R0: 20, BlastRadius.R1: 35, BlastRadius.R2: 70, BlastRadius.R3: 100}[radius]
    return _timed(lambda: EvidenceSignal(
        check_id="injection",
        code=ReasonCode.INJECTION_SUSPECTED,
        labels=["security", "instruction_integrity"],
        severity=severity,
        confidence=0.82,
        status=EvidenceStatus.DETECTED,
        summary=f"Instruction-override language detected for a {radius} action.",
        evidence=[f"Matched {len(matches)} bounded injection heuristic(s)."],
        limitations="Pattern screening is partial and does not establish malicious intent by itself.",
    ))


PII_PATTERNS = {
    "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    "phone": r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)",
    "payment_card": r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)",
    "aadhaar_like": r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}


def pii_check(text: str, location: str, categories: list[str]) -> EvidenceSignal | None:
    found: list[str] = []
    for category in categories:
        pattern = PII_PATTERNS.get(category)
        if pattern and re.search(pattern, text, re.IGNORECASE):
            found.append(category)
    if not found:
        return None
    output = location == "output"
    return _timed(lambda: EvidenceSignal(
        check_id="pii",
        code=ReasonCode.PII_DETECTED_OUTPUT if output else ReasonCode.PII_DETECTED_INPUT,
        labels=["privacy", "data_protection"],
        severity=58 if output else 38,
        confidence=0.94,
        status=EvidenceStatus.DETECTED,
        summary=f"Detected {', '.join(found)} in the {location}.",
        evidence=[f"{len(found)} configured identifier category/categories matched."],
        limitations="Regex detection covers a bounded synthetic identifier set and can produce false positives.",
    ))


def redact_pii(text: str | None, categories: list[str]) -> str | None:
    if text is None:
        return None
    redacted = text
    for category in categories:
        pattern = PII_PATTERNS.get(category)
        if pattern:
            redacted = re.sub(pattern, f"[REDACTED_{category.upper()}]", redacted, flags=re.IGNORECASE)
    return redacted


def grounding_check(response: str, chunks: list[str]) -> EvidenceSignal | None:
    claim_markers = ("policy", "refund", "refundable", "credit", "eligible", "delivery", "guarantee")
    if not any(marker in response.lower() for marker in claim_markers):
        return None
    scored = sorted(((_jaccard(response, chunk), chunk) for chunk in chunks), reverse=True, key=lambda item: item[0])
    best_score, best_chunk = scored[0] if scored else (0.0, "")
    response_lower, chunk_lower = response.lower(), best_chunk.lower()
    contradictory = any(
        left in response_lower and right in chunk_lower
        for left, right in [
            ("full cash refund", "not eligible for an automatic full cash refund"),
            ("full refund", "non-refundable"),
            ("guarantee", "not eligible"),
        ]
    )
    corpus = " ".join(chunks).lower()
    novel_goodwill_claim = "goodwill" in response_lower and "goodwill" not in corpus
    if contradictory:
        status, code, severity, summary = (
            EvidenceStatus.CONTRADICTED,
            ReasonCode.CLAIM_CONTRADICTED,
            70,
            "The response conflicts with the closest policy clause.",
        )
    elif novel_goodwill_claim:
        status, code, severity, summary = (
            EvidenceStatus.UNAVAILABLE,
            ReasonCode.EVIDENCE_UNAVAILABLE,
            35,
            "No authoritative policy evidence exists for the goodwill claim.",
        )
    elif best_score >= 0.34:
        status, code, severity, summary = (
            EvidenceStatus.SUPPORTED,
            ReasonCode.CLAIM_SUPPORTED,
            0,
            "The response is attributable to a policy clause.",
        )
    elif best_score < 0.10:
        status, code, severity, summary = (
            EvidenceStatus.UNAVAILABLE,
            ReasonCode.EVIDENCE_UNAVAILABLE,
            35,
            "No sufficiently relevant authoritative policy evidence was found.",
        )
    else:
        status, code, severity, summary = (
            EvidenceStatus.UNSUPPORTED,
            ReasonCode.CLAIM_UNSUPPORTED,
            62,
            "The response makes a policy claim that the retrieved material does not support.",
        )
    excerpt = re.sub(r"\s+", " ", best_chunk)[:240]
    return _timed(lambda: EvidenceSignal(
        check_id="grounding",
        code=code,
        labels=["hallucination", "governance"],
        severity=severity,
        confidence=round(min(0.98, 0.55 + abs(best_score - 0.2)), 2),
        status=status,
        summary=summary,
        evidence=[f"Best lexical evidence score: {best_score:.2f}", excerpt] if excerpt else [],
        limitations="Lexical retrieval is evidence, not proof of entailment; a reviewer should inspect consequential claims.",
    ))


def numeric_check(request: EvaluationRequest, data: BusinessData) -> EvidenceSignal | None:
    if request.action != "issue_refund" or not request.proposed_response:
        return None
    order_match = re.search(r"ORD-\d{4}", f"{request.prompt} {request.proposed_response}", re.IGNORECASE)
    amount_match = re.search(r"(?:INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", request.proposed_response, re.IGNORECASE)
    if not order_match or not amount_match:
        return _timed(lambda: EvidenceSignal(
            check_id="numeric", code=ReasonCode.EVIDENCE_UNAVAILABLE, labels=["financial", "hallucination"],
            severity=78, confidence=0.95, status=EvidenceStatus.UNAVAILABLE,
            summary="A financial action lacks a parseable order ID or amount.",
            evidence=[], limitations="The prototype parser accepts ORD-#### and INR/₹ amount formats.",
        ))
    order_id = order_match.group(0).upper()
    order = data.orders.get(order_id)
    if not order:
        return _timed(lambda: EvidenceSignal(
            check_id="numeric", code=ReasonCode.EVIDENCE_UNAVAILABLE, labels=["financial"], severity=90,
            confidence=0.99, status=EvidenceStatus.UNAVAILABLE, summary=f"{order_id} does not exist in the system of record.",
            evidence=[], limitations="Synthetic order database only.",
        ))
    stated = float(amount_match.group(1).replace(",", ""))
    total = float(order["order_total_inr"])
    issue = order["fulfilment_issue"]
    status = order["status"]
    allowed = total if issue == "wrong_item" and status == "delivered" else round(total * 0.10, 2) if issue == "late_delivery" else None
    matches = allowed is not None and math.isclose(stated, allowed, abs_tol=0.01)
    if matches:
        return _timed(lambda: EvidenceSignal(
            check_id="numeric", code=ReasonCode.NUMERIC_VERIFIED, labels=["financial"], severity=0,
            confidence=1, status=EvidenceStatus.VERIFIED, summary="Refund amount and eligibility match the order record.",
            evidence=[f"{order_id}: expected INR {allowed:,.2f}; stated INR {stated:,.2f}"],
            limitations="Verification is limited to the synthetic refund rules and order table.",
        ))
    expected = "no automated cash refund" if allowed is None else f"INR {allowed:,.2f}"
    return _timed(lambda: EvidenceSignal(
        check_id="numeric", code=ReasonCode.NUMERIC_MISMATCH, labels=["financial", "hallucination", "policy"],
        severity=100, confidence=1, status=EvidenceStatus.CONTRADICTED,
        summary="The proposed refund conflicts with deterministic business data or policy eligibility.",
        evidence=[f"{order_id}: expected {expected}; stated INR {stated:,.2f}; status={status}; issue={issue}"],
        limitations="Verification is limited to the synthetic refund rules and order table.",
    ))


def disagreement_check(samples: list[str]) -> EvidenceSignal | None:
    if len(samples) < 2:
        return None
    similarities = [_jaccard(a, b) for a, b in itertools.combinations(samples, 2)]
    agreement = sum(similarities) / len(similarities)
    disagreement = 1 - agreement
    if disagreement < 0.55:
        return None
    return _timed(lambda: EvidenceSignal(
        check_id="disagreement", code=ReasonCode.HIGH_DISAGREEMENT,
        labels=["uncertainty", "hallucination"], severity=round(disagreement * 80, 1), confidence=0.78,
        status=EvidenceStatus.DETECTED,
        summary="Repeated response samples materially disagree in meaning.",
        evidence=[f"Pairwise lexical disagreement: {disagreement:.2f}", f"Samples compared: {len(samples)}"],
        limitations="Sample agreement measures stability, not factual correctness; lexical similarity is a prototype approximation.",
    ))


def cascade_check(prior_risk: float, radius: BlastRadius) -> EvidenceSignal | None:
    if prior_risk < 25 or radius not in (BlastRadius.R2, BlastRadius.R3):
        return None
    severity = min(90, prior_risk + (25 if radius == BlastRadius.R3 else 10))
    return _timed(lambda: EvidenceSignal(
        check_id="cascade", code=ReasonCode.CASCADE_RISK_ELEVATED,
        labels=["agentic_risk", "compounding_risk"], severity=severity, confidence=0.9,
        status=EvidenceStatus.DETECTED,
        summary="Earlier session risk compounds the current downstream action.",
        evidence=[f"Prior session risk: {prior_risk:.1f}; current action radius: {radius}"],
        limitations="Prototype accumulation is a transparent heuristic, not a learned causal model.",
    ))
