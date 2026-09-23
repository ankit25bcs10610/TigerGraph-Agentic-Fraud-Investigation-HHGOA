"""Case memory: the system's own finished investigations, retrieved for new ones.

Closed cases in the dataset are the bank's history. This store holds the
investigations *this agent* has concluded, so a later case on the same
customer, card or device starts from what was already learned. Records are
appended as JSON Lines (``CASE_MEMORY_PATH``) and, when TigerGraph is
configured, the same case is also written to the graph as an
``InvestigationCase`` vertex.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CaseMemory:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else None
        self._records: dict[str, dict[str, Any]] = {}
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    record = json.loads(line)
                    self._records[record["case_id"]] = record

    def remember(self, record: dict[str, Any]) -> None:
        self._records[record["case_id"]] = record
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    def related(self, *, case_id: str, customer_id: str, card_id: str, devices: set[str]) -> list[tuple[dict[str, Any], list[str]]]:
        matches = []
        for record in self._records.values():
            if record["case_id"] == case_id:
                continue
            reasons = []
            if record.get("customer_id") == customer_id:
                reasons.append(f"same customer {customer_id}")
            if card_id and record.get("card_id") == card_id:
                reasons.append(f"same card {card_id}")
            shared = devices & set(record.get("devices", []))
            if shared:
                reasons.append(f"shared device {', '.join(sorted(shared))}")
            if reasons:
                matches.append((record, reasons))
        return matches

    def __len__(self) -> int:
        return len(self._records)
