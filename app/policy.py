from __future__ import annotations

import json
from pathlib import Path

from app.models import Decision, PolicyView


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PROFILE_FIELDS = (
    "owner",
    "risk_appetite",
    "latency_budget_ms",
    "permitted_actions",
    "checks",
    "weights",
    "thresholds",
    "disagreement_samples",
    "uncertainty_default",
    "retention_days",
)
REQUIRED_OVERLAY_FIELDS = ("label", "pii_categories", "consent_required", "retention_cap_days")
THRESHOLD_KEYS = ("warn_or_edit", "hold_for_human", "block")
BLAST_RADIUS_KEYS = ("R0", "R1", "R2", "R3")


class PolicyError(ValueError):
    pass


class PolicyStore:
    def __init__(self, path: Path | None = None):
        self.path = path or ROOT / "config" / "policies.json"
        self._raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._validate()

    @property
    def active_version(self) -> str:
        return self._raw["active_version"]

    @property
    def known_versions(self) -> list[str]:
        history = self._raw.get("version_history", [])
        versions = {self.active_version, *history}
        return sorted(versions)

    def _validate(self) -> None:
        if not self._raw.get("active_version"):
            raise PolicyError("active_version is required")
        profiles = self._raw.get("profiles", {})
        overlays = self._raw.get("region_overlays", {})
        if not profiles or not overlays:
            raise PolicyError("At least one profile and region overlay are required")

        for name, profile in profiles.items():
            missing = [field for field in REQUIRED_PROFILE_FIELDS if field not in profile]
            if missing:
                raise PolicyError(f"Profile {name} missing fields: {', '.join(missing)}")
            thresholds = profile["thresholds"]
            ordered = [thresholds.get(key) for key in THRESHOLD_KEYS]
            if any(value is None for value in ordered) or ordered != sorted(ordered):
                raise PolicyError(f"Thresholds for {name} must be ascending warn < hold < block")
            if not profile["permitted_actions"]:
                raise PolicyError(f"Profile {name} has no permitted actions")
            missing_weights = set(profile["checks"]) - set(profile["weights"])
            if missing_weights:
                raise PolicyError(f"Profile {name} checks missing weights: {sorted(missing_weights)}")
            missing_samples = set(BLAST_RADIUS_KEYS) - set(profile["disagreement_samples"])
            if missing_samples:
                raise PolicyError(f"Profile {name} missing disagreement_samples for {sorted(missing_samples)}")
            try:
                Decision(profile["uncertainty_default"])
            except ValueError as exc:
                raise PolicyError(f"Profile {name} has invalid uncertainty_default") from exc

        for region, overlay in overlays.items():
            missing = [field for field in REQUIRED_OVERLAY_FIELDS if field not in overlay]
            if missing:
                raise PolicyError(f"Region overlay {region} missing fields: {', '.join(missing)}")

    def resolve(
        self,
        profile_name: str,
        region: str,
        *,
        requested_version: str | None = None,
    ) -> PolicyView:
        try:
            profile = self._raw["profiles"][profile_name]
        except KeyError as exc:
            raise PolicyError(f"Unknown use-case profile: {profile_name}") from exc
        try:
            overlay = self._raw["region_overlays"][region]
        except KeyError as exc:
            raise PolicyError(f"Unknown region overlay: {region}") from exc

        active = self.active_version
        version = active
        version_stale = False
        if requested_version:
            if requested_version not in self.known_versions:
                raise PolicyError(f"Unknown policy version: {requested_version}")
            version_stale = requested_version != active
            version = active  # runtime always evaluates with the active version

        retention = min(profile["retention_days"], overlay["retention_cap_days"])
        return PolicyView(
            profile=profile_name,
            owner=profile["owner"],
            version=version,
            requested_version=requested_version,
            version_stale=version_stale,
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
        return [
            self.resolve(name, region)
            for name in self._raw["profiles"]
            for region in self._raw["region_overlays"]
        ]

    def version_info(self) -> dict[str, object]:
        history = self._raw.get("version_history", [])
        active = self.active_version
        return {
            "schema_version": self._raw.get("schema_version"),
            "active_version": active,
            "version_history": sorted({*history, active}),
            "superseded_versions": sorted(set(history) - {active}),
            "profiles": sorted(self._raw["profiles"]),
            "regions": sorted(self._raw["region_overlays"]),
        }
