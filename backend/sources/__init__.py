"""Graph data sources the investigation agent can call as tools.

Two interchangeable implementations answer the same questions:

* ``TigerGraphSource`` runs installed GSQL queries through the official
  TigerGraph MCP server (the production path).
* ``CsvSource`` answers from the supplied CSV files (local development,
  offline demos and calibration).

The agent never reads raw rows directly; every lookup is a named tool call
whose inputs, output size and latency are recorded in the case trace.
"""
from backend.sources.base import CaseDataSource, ClosedCaseRecord, RingResult, Txn
from backend.sources.csv_source import CsvSource

__all__ = ["CaseDataSource", "ClosedCaseRecord", "CsvSource", "RingResult", "Txn"]
