from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.action_gateway import (
    ActionGateway,
    ActionReview,
    ActionStatus,
    AuthorizationExpired,
    InvalidActionState,
    InvalidAuthorization,
    ProposalError,
)
from app.data_store import BusinessData
from app.models import BlastRadius, Decision, EvaluationRequest, EvaluationResult
from app.policy import PolicyStore


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture()
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture()
def gateway(tmp_path: Path, clock: MutableClock) -> ActionGateway:
    return ActionGateway(
        tmp_path / "gateway.db",
        BusinessData(),
        "test-secret-is-long-enough",
        token_ttl_seconds=30,
        clock=clock,
    )


def evaluation(
    request: EvaluationRequest,
    decision: Decision,
    *,
    audit_id: str = "audit-1",
) -> EvaluationResult:
    policy = PolicyStore().resolve(request.use_case, request.region)
    return EvaluationResult(
        audit_id=audit_id,
        scenario_id=None,
        use_case=request.use_case,
        region=request.region,
        action=request.action,
        session_id=request.session_id,
        blast_radius=BlastRadius.R3 if request.action == "issue_refund" else BlastRadius.R0,
        policy=policy,
        decision=decision,
        risk_score=0,
        reason_codes=[],
        signals=[],
        original_response=request.proposed_response,
        safe_response=request.proposed_response,
        model_called=False,
        total_latency_ms=1,
        check_cost={"model_calls": 0},
    )


def refund_request(
    *,
    order_id: str = "ORD-1009",
    amount: str = "2,799",
    response: str | None = None,
) -> EvaluationRequest:
    return EvaluationRequest(
        use_case="refund_agent",
        action="issue_refund",
        prompt=f"Issue a refund for {order_id}.",
        proposed_response=response or f"I will issue INR {amount} for {order_id}.",
    )


def test_non_executable_evaluation_creates_no_action(gateway: ActionGateway) -> None:
    request = EvaluationRequest(prompt="Where is my order?", action="answer")

    assert gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW)) is None
    assert gateway.list_actions() == []


def test_allowed_refund_executes_exactly_once_and_updates_order_state(
    gateway: ActionGateway,
) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))

    assert proposed is not None
    assert proposed.action.status == ActionStatus.AUTHORIZED
    assert proposed.action.amount_inr == Decimal("2799.00")
    assert proposed.authorization_token

    first = gateway.execute(proposed.authorization_token)
    second = gateway.execute(proposed.authorization_token)

    assert first == second
    assert gateway.get_action(proposed.action.action_id).status == ActionStatus.EXECUTED
    order = next(item for item in gateway.list_orders() if item.order_id == "ORD-1009")
    assert order.status == "refunded"
    assert order.refunded_amount_inr == Decimal("2799.00")
    assert order.refund_action_id == proposed.action.action_id


def test_execution_survives_gateway_restart(
    gateway: ActionGateway, clock: MutableClock
) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))
    receipt = gateway.execute(proposed.authorization_token or "")

    restarted = ActionGateway(
        gateway.path,
        BusinessData(),
        "test-secret-is-long-enough",
        token_ttl_seconds=30,
        clock=clock,
    )

    assert restarted.execute(proposed.authorization_token or "") == receipt
    assert len([o for o in restarted.list_orders() if o.refund_action_id]) == 1


def test_blocked_action_has_no_authorization(gateway: ActionGateway) -> None:
    request = refund_request(order_id="ORD-1001", amount="2,499")
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.BLOCK))

    assert proposed.action.status == ActionStatus.BLOCKED
    assert proposed.authorization_token is None


@pytest.mark.parametrize("decision", [Decision.HOLD_FOR_HUMAN, Decision.WARN_OR_EDIT])
def test_intervened_action_requires_review(
    gateway: ActionGateway, decision: Decision
) -> None:
    request = refund_request(order_id="ORD-1001", amount="2,499")
    proposed = gateway.propose_from_evaluation(request, evaluation(request, decision))

    assert proposed.action.status == ActionStatus.PENDING_REVIEW
    assert proposed.authorization_token is None


def test_reviewer_can_correct_then_authorize_and_execute(gateway: ActionGateway) -> None:
    request = refund_request(order_id="ORD-1001", amount="2,499")
    proposed = gateway.propose_from_evaluation(
        request, evaluation(request, Decision.HOLD_FOR_HUMAN)
    )

    reviewed = gateway.review(
        proposed.action.action_id,
        ActionReview(
            approve=True,
            corrected_amount_inr=Decimal("1499"),
            note="Corrected to the system-of-record amount.",
        ),
    )
    receipt = gateway.execute(reviewed.authorization_token or "")

    assert reviewed.action.status == ActionStatus.AUTHORIZED
    assert reviewed.action.amount_inr == Decimal("1499.00")
    assert reviewed.action.review_note.startswith("Corrected")
    assert receipt.amount_inr == Decimal("1499.00")


