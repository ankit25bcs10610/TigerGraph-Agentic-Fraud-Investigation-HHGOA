import { Evidence, EvidenceRequest } from "../lib/types";

type Props = {
  evidence: Evidence[];
  requests: EvidenceRequest[];
  auditCount: number;
  status?: string;
};

export function CaseIntegrity({ evidence, requests, auditCount, status }: Props) {
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
    <p className="integrity-note"><i /> Sentinel separates evidence completeness from fraud probability so analysts can see what is known, what remains unresolved, and why policy-controlled actions are required.</p>
  </section>;
}
