from __future__ import annotations

from typing import Protocol

from app.models import EvaluationRequest


class ModelProvider(Protocol):
    def generate(self, request: EvaluationRequest) -> str: ...


class DeterministicDemoProvider:
    """Safe fallback for manual requests; seeded scenarios supply their own model output."""

    def generate(self, request: EvaluationRequest) -> str:
        return (
            "I do not have enough authoritative evidence to complete this request automatically. "
            "Please provide a governed source or route it for review."
        )

