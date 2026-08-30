from __future__ import annotations

import csv
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from app.embeddings import EmbeddingIndex
from app.policy import ROOT

log = logging.getLogger(__name__)


class BusinessData:
    def __init__(self, root: Path | None = None):
        self.root = root or ROOT / "data"
        metadata = self._read_json_object("dataset_metadata.json")
        self.reference_date = date.fromisoformat(metadata["reference_date"])
        with (self.root / "orders.csv").open(encoding="utf-8", newline="") as handle:
            self.orders = {row["order_id"]: row for row in csv.DictReader(handle)}
        policy_text = (self.root / "policy_docs" / "refund_policy_v1.md").read_text(encoding="utf-8")
        chunks = re.split(r"(?=^## )", policy_text, flags=re.MULTILINE)
        self.policy_chunks = [chunk.strip() for chunk in chunks if chunk.strip().startswith("##")]
        self.embedding_index = EmbeddingIndex(self.policy_chunks)
        log.info("BusinessData loaded: %d orders, %d policy chunks.", len(self.orders), len(self.policy_chunks))
        self.demo_scenarios = self._read_json("demo_scenarios.json")
        self.evaluation_scenarios = self._read_json("evaluation_scenarios.json")

    def _read_json(self, name: str) -> list[dict[str, Any]]:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def _read_json_object(self, name: str) -> dict[str, Any]:
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def scenario(self, scenario_id: str) -> dict[str, Any]:
        for scenario in self.demo_scenarios:
            if scenario["id"] == scenario_id:
                return scenario
        raise KeyError(scenario_id)
