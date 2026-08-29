from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import EvaluationRequest, EvaluationResult, ReviewRequest
from app.policy import ROOT


class AuditRepository:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "controlplane.db"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS evaluations (
                    audit_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    scenario_id TEXT,
                    source TEXT NOT NULL DEFAULT 'runtime',
                    use_case TEXT NOT NULL,
                    region TEXT NOT NULL,
                    action TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    original_response TEXT,
                    safe_response TEXT,
                    blast_radius TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    risk_score REAL NOT NULL,
                    policy_version TEXT NOT NULL,
                    reason_codes TEXT NOT NULL,
                    signals TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    model_calls INTEGER NOT NULL,
                    expected_harmful INTEGER,
                    human_label TEXT,
                    human_decision TEXT,
                    review_note TEXT,
                    reviewed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_evaluations_session ON evaluations(session_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_evaluations_created ON evaluations(created_at DESC);
                """
            )

    def save(self, request: EvaluationRequest, result: EvaluationResult, source: str = "runtime") -> None:
        expected = None if request.expected_harmful is None else int(request.expected_harmful)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO evaluations (
                    audit_id, created_at, scenario_id, source, use_case, region, action, session_id,
                    prompt, original_response, safe_response, blast_radius, decision, risk_score,
                    policy_version, reason_codes, signals, latency_ms, model_calls, expected_harmful
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.audit_id, result.created_at.isoformat(), result.scenario_id, source,
                    result.use_case, result.region, result.action, result.session_id, request.prompt,
                    result.original_response, result.safe_response, result.blast_radius, result.decision,
                    result.risk_score, result.policy.version,
                    json.dumps([str(code) for code in result.reason_codes]),
                    json.dumps([signal.model_dump(mode="json") for signal in result.signals]),
                    result.total_latency_ms, result.check_cost["model_calls"], expected,
                ),
            )

    def session_risk(self, session_id: str) -> float:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(risk_score) AS max_risk FROM evaluations WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return float(row["max_risk"] or 0)

    def review(self, audit_id: str, review: ReviewRequest) -> dict[str, Any]:
        reviewed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT decision FROM evaluations WHERE audit_id = ?", (audit_id,)
            ).fetchone()
            if not existing:
                raise KeyError(audit_id)
            decision = str(review.decision) if review.decision else existing["decision"]
            connection.execute(
                """UPDATE evaluations
                   SET human_label = ?, human_decision = ?, review_note = ?, reviewed_at = ?
                   WHERE audit_id = ?""",
                (review.human_label, decision, review.note, reviewed_at, audit_id),
            )
        return {"audit_id": audit_id, "human_label": review.human_label, "decision": decision, "reviewed_at": reviewed_at}

    def recent(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT audit_id, created_at, scenario_id, source, use_case, region, action,
                          blast_radius, decision, risk_score, policy_version, reason_codes,
                          latency_ms, expected_harmful, human_label, human_decision, review_note
                   FROM evaluations ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["reason_codes"] = json.loads(record["reason_codes"])
            if record["expected_harmful"] is not None:
                record["expected_harmful"] = bool(record["expected_harmful"])
        return records

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT decision, latency_ms, model_calls, expected_harmful, human_label,
                          human_decision, source, use_case FROM evaluations"""
            ).fetchall()
        total = len(rows)
        decisions = {name: 0 for name in ("allow", "warn_or_edit", "hold_for_human", "block")}
        latencies: list[float] = []
        reviewed = overrides = model_calls = 0
        labeled: list[tuple[bool, bool]] = []
        by_profile: dict[str, dict[str, int]] = {}
        for row in rows:
            decisions[row["decision"]] = decisions.get(row["decision"], 0) + 1
            latencies.append(float(row["latency_ms"]))
            model_calls += int(row["model_calls"])
            if row["human_label"]:
                reviewed += 1
                overrides += int(bool(row["human_decision"] and row["human_decision"] != row["decision"]))
            truth = row["human_label"] == "unsafe" if row["human_label"] else (
                bool(row["expected_harmful"]) if row["expected_harmful"] is not None else None
            )
            predicted = row["decision"] != "allow"
            if truth is not None:
                labeled.append((predicted, truth))
            profile = by_profile.setdefault(row["use_case"], {"total": 0, "interventions": 0})
            profile["total"] += 1
            profile["interventions"] += int(predicted)
        tp = sum(predicted and truth for predicted, truth in labeled)
        fp = sum(predicted and not truth for predicted, truth in labeled)
        tn = sum(not predicted and not truth for predicted, truth in labeled)
        fn = sum(not predicted and truth for predicted, truth in labeled)
        def ratio(numerator: int, denominator: int) -> float | None:
            return round(numerator / denominator, 4) if denominator else None
        ordered = sorted(latencies)
        p95_index = max(0, math_ceil(0.95 * len(ordered)) - 1) if ordered else 0
        return {
            "volume": total,
            "decisions": decisions,
            "intervention_rate": ratio(total - decisions.get("allow", 0), total),
            "reviewed": reviewed,
            "override_rate": ratio(overrides, reviewed),
            "model_calls": model_calls,
            "latency_ms": {
                "median": round(ordered[len(ordered) // 2], 2) if ordered else None,
                "p95": round(ordered[p95_index], 2) if ordered else None,
            },
            "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "labeled": len(labeled)},
            "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn),
            "false_positive_rate": ratio(fp, fp + tn),
            "false_negative_rate": ratio(fn, fn + tp),
            "by_profile": by_profile,
            "metric_note": "Warn/edit, hold, and block count as predicted risky. Human labels supersede seeded labels.",
        }


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if integer == value else integer + 1

