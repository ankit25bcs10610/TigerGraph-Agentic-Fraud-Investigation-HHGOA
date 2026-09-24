"""Fill in the dataset fields the live graph is missing, over TigerGraph MCP.

The graph that was loaded for the benchmark has every ClosedCase vertex, but
with empty attributes (the ClosedCase file never loaded: its columns did not
match the graph's schema, so the vertices exist only because edges point at
them). It also has no identity signals on transactions. Without these the
agent cannot learn from past outcomes, and the new-device and
account-takeover detectors can never fire.

This script, given the dataset folder:

1. upserts every ClosedCase's attributes from ``closed_cases_history.csv``;
2. adds ``device_status`` (id_15), ``proxy_type`` (id_23) and
   ``match_status`` (id_34) to Transaction (a schema change, once) and
   upserts them from ``identity.csv``;
3. adds the identity signals to the agent queries' projections (in
   ``tigergraph/queries``, so the repository matches the graph) and
   reinstalls them.

Everything goes through the official TigerGraph MCP server, the same way the
agent talks to the graph. Re-running it is safe: upserts overwrite.

    python scripts/load_dataset_to_graph.py --data-dir ~/Downloads/HHGOA_IEEE

Then rebuild the closed-case narratives for GraphRAG::

    python scripts/index_fraud_knowledge.py --readme ~/Downloads/HHGOA_IEEE/README.md --closed-case-limit 5565
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend.sources.base import parse_float, parse_time  # noqa: E402
from backend.sources.tigergraph_source import TigerGraphSource  # noqa: E402

IDENTITY_ATTRIBUTES = {"device_status": "id_15", "proxy_type": "id_23", "match_status": "id_34"}
AGENT_QUERIES = ["agent_txn_profile", "agent_customer_activity", "agent_device_activity"]


def batches(rows: Iterable[dict[str, Any]], size: int) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def stamp(value: str | None) -> str:
    parsed = parse_time(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else "1970-01-01 00:00:00"


def closed_case_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            case_id = (row.get("case_id") or "").strip()
            if not case_id:
                continue
            txn_ids = [item for item in (row.get("txn_ids") or "").split("|") if item.strip()]
            yield {
                "case_id": case_id,
                "customer_id": (row.get("customer_id") or "").strip(),
                "card_id": (row.get("card_id") or "").strip(),
                "opened_at": stamp(row.get("opened_at")),
                "closed_at": stamp(row.get("closed_at")),
                "outcome": (row.get("outcome") or "").strip(),
                "pattern": (row.get("pattern") or "").strip(),
                "first_fraud_txn_id": (row.get("first_fraud_txn_id") or "").strip(),
                "n_txns": int(parse_float(row.get("n_txns")) or len(txn_ids)),
                "exposure_usd": parse_float(row.get("exposure_usd")) or 0.0,
                "actions_taken": (row.get("actions_taken") or "").strip(),
                "report_filed": (row.get("report_filed") or "").strip().lower() in {"yes", "true", "1", "y"},
                "analyst_notes": (row.get("analyst_notes") or "").strip(),
            }


def identity_rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            transaction_id = (row.get("TransactionID") or "").strip()
            values = {attribute: (row.get(column) or "").strip() for attribute, column in IDENTITY_ATTRIBUTES.items()}
            if transaction_id and any(values.values()):
                yield {"transaction_id": transaction_id, **values}


def identity_aware(text: str) -> str:
    """Project the identity signals next to product_code (idempotent)."""
    if "device_status AS device_status" in text:
        return text
    for alias in ("anchor", "txns"):
        text = text.replace(f"{alias}.product_cd AS product_code", f"{alias}.product_cd AS product_code, {alias}.device_status AS device_status, "
                            f"{alias}.proxy_type AS proxy_type, {alias}.match_status AS match_status")
    return text


def gsql(source: TigerGraphSource, graph: str, command: str) -> str:
    result = source.call_tool("tigergraph__gsql", {"command": f"USE GRAPH {graph}\n{command}"})
    return str(result.get("data", result) if isinstance(result, dict) else result)


def transaction_attributes(source: TigerGraphSource, graph: str) -> set[str]:
    text = gsql(source, graph, "LS")
    line = next((item for item in text.replace("\\n", "\n").splitlines() if "VERTEX Transaction(" in item), "")
    return {name for name in IDENTITY_ATTRIBUTES if f"{name} " in line or f"{name}:" in line}


def add_identity_attributes(source: TigerGraphSource, graph: str) -> None:
    present = transaction_attributes(source, graph)
    missing = [name for name in IDENTITY_ATTRIBUTES if name not in present]
    if not missing:
        print("Transaction already has the identity attributes.")
        return
    columns = ", ".join(f"{name} STRING" for name in missing)
    for scope, create in (("local", f"CREATE SCHEMA_CHANGE JOB add_identity_signals FOR GRAPH {graph}"), ("global", "CREATE GLOBAL SCHEMA_CHANGE JOB add_identity_signals")):
        print(f"Adding {', '.join(missing)} to Transaction ({scope} schema change)…", flush=True)
        try:
            gsql(source, graph, f"{create} {{\n  ALTER VERTEX Transaction ADD ATTRIBUTE ({columns});\n}}")
            output = gsql(source, graph, f"RUN {'GLOBAL ' if scope == 'global' else ''}SCHEMA_CHANGE JOB add_identity_signals")
            print(output[-300:])
            return
        except Exception as error:  # noqa: BLE001 - try the other scope, then report
            print(f"  {scope} schema change failed: {str(error)[:300]}")
        finally:
            try:
                gsql(source, graph, "DROP JOB add_identity_signals")
            except Exception:  # noqa: BLE001 - nothing to drop
                pass
    raise SystemExit("Could not add the identity attributes to Transaction; see the errors above.")


def upsert(source: TigerGraphSource, vertex_type: str, key: str, rows: Iterable[dict[str, Any]], size: int) -> int:
    total, started = 0, time.time()
    for batch in batches(rows, size):
        source.call_tool("tigergraph__add_nodes", {"vertex_type": vertex_type, "vertex_id": key, "vertices": batch})
        total += len(batch)
        print(f"  {vertex_type}: {total} upserted ({time.time() - started:.0f}s)", flush=True)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, required=True, help="the HHGOA_IEEE folder")
    parser.add_argument("--graph", default=None, help="graph name (default: TG_GRAPHNAME)")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--skip", nargs="*", default=[], choices=["closed_cases", "identity", "queries"])
    args = parser.parse_args()

    source = TigerGraphSource(timeout_s=900)
    graph = args.graph or source.service.graph_name
    if "closed_cases" not in args.skip:
        path = args.data_dir / "closed_cases_history.csv"
        print(f"Closed cases from {path}")
        print(f"Done: {upsert(source, 'ClosedCase', 'case_id', closed_case_rows(path), args.batch_size)} closed cases")
    if "identity" not in args.skip:
        add_identity_attributes(source, graph)
        path = args.data_dir / "identity.csv"
        print(f"Identity signals from {path}")
        print(f"Done: {upsert(source, 'Transaction', 'transaction_id', identity_rows(path), args.batch_size)} transactions")
    if "queries" not in args.skip:
        if len(transaction_attributes(source, graph)) < len(IDENTITY_ATTRIBUTES):
            raise SystemExit("Transaction has no identity attributes yet: run without --skip identity first.")
        for name in AGENT_QUERIES:
            path = ROOT / "tigergraph" / "queries" / f"{name}.gsql"
            text = identity_aware(path.read_text(encoding="utf-8"))
            path.write_text(text, encoding="utf-8")
            print(gsql(source, graph, text.replace("CREATE QUERY", "CREATE OR REPLACE QUERY", 1))[-160:])
        print(gsql(source, graph, "INSTALL QUERY " + ", ".join(AGENT_QUERIES))[-200:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
