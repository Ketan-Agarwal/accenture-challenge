from __future__ import annotations

import json
from pathlib import Path

from app.models import Decision, PolicyView


ROOT = Path(__file__).resolve().parents[1]


class PolicyError(ValueError):
    pass


class PolicyStore:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "config" / "policies.json"
        self._raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate()

    def _validate(self) -> None:
        profiles = self._raw.get("profiles", {})
        overlays = self._raw.get("region_overlays", {})
        if not profiles or not overlays:
            raise PolicyError("At least one profile and region overlay are required")
        for name, profile in profiles.items():
            thresholds = profile.get("thresholds", {})
            ordered = [thresholds.get(key) for key in ("warn_or_edit", "hold_for_human", "block")]
            if any(value is None for value in ordered) or ordered != sorted(ordered):
                raise PolicyError(f"Thresholds for {name} must be ordered")
            if not set(profile.get("permitted_actions", [])):
                raise PolicyError(f"Profile {name} has no permitted actions")

    def resolve(self, profile_name: str, region: str) -> PolicyView:
        try:
            profile = self._raw["profiles"][profile_name]
        except KeyError as exc:
            raise PolicyError(f"Unknown use-case profile: {profile_name}") from exc
        try:
            overlay = self._raw["region_overlays"][region]
        except KeyError as exc:
            raise PolicyError(f"Unknown region overlay: {region}") from exc
        retention = min(profile["retention_days"], overlay["retention_cap_days"])
        return PolicyView(
            profile=profile_name,
            owner=profile["owner"],
            version=self._raw["active_version"],
            region=region,
            region_label=overlay["label"],
            risk_appetite=profile["risk_appetite"],
            latency_budget_ms=profile["latency_budget_ms"],
            permitted_actions=profile["permitted_actions"],
            checks=profile["checks"],
            weights=profile["weights"],
            thresholds=profile["thresholds"],
            disagreement_samples=profile["disagreement_samples"],
            uncertainty_default=Decision(profile["uncertainty_default"]),
            retention_days=retention,
            consent_required=overlay["consent_required"],
            pii_categories=overlay["pii_categories"],
        )

    def list_profiles(self) -> list[PolicyView]:
        return [self.resolve(name, region) for name in self._raw["profiles"] for region in self._raw["region_overlays"]]

