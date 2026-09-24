"""Answer the agent's graph questions from the supplied CSV files.

Card and device identifiers are derived exactly as the TigerGraph loader
derives them (``scripts/prepare_graph_data.py``), so an investigation run on
CSVs and one run on the loaded graph refer to the same entities.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from backend.sources.base import (BURST_MIN_CUSTOMERS, BURST_SPAN_HOURS, COMMON_DEVICE_CUSTOMERS, RING_MAX_CARDS, RING_WINDOW,
                                  ClosedCaseRecord, Community, RingResult, Txn, clean, generic_device, parse_float, parse_time)
from scripts.prepare_graph_data import CARD_FIELDS, card_id as loader_card_id, device_profile


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split("|") if item.strip())


class CsvSource:
    name = "csv"

    def __init__(self, transactions_path: str | None, identity_path: str | None = None, closed_cases_path: str | None = None) -> None:
        self._txns: dict[str, Txn] = {}
        self._by_customer: dict[str, list[str]] = defaultdict(list)
        self._by_device: dict[str, list[str]] = defaultdict(list)
        self._by_card: dict[str, list[str]] = defaultdict(list)
        self._closed: list[ClosedCaseRecord] = []
        self._cards: set[str] = set()
        self._device_users: dict[str, int] = {}
        self._communities: dict[tuple[int, int], list[Community]] = {}
        devices: dict[str, tuple[str, dict[str, str]]] = {}
        if identity_path and Path(identity_path).exists():
            with Path(identity_path).open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    profile = device_profile(row)
                    if profile and row.get("TransactionID"):
                        devices[row["TransactionID"].strip()] = profile
        if transactions_path and Path(transactions_path).exists():
            self._load_transactions(Path(transactions_path), devices)
        if closed_cases_path and Path(closed_cases_path).exists():
            with Path(closed_cases_path).open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    if not row.get("case_id"):
                        continue
                    self._closed.append(ClosedCaseRecord(
                        case_id=row["case_id"].strip(), customer_id=(row.get("customer_id") or "").strip(),
                        card_id=(row.get("card_id") or "").strip(), outcome=(row.get("outcome") or "").strip(),
                        pattern=(row.get("pattern") or "").strip(), txn_ids=_split(row.get("txn_ids")),
                        connected_card_ids=_split(row.get("connected_card_ids")), exposure_usd=parse_float(row.get("exposure_usd")),
                        analyst_notes=(row.get("analyst_notes") or "").strip(), opened_at=(row.get("opened_at") or "").strip(),
                        first_fraud_txn_id=(row.get("first_fraud_txn_id") or "").strip(),
                    ))

    def _load_transactions(self, path: Path, devices: dict[str, tuple[str, dict[str, str]]]) -> None:
        pending: list[tuple[dict[str, str], tuple[str, ...] | None]] = []
        fingerprints: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if not row.get("TransactionID") or not row.get("customer_id"):
                    continue
                keep = {key: row.get(key, "") for key in ("TransactionID", "customer_id", "card_id", "ts", "TransactionAmt", "channel", "risk_score", "addr1", "P_emaildomain", "ProductCD", "device_profile_id", "id_15", "id_23", "id_34")}
                fingerprint = None
                if not keep["card_id"]:
                    values = tuple((row.get(field) or "").strip() for field in CARD_FIELDS)
                    fingerprint = values if any(values) else None
                    if fingerprint:
                        fingerprints[keep["customer_id"].strip()].add(fingerprint)
                pending.append((keep, fingerprint))
        ordinals = {(customer, fp): index for customer, fps in fingerprints.items() for index, fp in enumerate(sorted(fps), start=1)}
        for row, fingerprint in pending:
            stamp, amount = parse_time(row["ts"]), parse_float(row["TransactionAmt"])
            if stamp is None or amount is None:
                continue
            txn_id, customer = row["TransactionID"].strip(), row["customer_id"].strip()
            card = row["card_id"].strip() or (loader_card_id(customer, fingerprint, ordinals[(customer, fingerprint)]) if fingerprint else "")
            device_id, attributes = row["device_profile_id"].strip(), {}
            if txn_id in devices:
                device_id, attributes = devices[txn_id]
            txn = Txn(
                transaction_id=txn_id, customer_id=customer, card_id=card, ts=stamp, amount=abs(amount),
                channel=(row["channel"] or "").strip(), risk_score=parse_float(row["risk_score"]), region=clean(row["addr1"]),
                email=clean(row["P_emaildomain"]), product_code=clean(row["ProductCD"]), device_profile_id=clean(device_id),
                device_status=clean(attributes.get("device_status") or row["id_15"]), proxy_type=clean(attributes.get("proxy_type") or row["id_23"]),
                match_status=clean(attributes.get("match_status") or row["id_34"]), device_info=clean(attributes.get("device_info")),
            )
            self._txns[txn_id] = txn
            self._by_customer[customer].append(txn_id)
            if txn.device_profile_id:
                self._by_device[txn.device_profile_id].append(txn_id)
            if card:
                self._by_card[card].append(txn_id)
                self._cards.add(card)

    # --------------------------------------------------------------- tools

    def _device_customers(self, device_profile_id: str | None) -> int:
        if not device_profile_id:
            return 0
        if device_profile_id not in self._device_users:
            self._device_users[device_profile_id] = len({self._txns[txn].customer_id for txn in self._by_device.get(device_profile_id, [])})
        return self._device_users[device_profile_id]

    def transaction(self, transaction_id: str) -> Txn | None:
        txn = self._txns.get(transaction_id)
        return replace(txn, device_customers=self._device_customers(txn.device_profile_id)) if txn and txn.device_profile_id else txn

    def customer_transactions(self, customer_id: str) -> list[Txn]:
        return sorted((self._txns[txn] for txn in self._by_customer.get(customer_id, [])), key=lambda item: (item.ts, item.transaction_id))

    def device_transactions(self, device_profile_id: str) -> list[Txn]:
        users = self._device_customers(device_profile_id)
        return sorted((replace(self._txns[txn], device_customers=users) for txn in self._by_device.get(device_profile_id, [])), key=lambda item: (item.ts, item.transaction_id))

    def linked_closed_cases(self, customer_id: str, card_id: str, related_customers: set[str], related_txns: set[str]) -> list[ClosedCaseRecord]:
        linked = []
        for case in self._closed:
            if case.customer_id == customer_id or (card_id and (case.card_id == card_id or card_id in case.connected_card_ids)):
                linked.append(case)
            elif (case.customer_id and case.customer_id in related_customers) or set(case.txn_ids) & related_txns:
                linked.append(case)
        return linked

    def closed_cases_by_pattern(self, pattern: str, limit: int) -> list[ClosedCaseRecord]:
        return [case for case in self._closed if case.pattern == pattern][:limit]

    def device_ring(self, device_profile_id: str, max_hops: int, around: datetime | None = None) -> RingResult:
        """Bounded connected component over device <-> transaction <-> card links (same rules as agent_device_ring)."""
        start, end = (around - RING_WINDOW, around + RING_WINDOW) if around else (datetime.min, datetime.max)
        in_window = lambda txn: start <= self._txns[txn].ts <= end  # noqa: E731
        devices, cards, txns, skipped = set(), set(), set(), set()
        frontier_devices = {device_profile_id}
        hops = 0
        while frontier_devices and hops < max_hops:
            if hops == 0:  # the device under investigation: generic only if its customers are not concentrated in the window
                generic = {device for device in frontier_devices
                           if generic_device(self._device_customers(device), len({self._txns[txn].customer_id for txn in self._by_device.get(device, []) if in_window(txn)}),
                                             next((self._txns[txn].device_info for txn in self._by_device.get(device, [])), None))}
            else:
                generic = {device for device in frontier_devices if self._device_customers(device) > COMMON_DEVICE_CUSTOMERS}
            skipped |= generic
            frontier_devices -= generic
            devices |= frontier_devices
            if not frontier_devices:
                break
            hops += 1
            new_txns = {txn for device in frontier_devices for txn in self._by_device.get(device, []) if in_window(txn)} - txns
            txns |= new_txns
            new_cards = {self._txns[txn].card_id for txn in new_txns if self._txns[txn].card_id} - cards
            cards |= new_cards
            if len(cards) >= RING_MAX_CARDS:
                break
            card_txns = {txn for card in new_cards for txn in self._by_card.get(card, []) if in_window(txn)} - txns
            txns |= card_txns
            frontier_devices = {self._txns[txn].device_profile_id for txn in card_txns if self._txns[txn].device_profile_id} - devices - skipped
        customers = {self._txns[txn].customer_id for txn in txns}
        confirmed = sorted(case.case_id for case in self._closed if case.confirmed_fraud and (case.card_id in cards or set(case.txn_ids) & txns))
        return RingResult(device_profile_id, tuple(sorted(devices)), tuple(sorted(cards)), tuple(sorted(customers)), len(txns), tuple(confirmed), hops,
                          {"common_devices_skipped": len(skipped)})

    def _burst_devices(self) -> set[str]:
        """Devices that behave like one physical device serving several people in a burst (see agent_fraud_communities)."""
        burst = set()
        for device, txn_ids in self._by_device.items():
            users = {self._txns[txn].customer_id for txn in txn_ids}
            stamps = [self._txns[txn].ts for txn in txn_ids]
            if BURST_MIN_CUSTOMERS <= len(users) <= COMMON_DEVICE_CUSTOMERS and (max(stamps) - min(stamps)).total_seconds() <= BURST_SPAN_HOURS * 3600:
                burst.add(device)
        return burst

    def communities(self, min_customers: int, top_k: int) -> list[Community]:
        """Weakly connected components over card <-> burst-device links (union-find), computed once per arguments."""
        key = (min_customers, top_k)
        if key not in self._communities:
            self._communities[key] = self._components(min_customers, top_k)
        return self._communities[key]

    def _components(self, min_customers: int, top_k: int) -> list[Community]:
        parent: dict[str, str] = {}
        burst = self._burst_devices()

        def find(node: str) -> str:
            while parent.setdefault(node, node) != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for txn in self._txns.values():
            if txn.card_id and txn.device_profile_id in burst:
                left, right = find("card:" + txn.card_id), find("device:" + txn.device_profile_id)
                if left != right:
                    parent[max(left, right)] = min(left, right)
        groups: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"cards": set(), "devices": set(), "customers": set(), "txns": set()})
        for txn in self._txns.values():
            if not txn.card_id or "card:" + txn.card_id not in parent:
                continue
            group = groups[find("card:" + txn.card_id)]
            group["cards"].add(txn.card_id)
            group["customers"].add(txn.customer_id)
            group["txns"].add(txn.transaction_id)
            if txn.device_profile_id in burst:
                group["devices"].add(txn.device_profile_id)
        found = []
        for root, group in groups.items():
            if len(group["customers"]) < min_customers:
                continue
            confirmed = sorted(case.case_id for case in self._closed if case.confirmed_fraud and (set(case.txn_ids) & group["txns"] or case.customer_id in group["customers"]))
            found.append(Community(root, tuple(sorted(group["cards"])), tuple(sorted(group["devices"])), tuple(sorted(group["customers"])), tuple(confirmed), len(group["txns"]), len(group["customers"])))
        return sorted(found, key=lambda item: (-len(item.customers), -len(item.confirmed_cases)))[:top_k]

    def exists(self, entity_type: str, entity_id: str) -> bool:
        if entity_type == "Transaction":
            return entity_id in self._txns
        if entity_type == "Card":
            return entity_id in self._cards
        if entity_type == "Customer":
            return entity_id in self._by_customer
        if entity_type == "DeviceProfile":
            return entity_id in self._by_device
        if entity_type == "ClosedCase":
            return any(case.case_id == entity_id for case in self._closed)
        return False