def test_reviewer_can_reject_but_cannot_review_twice(gateway: ActionGateway) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(
        request, evaluation(request, Decision.HOLD_FOR_HUMAN)
    )

    rejected = gateway.review(
        proposed.action.action_id, ActionReview(approve=False, note="Customer withdrew request.")
    )

    assert rejected.action.status == ActionStatus.REJECTED
    assert rejected.authorization_token is None
    with pytest.raises(InvalidActionState):
        gateway.review(proposed.action.action_id, ActionReview(approve=True))


def test_tampered_token_is_rejected(gateway: ActionGateway) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))
    token = proposed.authorization_token or ""
    altered = token[:-1] + ("A" if token[-1] != "A" else "B")

    with pytest.raises(InvalidAuthorization):
        gateway.execute(altered)
    assert gateway.get_action(proposed.action.action_id).status == ActionStatus.AUTHORIZED


def test_token_is_bound_to_persisted_amount(gateway: ActionGateway) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))
    with sqlite3.connect(gateway.path) as connection:
        connection.execute(
            "UPDATE gateway_actions SET amount_cents = 1 WHERE action_id = ?",
            (proposed.action.action_id,),
        )

    with pytest.raises(InvalidAuthorization, match="does not match"):
        gateway.execute(proposed.authorization_token or "")


def test_token_cannot_execute_through_another_action_route(gateway: ActionGateway) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))

    with pytest.raises(InvalidAuthorization, match="requested action"):
        gateway.execute(
            proposed.authorization_token or "", expected_action_id="act_a-different-action"
        )


def test_expired_authorization_cannot_execute(
    gateway: ActionGateway, clock: MutableClock
) -> None:
    request = refund_request()
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))
    clock.advance(31)

    with pytest.raises(AuthorizationExpired):
        gateway.execute(proposed.authorization_token or "")
    assert gateway.get_action(proposed.action.action_id).status == ActionStatus.EXPIRED


def test_same_evaluation_does_not_create_duplicate_action(gateway: ActionGateway) -> None:
    request = refund_request()
    result = evaluation(request, Decision.ALLOW)

    first = gateway.propose_from_evaluation(request, result)
    second = gateway.propose_from_evaluation(request, result)

    assert first.action.action_id == second.action.action_id
    assert len(gateway.list_actions()) == 1


def test_reproposing_expired_evaluation_does_not_mint_a_new_token(
    gateway: ActionGateway, clock: MutableClock
) -> None:
    request = refund_request()
    result = evaluation(request, Decision.ALLOW)
    gateway.propose_from_evaluation(request, result)
    clock.advance(31)

    repeated = gateway.propose_from_evaluation(request, result)

    assert repeated.action.status == ActionStatus.EXPIRED
    assert repeated.authorization_token is None
    assert len(gateway.list_actions()) == 1


@pytest.mark.parametrize(
    ("evaluation_request", "message"),
    [
        (refund_request(response="I will issue the requested refund."), "requires a structured"),
        (refund_request(order_id="ORD-9999"), "Unknown order"),
    ],
)
def test_invalid_proposal_is_rejected(
    gateway: ActionGateway, evaluation_request: EvaluationRequest, message: str
) -> None:
    with pytest.raises(ProposalError, match=message):
        gateway.propose_from_evaluation(
            evaluation_request, evaluation(evaluation_request, Decision.ALLOW)
        )


def test_source_order_already_refunded_cannot_execute(gateway: ActionGateway) -> None:
    request = refund_request(order_id="ORD-1005", amount="8,999")
    proposed = gateway.propose_from_evaluation(request, evaluation(request, Decision.ALLOW))

    with pytest.raises(InvalidActionState, match="already been refunded"):
        gateway.execute(proposed.authorization_token or "")


def test_only_one_action_can_refund_an_order(gateway: ActionGateway) -> None:
    first_request = refund_request()
    first = gateway.propose_from_evaluation(
        first_request, evaluation(first_request, Decision.ALLOW, audit_id="audit-first")
    )
    gateway.execute(first.authorization_token or "")

    second_request = refund_request()
    second = gateway.propose_from_evaluation(
        second_request, evaluation(second_request, Decision.ALLOW, audit_id="audit-second")
    )
    with pytest.raises(InvalidActionState, match="already been refunded"):
        gateway.execute(second.authorization_token or "")


def test_list_actions_can_filter_status(gateway: ActionGateway) -> None:
    allowed = refund_request(order_id="ORD-1009")
    blocked = refund_request(order_id="ORD-1001", amount="2,499")
    gateway.propose_from_evaluation(allowed, evaluation(allowed, Decision.ALLOW, audit_id="a"))
    gateway.propose_from_evaluation(blocked, evaluation(blocked, Decision.BLOCK, audit_id="b"))

    records = gateway.list_actions(status=ActionStatus.BLOCKED)

    assert len(records) == 1
    assert records[0].status == ActionStatus.BLOCKED
