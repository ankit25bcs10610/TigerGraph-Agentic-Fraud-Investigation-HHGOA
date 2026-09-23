"""Policy grounding for the agent's recommendations.

Two sources are retrieved from, both returning citable chunks:

* The rule catalog: the docstrings of the deterministic R1-R10 rules and the
  approval routing, so every recommended action can be cited to the exact
  rule that produced it.
* Policy documents (``POLICY_DOCS_PATH``): the bank's fraud policy, known
  fraud patterns and regulatory references supplied with the dataset,
  chunked by heading and ranked by term overlap with the investigation.

When TigerGraph GraphRAG is configured, vector retrieval over the same
documents is used first and this lexical ranking is the fallback.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from backend.policy import rules

WORD = re.compile(r"[a-z0-9$]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "be", "with", "by", "if", "as", "at", "it", "that", "this", "from"}


@dataclass(frozen=True)
class PolicyChunk:
    ref: str
    title: str
    text: str
    source: str


def _terms(text: str) -> list[str]:
    return [word for word in WORD.findall(text.lower()) if word not in STOP and len(word) > 1]


def _rule_catalog() -> list[PolicyChunk]:
    chunks = []
    for name in dir(rules):
        match = re.match(r"r(\d+)_", name)
        function = getattr(rules, name)
        if match and callable(function) and function.__doc__:
            number = match.group(1)
            chunks.append(PolicyChunk(f"policy:R{number}", f"Rule R{number}", " ".join(function.__doc__.split()), "rule_catalog"))
    chunks.append(PolicyChunk("policy:approval_routes", "Approval routes", "Allow, monitor, warn, verify, step-up, report generation, case creation, escalation and close are AUTO. Decline transaction needs L1. Block card needs L1 up to $2,500 exposure and L2 above. Block all cards and file report need L2.", "rule_catalog"))
    return sorted(chunks, key=lambda chunk: int(chunk.ref.split("R")[-1]) if chunk.ref[-1].isdigit() else 99)


def _document_chunks(directory: Path) -> list[PolicyChunk]:
    chunks: list[PolicyChunk] = []
    for path in sorted(directory.rglob("*")):
        if path.suffix.lower() not in {".md", ".txt"} or not path.is_file():
            continue
        title, lines, index = path.stem, [], 0
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() + ["# end"]:
            if line.startswith("#"):
                body = " ".join(" ".join(lines).split())
                if len(body) > 40:
                    index += 1
                    chunks.append(PolicyChunk(f"doc:{path.name}#{index}", title, body[:1200], path.name))
                title, lines = line.lstrip("# ").strip() or path.stem, []
            else:
                lines.append(line)
    return chunks


class PolicyKnowledge:
    def __init__(self, docs_path: str | None = None) -> None:
        self.chunks = _rule_catalog()
        if docs_path and Path(docs_path).is_dir():
            self.chunks += _document_chunks(Path(docs_path))
        self._frequencies = [Counter(_terms(f"{chunk.title} {chunk.text}")) for chunk in self.chunks]
        documents = len(self.chunks) or 1
        seen = Counter(term for counts in self._frequencies for term in counts)
        self._idf = {term: math.log(1 + documents / count) for term, count in seen.items()}

    def rule(self, number: str) -> PolicyChunk | None:
        return next((chunk for chunk in self.chunks if chunk.ref == f"policy:{number}"), None)

    def search(self, query: str, limit: int = 4, *, documents_only: bool = False) -> list[PolicyChunk]:
        terms = _terms(query)
        scored = []
        for chunk, counts in zip(self.chunks, self._frequencies):
            if documents_only and chunk.source == "rule_catalog":
                continue
            score = sum(counts[term] * self._idf.get(term, 0.0) for term in terms)
            if score > 0:
                scored.append((score, chunk))
        return [chunk for _, chunk in sorted(scored, key=lambda item: -item[0])[:limit]]

    @property
    def has_documents(self) -> bool:
        return any(chunk.source != "rule_catalog" for chunk in self.chunks)
