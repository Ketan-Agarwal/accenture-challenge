"""Constrained, exactly-once execution gateway for consequential AI actions.

The model may *propose* a refund, but only this gateway can authorize and
execute it.  Authorization is represented by a short-lived HMAC token bound
to the exact action arguments and policy version.  Action state and execution
receipts are persisted in SQLite so restarts cannot cause a replay.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from app.data_store import BusinessData
from app.models import Decision, EvaluationRequest, EvaluationResult


class ActionStatus(StrEnum):
    BLOCKED = "blocked"
    PENDING_REVIEW = "pending_review"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class GatewayError(RuntimeError):
    """Base class for errors safe for an API adapter to translate."""


class ProposalError(GatewayError):
    pass


class ActionNotFound(GatewayError):
    pass


class InvalidActionState(GatewayError):
    pass


class InvalidAuthorization(GatewayError):

    pass


class AuthorizationExpired(InvalidAuthorization):
    pass


class ActionReview(BaseModel):
    approve: bool
    corrected_amount_inr: Decimal | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=1000)


class ActionRecord(BaseModel):
    action_id: str
    audit_id: str
    action_type: str
    order_id: str
    amount_inr: Decimal
    policy_version: str
    status: ActionStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    review_note: str = ""


class AuthorizationResult(BaseModel):
    action: ActionRecord
    authorization_token: str | None = None


class RefundReceipt(BaseModel):
    refund_id: str
    action_id: str
    order_id: str
    amount_inr: Decimal
    policy_version: str
    executed_at: datetime


class CommerceOrder(BaseModel):
    order_id: str
    customer_id: str
    item: str
    order_total_inr: Decimal
    order_date: str
    status: str
    fulfilment_issue: str
    refunded_amount_inr: Decimal | None = None
    refund_action_id: str | None = None


_ORDER_PATTERN = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
_AMOUNT_PATTERN = re.compile(r"(?:INR|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_cents(value: Decimal | str | float) -> int:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ProposalError("Refund amount is not a valid monetary value.") from exc
    if amount <= 0:
        raise ProposalError("Refund amount must be greater than zero.")
    return int(amount * 100)


def _from_cents(value: int) -> Decimal:
    return (Decimal(value) / 100).quantize(Decimal("0.01"))


class ActionGateway:
    """Persistent gateway for proposing, reviewing and executing refunds."""

    def __init__(
        self,
        db_path: Path,
        data: BusinessData,
        secret: bytes | str,
        *,
        token_ttl_seconds: int = 30,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if token_ttl_seconds < 1:
            raise ValueError("token_ttl_seconds must be positive")
        secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(secret_bytes) < 16:
            raise ValueError("Action Gateway secret must be at least 16 bytes")
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = data
        self._secret = secret_bytes
        self._token_ttl = token_ttl_seconds
        self._clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS gateway_actions (
                    action_id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL UNIQUE,
                    action_type TEXT NOT NULL CHECK(action_type = 'issue_refund'),
                    order_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    policy_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'blocked', 'pending_review', 'authorized', 'executed',
                        'rejected', 'expired'
                    )),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    review_note TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_gateway_actions_status
                    ON gateway_actions(status, created_at DESC);
                CREATE TABLE IF NOT EXISTS gateway_refunds (
                    refund_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL UNIQUE REFERENCES gateway_actions(action_id),
                    order_id TEXT NOT NULL UNIQUE,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    policy_version TEXT NOT NULL,
                    executed_at TEXT NOT NULL
                );
                """
            )

    def propose_from_evaluation(
        self, request: EvaluationRequest, result: EvaluationResult
    ) -> AuthorizationResult | None:
        """Persist a structured proposal derived from a completed evaluation.

        Non-refund evaluations have no executable action and return ``None``.
        Repeated calls for the same audit ID return the original proposal.
        """
        if request.action != "issue_refund":
            return None
        order_id, amount_cents = self._parse_proposal(request, result)
        if order_id not in self.data.orders:
            raise ProposalError(f"Unknown order: {order_id}")

        self._expire_authorizations()
        existing = self._by_audit_id(result.audit_id)
        if existing:
            return AuthorizationResult(
                action=existing,
                authorization_token=self._token_for_record(existing)
                if existing.status == ActionStatus.AUTHORIZED
                else None,
            )

        now = _as_utc(self._clock())
        if result.decision == Decision.BLOCK:
            status = ActionStatus.BLOCKED
        elif result.decision == Decision.ALLOW:
            status = ActionStatus.AUTHORIZED
        else:
            status = ActionStatus.PENDING_REVIEW
        expires_at = now + timedelta(seconds=self._token_ttl) if status == ActionStatus.AUTHORIZED else None
        action_id = f"act_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO gateway_actions (
                    action_id, audit_id, action_type, order_id, amount_cents,
                    policy_version, status, created_at, updated_at, expires_at
                ) VALUES (?, ?, 'issue_refund', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action_id,
                    result.audit_id,
                    order_id,
                    amount_cents,
                    result.policy.version,
                    status,
                    now.isoformat(),
                    now.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                ),
            )
        action = self.get_action(action_id)
        return AuthorizationResult(
            action=action,
            authorization_token=self._token_for_record(action)
            if action.status == ActionStatus.AUTHORIZED
            else None,
        )

    def list_actions(self, *, status: ActionStatus | None = None) -> list[ActionRecord]:
        self._expire_authorizations()
        query = "SELECT * FROM gateway_actions"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (str(status),)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._action_from_row(row) for row in rows]

    def get_action(self, action_id: str) -> ActionRecord:
        self._expire_authorizations(action_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
        if row is None:
            raise ActionNotFound(action_id)
        return self._action_from_row(row)

    def review(self, action_id: str, review: ActionReview) -> AuthorizationResult:
        """Approve/correct a held proposal or reject it permanently."""
        now = _as_utc(self._clock())
        corrected_cents = (
            _to_cents(review.corrected_amount_inr)
            if review.corrected_amount_inr is not None
            else None
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM gateway_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                raise ActionNotFound(action_id)
            if row["status"] != ActionStatus.PENDING_REVIEW:
                raise InvalidActionState(
                    f"Only pending_review actions can be reviewed; current status is {row['status']}."
                )
            amount_cents = corrected_cents or int(row["amount_cents"])
            status = ActionStatus.AUTHORIZED if review.approve else ActionStatus.REJECTED
            expires_at = now + timedelta(seconds=self._token_ttl) if review.approve else None
            connection.execute(
                """UPDATE gateway_actions
                   SET amount_cents = ?, status = ?, updated_at = ?, expires_at = ?, review_note = ?
                   WHERE action_id = ?""",
                (
                    amount_cents,
                    status,
                    now.isoformat(),
                    expires_at.isoformat() if expires_at else None,
                    review.note,
                    action_id,
                ),
            )
        action = self.get_action(action_id)
        return AuthorizationResult(
            action=action,
            authorization_token=self._token_for_record(action) if review.approve else None,
        )

    def execute(
        self, authorization_token: str, *, expected_action_id: str | None = None
    ) -> RefundReceipt:
        """Execute an authorized action exactly once and return its receipt.

        Replaying a still-valid token is idempotent: it returns the same receipt
        and never creates a second refund.
        """
        payload = self._verify_token(authorization_token)
        action_id = str(payload["action_id"])
        if expected_action_id is not None and action_id != expected_action_id:
            raise InvalidAuthorization(
                "Authorization token does not belong to the requested action."
            )
        now = _as_utc(self._clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM gateway_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if row is None:
                raise ActionNotFound(action_id)
            self._assert_token_binds(payload, row)

            receipt_row = connection.execute(
                "SELECT * FROM gateway_refunds WHERE action_id = ?", (action_id,)
            ).fetchone()
            if receipt_row is not None:
                return self._receipt_from_row(receipt_row)

            expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
            if expires_at is None or now >= expires_at:
                connection.execute(
                    "UPDATE gateway_actions SET status = 'expired', updated_at = ? WHERE action_id = ?",
                    (now.isoformat(), action_id),
                )
                raise AuthorizationExpired("Authorization token has expired.")
            if row["status"] != ActionStatus.AUTHORIZED:
                raise InvalidActionState(f"Action is {row['status']}, not authorized.")

            existing_order_refund = connection.execute(
                "SELECT action_id FROM gateway_refunds WHERE order_id = ?", (row["order_id"],)
            ).fetchone()
            source_order = self.data.orders[row["order_id"]]
            if existing_order_refund or source_order["status"] == "refunded":
                raise InvalidActionState(f"Order {row['order_id']} has already been refunded.")

            refund_id = f"ref_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO gateway_refunds (
                    refund_id, action_id, order_id, amount_cents, policy_version, executed_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    refund_id,
                    action_id,
                    row["order_id"],
                    row["amount_cents"],
                    row["policy_version"],
                    now.isoformat(),
                ),
            )
            connection.execute(
                "UPDATE gateway_actions SET status = 'executed', updated_at = ? WHERE action_id = ?",
                (now.isoformat(), action_id),
            )
            receipt_row = connection.execute(
                "SELECT * FROM gateway_refunds WHERE refund_id = ?", (refund_id,)
            ).fetchone()
        return self._receipt_from_row(receipt_row)

    def list_orders(self) -> list[CommerceOrder]:
        """Overlay persisted executions on the immutable demo order system."""
        with self._connect() as connection:
            refunds = {
                row["order_id"]: row
                for row in connection.execute("SELECT * FROM gateway_refunds").fetchall()
            }
        orders: list[CommerceOrder] = []
        for raw in self.data.orders.values():
            refund = refunds.get(raw["order_id"])
            values = dict(raw)
            if refund:
                values["status"] = "refunded"
                values["refunded_amount_inr"] = _from_cents(refund["amount_cents"])
                values["refund_action_id"] = refund["action_id"]
            orders.append(CommerceOrder.model_validate(values))
        return orders

    def _parse_proposal(
        self, request: EvaluationRequest, result: EvaluationResult
    ) -> tuple[str, int]:
        response = result.safe_response or result.original_response or request.proposed_response or ""
        combined = f"{request.prompt} {response}"
        order_match = _ORDER_PATTERN.search(combined)
        amount_match = _AMOUNT_PATTERN.search(response) or _AMOUNT_PATTERN.search(request.prompt)
        if not order_match or not amount_match:
            raise ProposalError(
                "issue_refund requires a structured ORD-#### identifier and INR/₹ amount."
            )
        order_id = order_match.group(0).upper()
        return order_id, _to_cents(amount_match.group(1).replace(",", ""))

    def _by_audit_id(self, audit_id: str) -> ActionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM gateway_actions WHERE audit_id = ?", (audit_id,)
            ).fetchone()
        return self._action_from_row(row) if row else None

    def _expire_authorizations(self, action_id: str | None = None) -> None:
        now = _as_utc(self._clock()).isoformat()
        query = """UPDATE gateway_actions SET status = 'expired', updated_at = ?
                   WHERE status = 'authorized' AND expires_at <= ?"""
        params: tuple[str, ...] = (now, now)
        if action_id:
            query += " AND action_id = ?"
            params += (action_id,)
        with self._connect() as connection:
            connection.execute(query, params)

    def _token_for_record(self, action: ActionRecord) -> str:
        if action.expires_at is None:
            raise InvalidActionState("Cannot issue a token without an expiry.")
        payload = {
            "action_id": action.action_id,
            "order_id": action.order_id,
            "amount_cents": _to_cents(action.amount_inr),
            "policy_version": action.policy_version,
            "exp": int(action.expires_at.timestamp()),
        }
        encoded = self._b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = self._b64encode(hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def _verify_token(self, token: str) -> dict[str, object]:
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected = self._b64encode(
                hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected):
                raise InvalidAuthorization("Authorization signature is invalid.")
            payload = json.loads(self._b64decode(encoded))
            required = {"action_id", "order_id", "amount_cents", "policy_version", "exp"}
            if not isinstance(payload, dict) or not required.issubset(payload):
                raise InvalidAuthorization("Authorization payload is incomplete.")
            if int(payload["exp"]) <= int(_as_utc(self._clock()).timestamp()):
                self._mark_expired(str(payload["action_id"]))
                raise AuthorizationExpired("Authorization token has expired.")
            return payload
        except (
            ValueError,
            TypeError,
            binascii.Error,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            if isinstance(exc, GatewayError):
                raise
            raise InvalidAuthorization("Authorization token is malformed.") from exc

    def _assert_token_binds(self, payload: dict[str, object], row: sqlite3.Row) -> None:
        expected = {
            "action_id": row["action_id"],
            "order_id": row["order_id"],
            "amount_cents": row["amount_cents"],
            "policy_version": row["policy_version"],
            "exp": int(datetime.fromisoformat(row["expires_at"]).timestamp()),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise InvalidAuthorization("Authorization does not match the persisted action.")

    def _mark_expired(self, action_id: str) -> None:
        now = _as_utc(self._clock()).isoformat()
        with self._connect() as connection:
            connection.execute(
                """UPDATE gateway_actions SET status = 'expired', updated_at = ?
                   WHERE action_id = ? AND status = 'authorized'""",
                (now, action_id),
            )

    @staticmethod
    def _b64encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _b64decode(value: str) -> str:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding).decode("utf-8")

    @staticmethod
    def _action_from_row(row: sqlite3.Row) -> ActionRecord:
        return ActionRecord(
            action_id=row["action_id"],
            audit_id=row["audit_id"],
            action_type=row["action_type"],
            order_id=row["order_id"],
            amount_inr=_from_cents(row["amount_cents"]),
            policy_version=row["policy_version"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            review_note=row["review_note"],
        )

    @staticmethod
    def _receipt_from_row(row: sqlite3.Row) -> RefundReceipt:
        return RefundReceipt(
            refund_id=row["refund_id"],
            action_id=row["action_id"],
            order_id=row["order_id"],
            amount_inr=_from_cents(row["amount_cents"]),
            policy_version=row["policy_version"],
            executed_at=datetime.fromisoformat(row["executed_at"]),
        )
