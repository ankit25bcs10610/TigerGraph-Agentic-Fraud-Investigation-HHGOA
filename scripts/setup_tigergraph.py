"""Create the graph, load the prepared data and install every query on TigerGraph.

Works against TigerGraph Savanna or Community Edition over REST with
pyTigerGraph, so no local ``gsql`` client is needed. Reads the same ``TG_*``
settings as the MCP server (see ``.env.example``).

Steps (each can be skipped):

1. schema     create vertex/edge types and the FraudInvestigation graph
2. job        create the ``load_fraud_data`` loading job
3. load       upload the TSVs from ``scripts/prepare_graph_data.py --full``
4. queries    create and install every query in ``tigergraph/queries``
5. verify     print vertex counts and run one agent query

Example::

    python scripts/prepare_graph_data.py --data-dir /path/to/HHGOA_IEEE --output-dir build/graph_data --full
    python scripts/setup_tigergraph.py --data-dir build/graph_data
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = os.getenv("TG_GRAPHNAME", "FraudInvestigation")
VERTICES = ["Customer", "Card", "Transaction", "DeviceProfile", "EmailDomain", "BillingRegion", "ClosedCase", "InvestigationCase"]


def connect():
    try:
        import pyTigerGraph as tg
    except ImportError as error:
        raise SystemExit("pip install pyTigerGraph (it is in requirements.txt)") from error
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    host = os.getenv("TG_HOST")
    if not host:
        raise SystemExit("Set TG_HOST (and TG_SECRET or TG_USERNAME/TG_PASSWORD) in .env")
    conn = tg.TigerGraphConnection(host=host, graphname=GRAPH, username=os.getenv("TG_USERNAME") or "tigergraph",
                                   password=os.getenv("TG_PASSWORD") or "", tgCloud=(os.getenv("TG_TGCLOUD", "true").lower() == "true"),
                                   gsPort=os.getenv("TG_SSL_PORT") or "443", restppPort=os.getenv("TG_SSL_PORT") or "443")
    if os.getenv("TG_SECRET"):
        conn.getToken(os.getenv("TG_SECRET"))
    elif os.getenv("TG_API_TOKEN"):
        conn.apiToken = os.getenv("TG_API_TOKEN")
    return conn


def gsql(conn, text: str) -> str:
    result = conn.gsql(text)
    print(result if isinstance(result, str) else str(result))
    return str(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "build" / "graph_data", help="folder of prepared TSVs")
    parser.add_argument("--skip", nargs="*", default=[], choices=["schema", "job", "load", "queries", "verify"])
    args = parser.parse_args()
    conn = connect()

    if "schema" not in args.skip:
        schema = (ROOT / "tigergraph" / "schema.gsql").read_text(encoding="utf-8")
        if GRAPH in gsql(conn, "SHOW GRAPH *"):
            print(f"Graph {GRAPH} already exists; keeping it.")
        else:
            gsql(conn, schema)
    if "job" not in args.skip:
        gsql(conn, f"USE GRAPH {GRAPH}\nDROP JOB load_fraud_data")
        gsql(conn, f"USE GRAPH {GRAPH}\n" + (ROOT / "tigergraph" / "loading_jobs.gsql").read_text(encoding="utf-8"))
    if "load" not in args.skip:
        job = (ROOT / "tigergraph" / "loading_jobs.gsql").read_text(encoding="utf-8")
        tags = [line.split("DEFINE FILENAME", 1)[1].strip().rstrip(";") for line in job.splitlines() if "DEFINE FILENAME" in line]
        for tag in tags:
            path = args.data_dir / f"{tag.removeprefix('f_')}.tsv"
            if not path.exists():
                print(f"skip {tag}: {path} not found")
                continue
            print(f"loading {path.name} ...", flush=True)
            print(conn.runLoadingJobWithFile(str(path), tag, "load_fraud_data", sep="\t"))
    if "queries" not in args.skip:
        for path in sorted((ROOT / "tigergraph" / "queries").glob("*.gsql")):
            name = path.stem
            gsql(conn, f"USE GRAPH {GRAPH}\nDROP QUERY {name}")
            gsql(conn, f"USE GRAPH {GRAPH}\n" + path.read_text(encoding="utf-8"))
        gsql(conn, f"USE GRAPH {GRAPH}\nINSTALL QUERY ALL")
    if "verify" not in args.skip:
        for vertex in VERTICES:
            print(f"{vertex}: {conn.getVertexCount(vertex)}")
        sample = conn.getVertices("Transaction", limit=1)
        if sample:
            print("agent_txn_profile:", conn.runInstalledQuery("agent_txn_profile", {"transaction_id": sample[0]["v_id"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
