import pytest

from app.check_routing import build_check_plan
from app.decision_engine import decide, score_signals, summarize_decision
from app.models import BlastRadius, Decision, EvidenceSignal, EvidenceStatus, PolicyView
from app.policy import PolicyStore
from app.reason_codes import ReasonCode


def _policy(profile: str = "support_bot") -> PolicyView:
    return PolicyStore().resolve(profile, "IN")


def test_r0_support_bot_runs_grounding_not_numeric():
    plan = build_check_plan(_policy("support_bot"), BlastRadius.R0, "answer")
    assert plan.run_grounding is True
    assert plan.run_numeric is False
    assert plan.run_cascade is False


def test_r3_refund_agent_runs_full_verification():
    plan = build_check_plan(_policy("refund_agent"), BlastRadius.R3, "issue_refund")
    assert plan.run_grounding is True
    assert plan.run_numeric is True
    assert plan.run_disagreement is True
    assert plan.run_cascade is True
    assert plan.disagreement_sample_budget == 5


def test_refund_agent_r0_skips_numeric():
    plan = build_check_plan(_policy("refund_agent"), BlastRadius.R0, "answer")
    assert plan.run_grounding is True
    assert plan.run_numeric is False


def test_numeric_mismatch_hard_blocks_despite_low_score():
    signals = [
        EvidenceSignal(
            check_id="numeric",
            code=ReasonCode.NUMERIC_MISMATCH,
            labels=["financial"],
            severity=100,
            confidence=1,
            status=EvidenceStatus.CONTRADICTED,
            summary="Mismatch",
        )
    ]
    decision = decide(signals, score_signals(signals, {"numeric": 1}), {"warn_or_edit": 90, "hold_for_human": 95, "block": 99}, Decision.ALLOW, BlastRadius.R3, "INR 9999")
    assert decision is Decision.BLOCK


def test_decision_summary_mentions_top_findings():
    signals = [
        EvidenceSignal(
            check_id="pii",
            code=ReasonCode.PII_DETECTED_OUTPUT,
            labels=["privacy"],
            severity=58,
            confidence=0.9,
            status=EvidenceStatus.DETECTED,
            summary="Detected email in the output.",
        )
    ]
    summary = summarize_decision(Decision.WARN_OR_EDIT, signals, 46.0)
    assert "warn or edit" in summary
    assert "Detected email" in summary


def test_stale_policy_version_flagged():
    store = PolicyStore()
    view = store.resolve("support_bot", "IN", requested_version="2026.07.1")
    assert view.version_stale is True
    assert view.version == store.active_version


def test_unknown_policy_version_rejected():
    store = PolicyStore()
    with pytest.raises(Exception, match="Unknown policy version"):
        store.resolve("support_bot", "IN", requested_version="2099.01.1")
