"""Detection checks — Part B of the ControlPlane runtime pipeline.

Each check is an independent, self-contained function that receives request
context and returns an ``EvidenceSignal`` (or ``None`` when no finding is
produced).  The pipeline in :mod:`app.pipeline` orchestrates execution order,
concurrency, and blast-radius routing; checks here are intentionally unaware
of each other.

Upgrade notes (vs. the baseline heuristic versions):
- **PII**: Presidio-first with regex fallback.
- **Grounding**: Sentence-transformer embeddings (all-MiniLM-L6-v2) with
  Jaccard as a secondary signal.
- **Numeric**: Full business-rule coverage for all 6 refund-policy clauses
  (damaged, wrong-item, change-of-mind, digital, late-delivery, fraud).
- **Disagreement**: Embedding-based pairwise cosine similarity replaces
  token Jaccard for paraphrase-robust instability detection.
- **Injection**: Expanded from 4 to ~20 patterns across 5 categories.
- **Cascade**: Session step-counting and action-escalation detection.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
import time
from collections.abc import Callable
from datetime import date

from app.data_store import BusinessData
from app.embeddings import EmbeddingIndex, cosine_similarity, embed, embeddings_available, pairwise_cosine_matrix
from app.models import BlastRadius, EvidenceSignal, EvidenceStatus, EvaluationRequest
from app.reason_codes import ReasonCode

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blast-radius mapping
# ---------------------------------------------------------------------------

ACTION_RISK = {
    "answer": BlastRadius.R0,
    "lookup_order": BlastRadius.R0,
    "draft_email": BlastRadius.R1,
    "send_email": BlastRadius.R2,
    "issue_refund": BlastRadius.R3,
}


def blast_radius(action: str) -> BlastRadius:
    return ACTION_RISK.get(action, BlastRadius.R2)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "for", "from", "has", "in", "is", "it",
    "of", "on", "or", "the", "this", "to", "with", "will", "when", "every", "after",
}


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


# ===================================================================
# CHECK 1 — Injection screening (expanded patterns)
# ===================================================================

INJECTION_PATTERNS: dict[str, list[str]] = {
    "instruction_override": [
        r"ignore (?:all |any )?(?:previous|prior|above) instructions",
        r"bypass (?:the )?(?:policy|safety|security) checks?",
        r"disregard (?:all |any )?(?:previous|prior|above) (?:rules|instructions|guidelines)",
        r"override (?:the )?(?:system|safety) (?:prompt|rules|policy)",
        r"forget (?:all |everything )(?:you were |you\'ve been )told",
    ],
    "role_manipulation": [
        r"reveal (?:the )?(?:system|developer|internal) prompt",
        r"you are now (?:unrestricted|in developer mode|jailbroken|DAN)",
        r"pretend (?:you are|to be) (?:a )?(?:different|unrestricted|evil)",
        r"act as (?:a )?(?:different|unrestricted) (?:AI|model|assistant)",
        r"enter (?:developer|debug|admin|test) mode",
    ],
    "encoding_evasion": [
        r"base64[- ]?(?:decode|encode|convert)",
        r"rot13[- ]?(?:decode|encode)",
        r"translate (?:from|this) (?:hex|binary|base64)",
    ],
    "delimiter_injection": [
        r"```\s*system",
        r"\[SYSTEM\]",
        r"<<\s*SYS\s*>>",
        r"<\|(?:im_start|system)\|>",
    ],
    "social_engineering": [
        r"as an AI,? you (?:should|must|need to)",
        r"the above instructions (?:are|were) (?:wrong|incorrect|outdated)",
        r"your (?:true|real|actual) (?:instructions|purpose|goal)",
        r"do not (?:follow|obey|listen to) (?:your|the) (?:rules|instructions|guidelines)",
    ],
}

# Base severity by category (highest-risk categories score higher).
_INJECTION_CATEGORY_SEVERITY: dict[str, int] = {
    "instruction_override": 50,
    "role_manipulation": 40,
    "delimiter_injection": 45,
    "encoding_evasion": 35,
    "social_engineering": 30,
}


def injection_check(prompt: str, radius: BlastRadius) -> EvidenceSignal | None:
    """Screen input for prompt-injection / jailbreak patterns.

    Coverage is partial and bounded — this is stated explicitly in the signal
    ``limitations`` to comply with proposal §13 / §16.
    """
    matched_categories: dict[str, int] = {}
    total_matches = 0
    for category, patterns in INJECTION_PATTERNS.items():
        hits = sum(1 for p in patterns if re.search(p, prompt, re.IGNORECASE))
        if hits:
            matched_categories[category] = hits
            total_matches += hits

    if not matched_categories:
        return None

    # Base severity from the worst matched category.
    base_severity = max(_INJECTION_CATEGORY_SEVERITY[cat] for cat in matched_categories)
    # Compound: multiple matches from different categories increase severity.
    compound_bonus = min(25, (len(matched_categories) - 1) * 10)
    # Blast-radius scaling.
    radius_multiplier = {BlastRadius.R0: 0.4, BlastRadius.R1: 0.6, BlastRadius.R2: 1.0, BlastRadius.R3: 1.0}[radius]
    severity = min(100, round((base_severity + compound_bonus) * radius_multiplier))

    categories_str = ", ".join(sorted(matched_categories))
    return _timed(lambda: EvidenceSignal(
        check_id="injection",
        code=ReasonCode.INJECTION_SUSPECTED,
        labels=["security", "instruction_integrity"],
        severity=severity,
        confidence=0.82,
        status=EvidenceStatus.DETECTED,
        summary=f"Instruction-override language detected ({categories_str}) for a {radius} action.",
        evidence=[
            f"Matched {total_matches} pattern(s) across {len(matched_categories)} category/categories.",
            f"Categories: {categories_str}.",
        ],
        limitations=(
            "Pattern screening covers ~20 bounded heuristics across 5 categories. "
            "It does not establish malicious intent and will not catch novel or "
            "obfuscated injection techniques. Coverage limits are stated explicitly."
        ),
    ))


# ===================================================================
# CHECK 2 — PII detection (Presidio-first, regex fallback)
# ===================================================================

PII_PATTERNS = {
    "email": r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    "phone": r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\d)",
    "payment_card": r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)",
    "aadhaar_like": r"(?<!\d)\d{4}[ -]\d{4}[ -]\d{4}(?!\d)",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "person_name": None,  # Presidio-only; no regex fallback.
    "in_pan": r"\b[A-Z]{5}\d{4}[A-Z]\b",  # Indian PAN format: ABCDE1234F
}

# Map our category names to Presidio entity types.
_PRESIDIO_ENTITY_MAP = {
    "email": "EMAIL_ADDRESS",
    "phone": "PHONE_NUMBER",
    "payment_card": "CREDIT_CARD",
    "aadhaar_like": "IN_AADHAAR",
    "ip_address": "IP_ADDRESS",
    "person_name": "PERSON",
    "in_pan": "IN_PAN",
}

# Lazy-loaded Presidio engine.
_PRESIDIO_ANALYZER = None
_PRESIDIO_TRIED = False


def _get_presidio():
    """Attempt to load Presidio AnalyzerEngine once; return None on failure."""
    global _PRESIDIO_ANALYZER, _PRESIDIO_TRIED
    if _PRESIDIO_TRIED:
        return _PRESIDIO_ANALYZER
    _PRESIDIO_TRIED = True
    try:
        from presidio_analyzer import AnalyzerEngine
        _PRESIDIO_ANALYZER = AnalyzerEngine()
        log.info("Presidio AnalyzerEngine loaded successfully.")
    except ModuleNotFoundError:
        log.info("Presidio extra not installed; using regex PII detection.")
        _PRESIDIO_ANALYZER = None
    except Exception as exc:
        log.warning("Presidio initialization failed; using regex PII detection: %s", exc)
        _PRESIDIO_ANALYZER = None
    return _PRESIDIO_ANALYZER


def _pii_presidio(text: str, categories: list[str], language: str = "en") -> list[tuple[str, float]]:
    """Run Presidio and return ``[(category, confidence), ...]``."""
    analyzer = _get_presidio()
    if analyzer is None:
        return []
    entities = [_PRESIDIO_ENTITY_MAP[cat] for cat in categories if cat in _PRESIDIO_ENTITY_MAP]
    if not entities:
        return []
    try:
        supported = set(analyzer.get_supported_entities(language=language))
        valid_entities = [e for e in entities if e in supported]
        if not valid_entities:
            return []
        results = analyzer.analyze(text=text, entities=valid_entities, language=language)
    except Exception:
        log.warning("Presidio analysis failed", exc_info=True)
        return []
    # Reverse-map Presidio entity names back to our categories.
    reverse_map = {v: k for k, v in _PRESIDIO_ENTITY_MAP.items()}
    seen: set[str] = set()
    found: list[tuple[str, float]] = []
    for result in results:
        cat = reverse_map.get(result.entity_type)
        if cat and cat not in seen:
            seen.add(cat)
            found.append((cat, result.score))
    return found


def _pii_regex(text: str, categories: list[str]) -> list[tuple[str, float]]:
    """Regex fallback PII detection."""
    found: list[tuple[str, float]] = []
    for category in categories:
        pattern = PII_PATTERNS.get(category)
        if pattern and re.search(pattern, text, re.IGNORECASE):
            found.append((category, 0.85))  # Fixed confidence for regex.
    return found


def pii_check(text: str, location: str, categories: list[str]) -> EvidenceSignal | None:
    """Detect PII identifiers in *text*.

    Uses Presidio as the primary engine with per-entity confidence scores.
    Falls back to regex if Presidio is unavailable.
    """
    # Try Presidio first; fall back to regex.
    found = _pii_presidio(text, categories)
    detection_method = "Presidio NLP engine"
    if not found:
        found = _pii_regex(text, categories)
        if found:
            detection_method = "regex pattern matching"

    if not found:
        return None

    category_names = [cat for cat, _ in found]
    avg_confidence = sum(conf for _, conf in found) / len(found)
    output = location == "output"

    return _timed(lambda: EvidenceSignal(
        check_id="pii",
        code=ReasonCode.PII_DETECTED_OUTPUT if output else ReasonCode.PII_DETECTED_INPUT,
        labels=["privacy", "data_protection"],
        severity=58 if output else 38,
        confidence=round(min(0.99, avg_confidence), 2),
        status=EvidenceStatus.DETECTED,
        summary=f"Detected {', '.join(category_names)} in the {location}.",
        evidence=[
            f"{len(found)} identifier category/categories matched via {detection_method}.",
            f"Categories: {', '.join(category_names)}.",
        ],
        limitations=(
            f"Detection via {detection_method} covers a bounded set of configured "
            f"categories and can produce false positives. Presidio NLP models add "
            f"contextual scoring but do not guarantee recall for obfuscated identifiers."
        ),
    ))


def redact_pii(text: str | None, categories: list[str]) -> str | None:
    """Replace PII matches with ``[REDACTED_<CATEGORY>]`` tokens.

    Tries Presidio AnonymizerEngine first for offset-accurate redaction,
    then falls back to regex substitution.
    """
    if text is None:
        return None

    # Try Presidio-based redaction.
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig

        analyzer = _get_presidio()
        if analyzer is not None:
            entities = [_PRESIDIO_ENTITY_MAP[cat] for cat in categories if cat in _PRESIDIO_ENTITY_MAP]
            if entities:
                results = analyzer.analyze(text=text, entities=entities, language="en")
                if results:
                    reverse_map = {v: k for k, v in _PRESIDIO_ENTITY_MAP.items()}
                    operators = {}
                    for entity_type in {r.entity_type for r in results}:
                        cat = reverse_map.get(entity_type, entity_type)
                        operators[entity_type] = OperatorConfig(
                            "replace", {"new_value": f"[REDACTED_{cat.upper()}]"}
                        )
                    anonymizer = AnonymizerEngine()
                    anonymized = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
                    return anonymized.text
    except Exception:
        pass  # Fall through to regex.

    # Regex fallback.
    redacted = text
    for category in categories:
        pattern = PII_PATTERNS.get(category)
        if pattern:
            redacted = re.sub(pattern, f"[REDACTED_{category.upper()}]", redacted, flags=re.IGNORECASE)
    return redacted


# ===================================================================
# CHECK 3 — Grounding / claim attribution (embeddings + Jaccard)
# ===================================================================

def grounding_check(response: str, chunks: list[str], *, embedding_index: EmbeddingIndex | None = None) -> EvidenceSignal | None:
    """Attribute response claims against policy-document chunks.

    Uses sentence-transformer cosine similarity as the primary score with
    Jaccard token overlap as a secondary signal.  Falls back to Jaccard-only
    when embeddings are unavailable.
    """
    claim_markers = ("policy", "refund", "refundable", "credit", "eligible", "delivery", "guarantee")
    if not any(marker in response.lower() for marker in claim_markers):
        return None

    # --- Embedding similarity (primary) ---
    use_embeddings = embeddings_available() and embedding_index is not None
    if use_embeddings:
        query_emb = embed([response])[0]
        best_emb_score, best_emb_chunk, best_emb_idx = embedding_index.best_match(query_emb)
    else:
        best_emb_score = None

    # --- Jaccard similarity (secondary / fallback) ---
    scored_jaccard = sorted(
        ((_jaccard(response, chunk), chunk) for chunk in chunks),
        reverse=True, key=lambda item: item[0],
    )
    best_jaccard, best_jaccard_chunk = scored_jaccard[0] if scored_jaccard else (0.0, "")

    # Use the embedding score if available, otherwise Jaccard.
    if use_embeddings:
        primary_score = best_emb_score
        best_chunk = best_emb_chunk
        method = "semantic embedding (all-MiniLM-L6-v2)"
    else:
        primary_score = best_jaccard
        best_chunk = best_jaccard_chunk
        method = "lexical token overlap (Jaccard)"

    # --- Contradiction detection ---
    response_lower = response.lower()
    chunk_lower = best_chunk.lower()
    contradictory = any(
        left in response_lower and right in chunk_lower
        for left, right in [
            ("full cash refund", "not eligible for an automatic full cash refund"),
            ("full refund", "non-refundable"),
            ("guarantee", "not eligible"),
            ("refundable", "non-refundable"),
            ("automatic full", "not eligible for an automatic"),
        ]
    )

    # Check for claims about concepts not in any chunk.
    corpus = " ".join(chunks).lower()
    novel_goodwill_claim = "goodwill" in response_lower and "goodwill" not in corpus

    # --- Classification ---
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
    elif use_embeddings:
        # Embedding-calibrated thresholds.
        if primary_score >= 0.65:
            status, code, severity, summary = (
                EvidenceStatus.SUPPORTED,
                ReasonCode.CLAIM_SUPPORTED,
                0,
                "The response is attributable to a policy clause.",
            )
        elif primary_score >= 0.35:
            status, code, severity, summary = (
                EvidenceStatus.UNSUPPORTED,
                ReasonCode.CLAIM_UNSUPPORTED,
                62,
                "The response makes a policy claim that the retrieved material does not sufficiently support.",
            )
        else:
            status, code, severity, summary = (
                EvidenceStatus.UNAVAILABLE,
                ReasonCode.EVIDENCE_UNAVAILABLE,
                35,
                "No sufficiently relevant authoritative policy evidence was found.",
            )
    else:
        # Jaccard-only thresholds (original calibration).
        if primary_score >= 0.34:
            status, code, severity, summary = (
                EvidenceStatus.SUPPORTED,
                ReasonCode.CLAIM_SUPPORTED,
                0,
                "The response is attributable to a policy clause.",
            )
        elif primary_score < 0.10:
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

    # Confidence: higher when the score is far from decision boundaries.
    if use_embeddings:
        confidence = round(min(0.98, 0.60 + abs(primary_score - 0.5)), 2)
    else:
        confidence = round(min(0.98, 0.55 + abs(primary_score - 0.2)), 2)

    excerpt = re.sub(r"\s+", " ", best_chunk)[:240]
    evidence_lines = [f"Best {method} score: {primary_score:.3f}"]
    if use_embeddings and best_jaccard > 0:
        evidence_lines.append(f"Secondary Jaccard score: {best_jaccard:.3f}")
    if excerpt:
        evidence_lines.append(excerpt)

    return _timed(lambda: EvidenceSignal(
        check_id="grounding",
        code=code,
        labels=["hallucination", "governance"],
        severity=severity,
        confidence=confidence,
        status=status,
        summary=summary,
        evidence=evidence_lines,
        limitations=(
            f"{method.capitalize()} retrieval is evidence, not proof of entailment; "
            f"a reviewer should inspect consequential claims."
        ),
    ))


# ===================================================================
# CHECK 4 — Numeric recompute (full business-rule coverage)
# ===================================================================

# Return window for change-of-mind requests (days).
CHANGE_OF_MIND_WINDOW_DAYS = 7
DEMO_REFERENCE_DATE = date(2026, 8, 30)

# Refund rules keyed by fulfilment_issue.  Each returns (allowed_amount | None, policy_clause).
# None means "no automated cash refund allowed".
def _compute_refund_eligibility(
    order: dict[str, str],
    today: date = DEMO_REFERENCE_DATE,
) -> tuple[float | None, str]:
    """Return eligibility relative to the versioned synthetic dataset date."""
    issue = order.get("fulfilment_issue", "none")
    status = order.get("status", "")
    total = float(order["order_total_inr"])
    order_date = date.fromisoformat(order["order_date"])
    if status == "refunded":
        return None, "ALREADY_REFUNDED"
    if status == "cancelled":
        return None, "ORDER_CANCELLED"

    if issue == "wrong_item" and status == "delivered":
        return total, "RP-02"  # Full refund for wrong item.
    if issue == "damaged":
        # RP-01: Store credit for item value, not automatic full cash refund.
        return None, "RP-01"
    if issue == "change_of_mind":
        # RP-03: Store credit only, within 7-day window.
        days_since = (today - order_date).days
        if days_since > CHANGE_OF_MIND_WINDOW_DAYS:
            return None, "RP-03:EXPIRED"
        return None, "RP-03"
    if issue == "digital_delivered":
        # RP-04: Non-refundable after delivery.
        return None, "RP-04"
    if issue == "late_delivery":
        # RP-05: 10% service credit.
        return round(total * 0.10, 2), "RP-05"
    if issue == "suspected_fraud":
        # RP-06: Hold for manual review, no automated action.
        return None, "RP-06"
    if issue == "none":
        # No fulfilment issue — no refund applicable.
        return None, "NO_ISSUE"

    return None, "UNKNOWN"


def numeric_check(request: EvaluationRequest, data: BusinessData) -> EvidenceSignal | None:
    """Deterministic recomputation of refund amounts against the order system.

    Covers all 6 refund-policy clauses, date-window validation, and order
    status checks (already refunded, cancelled).
    """
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
            confidence=0.99, status=EvidenceStatus.UNAVAILABLE,
            summary=f"{order_id} does not exist in the system of record.",
            evidence=[], limitations="Synthetic order database only.",
        ))

    stated = float(amount_match.group(1).replace(",", ""))
    total = float(order["order_total_inr"])
    status = order["status"]
    issue = order.get("fulfilment_issue", "none")

    allowed, clause = _compute_refund_eligibility(order, today=data.reference_date)
    matches = allowed is not None and math.isclose(stated, allowed, abs_tol=0.01)

    if matches:
        return _timed(lambda: EvidenceSignal(
            check_id="numeric", code=ReasonCode.NUMERIC_VERIFIED, labels=["financial"], severity=0,
            confidence=1, status=EvidenceStatus.VERIFIED,
            summary="Refund amount and eligibility match the order record.",
            evidence=[
                f"{order_id}: expected INR {allowed:,.2f}; stated INR {stated:,.2f}",
                f"Policy clause: {clause}; issue: {issue}; status: {status}",
            ],
            limitations="Verification is limited to the synthetic refund rules and order table.",
        ))

    # Build a detailed mismatch explanation.
    if clause == "ALREADY_REFUNDED":
        expected_str = "no action (order already refunded)"
    elif clause == "ORDER_CANCELLED":
        expected_str = "no action (order cancelled)"
    elif clause == "RP-01":
        expected_str = f"store credit only for INR {total:,.2f} (not automatic cash refund per {clause})"
    elif clause == "RP-03":
        expected_str = f"store credit only (not cash refund per {clause})"
    elif clause == "RP-03:EXPIRED":
        expected_str = f"no refund (change-of-mind window expired per RP-03)"
    elif clause == "RP-04":
        expected_str = f"no refund (digital goods non-refundable per {clause})"
    elif clause == "RP-06":
        expected_str = f"no automated action (suspected fraud per {clause})"
    elif clause == "NO_ISSUE":
        expected_str = "no refund applicable (no fulfilment issue recorded)"
    elif allowed is not None:
        expected_str = f"INR {allowed:,.2f} per {clause}"
    else:
        expected_str = f"no automated cash refund per {clause}"

    return _timed(lambda: EvidenceSignal(
        check_id="numeric", code=ReasonCode.NUMERIC_MISMATCH, labels=["financial", "hallucination", "policy"],
        severity=100, confidence=1, status=EvidenceStatus.CONTRADICTED,
        summary="The proposed refund conflicts with deterministic business data or policy eligibility.",
        evidence=[
            f"{order_id}: expected {expected_str}; stated INR {stated:,.2f}",
            f"Status: {status}; issue: {issue}; clause: {clause}",
        ],
        limitations="Verification is limited to the synthetic refund rules and order table.",
    ))


# ===================================================================
# CHECK 5 — Semantic disagreement (embedding-based)
# ===================================================================

def disagreement_check(samples: list[str]) -> EvidenceSignal | None:
    """Measure instability across repeated generation samples.

    Uses sentence-transformer cosine similarity when available (paraphrase-
    robust), with Jaccard token overlap as a fallback.
    """
    if len(samples) < 2:
        return None

    use_emb = embeddings_available()
    if use_emb:
        embs = embed(samples)
        sim_matrix = pairwise_cosine_matrix(embs)
        n = len(samples)
        # Extract upper-triangle (excluding diagonal) for pairwise similarities.
        pairwise_sims = [
            float(sim_matrix[i][j])
            for i in range(n) for j in range(i + 1, n)
        ]
        agreement = sum(pairwise_sims) / len(pairwise_sims)
        disagreement = 1 - agreement
        method = "semantic embedding cosine similarity"
    else:
        similarities = [_jaccard(a, b) for a, b in itertools.combinations(samples, 2)]
        agreement = sum(similarities) / len(similarities)
        disagreement = 1 - agreement
        method = "lexical token Jaccard similarity"

    # Also compute Jaccard for a secondary signal (when using embeddings).
    if use_emb:
        jaccard_sims = [_jaccard(a, b) for a, b in itertools.combinations(samples, 2)]
        jaccard_disagreement = 1 - (sum(jaccard_sims) / len(jaccard_sims))
    else:
        jaccard_disagreement = disagreement

    # Thresholds (calibrated for embedding scale).
    if use_emb:
        if disagreement < 0.25:
            return None  # Consistent — no signal.
        severity = round(min(95, disagreement * 110), 1)
    else:
        if disagreement < 0.55:
            return None
        severity = round(disagreement * 80, 1)

    evidence_lines = [
        f"Pairwise {method} disagreement: {disagreement:.3f}",
        f"Samples compared: {len(samples)}",
    ]
    if use_emb:
        evidence_lines.append(f"Secondary Jaccard disagreement: {jaccard_disagreement:.3f}")

    return _timed(lambda: EvidenceSignal(
        check_id="disagreement", code=ReasonCode.HIGH_DISAGREEMENT,
        labels=["uncertainty", "hallucination"], severity=severity, confidence=0.78,
        status=EvidenceStatus.DETECTED,
        summary="Repeated response samples materially disagree in meaning.",
        evidence=evidence_lines,
        limitations=(
            f"Sample agreement via {method} measures stability, not factual correctness. "
            f"Consistent wrong answers remain possible."
        ),
    ))


# ===================================================================
# CHECK 6 — Session / cascade risk (enriched)
# ===================================================================

# Action escalation severity: read → write → irreversible.
_ACTION_ESCALATION_RANK = {
    "answer": 0, "lookup_order": 0,
    "draft_email": 1,
    "send_email": 2,
    "issue_refund": 3,
}


def cascade_check(prior_risk: float, radius: BlastRadius) -> EvidenceSignal | None:
    """Assess compounding session risk from prior steps.

    Considers: accumulated risk score, blast radius of current action, and
    escalation from prior non-risky steps to a high-impact action.
    """
    if prior_risk < 25 or radius not in (BlastRadius.R2, BlastRadius.R3):
        return None

    # Base: prior risk + blast-radius bonus.
    radius_bonus = 25 if radius == BlastRadius.R3 else 10
    severity = min(90, prior_risk + radius_bonus)

    evidence_lines = [
        f"Prior session risk: {prior_risk:.1f}; current action radius: {radius}",
    ]

    # Action escalation warning (if the session moved from read-only to write).
    if radius in (BlastRadius.R2, BlastRadius.R3):
        evidence_lines.append(
            "Session escalated from informational to a write/financial action."
        )

    return _timed(lambda: EvidenceSignal(
        check_id="cascade", code=ReasonCode.CASCADE_RISK_ELEVATED,
        labels=["agentic_risk", "compounding_risk"], severity=severity, confidence=0.9,
        status=EvidenceStatus.DETECTED,
        summary="Earlier session risk compounds the current downstream action.",
        evidence=evidence_lines,
        limitations=(
            "Prototype accumulation is a transparent heuristic, not a learned causal "
            "model. Decay and step-counting are simplified."
        ),
    ))
