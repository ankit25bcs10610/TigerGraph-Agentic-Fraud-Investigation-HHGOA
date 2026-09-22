import { Evidence, EvidenceRequest } from "../lib/types";

type Props = {
  evidence: Evidence[];
  requests: EvidenceRequest[];
  auditCount: number;
  status?: string;
  integrity?: { status: string; event_count: number; latest_hash: string };
};

export function CaseIntegrity({ evidence, requests, auditCount, status, integrity }: Props) {
  const sourceCount = new Set(evidence.map((item) => item.source)).size;
  const openRequests = requests.filter((item) => item.status !== "completed").length;
  const checks = [
    { label: "Grounded claims", value: evidence.length, detail: "Every claim carries a source and entity reference." },
    { label: "Independent sources", value: sourceCount, detail: "Source diversity informs decision confidence; it is not a fraud score." },
    { label: "Open evidence", value: openRequests, detail: "Requests remain explicit until a response is recorded." },
    { label: "Audit events", value: auditCount, detail: "Tool and workflow events preserve the decision trail." },
  ];
  return <section className="integrity-card" aria-label="Evidence integrity">
    <div className="integrity-heading"><div><p className="eyebrow">Decision integrity</p><h3>Defensibility snapshot</h3></div><span className="integrity-status">{status?.replaceAll("_", " ") || "In review"}</span></div>
    <div className="integrity-grid">{checks.map((check) => <article key={check.label}><strong>{check.value}</strong><span>{check.label}</span><small>{check.detail}</small></article>)}</div>
    {integrity && <div className="ledger-seal"><span>⌘ Tamper-evident case ledger</span><code>{integrity.latest_hash.slice(0, 16)}…{integrity.latest_hash.slice(-8)}</code><small>{integrity.event_count} sealed event{integrity.event_count === 1 ? "" : "s"}</small></div>}
    <p className="integrity-note"><i /> Sentinel separates evidence completeness from fraud probability so analysts can see what is known, what remains unresolved, and why policy-controlled actions are required.</p>
  </section>;
}
