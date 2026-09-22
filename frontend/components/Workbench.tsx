"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Action, CaseOption, Evidence, EvidenceRequest, Investigation } from "../lib/types";
import { Audit, Sar, SimilarCases, Timeline } from "./DataPanels";
import { GraphEvidence } from "./GraphEvidence";

const tabs = ["Overview", "Graph Evidence", "Transaction Timeline", "Evidence", "Similar Cases", "Actions", "SAR", "Audit Trail"] as const;
type Tab = (typeof tabs)[number];

function formatExposure(value: unknown): string {
  const amount = typeof value === "number" ? value : Number(value);
  return Number.isFinite(amount) ? `$${amount.toLocaleString()}` : "Not assessed";
}

function ActionList({ title, items }: { title: string; items?: Action[] }) {
  return <section className="space-y-2"><h3 className="panel-title">{title}</h3>{items?.length ? items.map((item, index) => <article className="rounded-xl border border-slate-200 p-3" key={`${item.action}-${index}`}><div className="flex justify-between gap-3"><strong>{item.action.replaceAll("_", " ")}</strong><span className={`route-badge route-${item.route.toLowerCase()}`}>{item.route}</span></div><p className="mt-1 text-sm text-slate-600">{item.reason}</p></article>) : <p className="text-sm text-slate-500">No actions returned.</p>}</section>;
}

function EvidenceRow({ item }: { item: Evidence }) {
  return <article className="border-b border-slate-100 py-4 last:border-0"><div className="mb-2 flex gap-2"><span className="source-badge">{item.source} evidence</span>{item.simulated && <span className="simulated-badge">Simulated</span>}</div><p className="text-sm">{item.claim}</p><small className="text-slate-500">Reference: {item.ref} · Entities: {item.entity_ids.join(", ") || "None"}</small>{item.simulated && <p className="text-xs text-amber-900">Assumption: {item.assumption}</p>}</article>;
}

export function Workbench() {
  const [availableCases, setAvailableCases] = useState<CaseOption[]>([]);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<Investigation | null>(null);
  const [tab, setTab] = useState<Tab>("Graph Evidence");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [responses, setResponses] = useState<Record<string, { result: string; details: string }>>({});

  useEffect(() => {
    if (!api.isConfigured) return;
    api.cases().then((items) => { setAvailableCases(items); setSelected(items[0]?.case_id ?? ""); }).catch((caught) => setError(caught instanceof Error ? caught.message : "Unable to load case queue."));
  }, []);

  async function start() {
    if (!selected) return;
    setLoading(true); setError("");
    try { setData(await api.start(selected)); setTab("Graph Evidence"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to start investigation."); }
    finally { setLoading(false); }
  }

  async function submitEvidence(request: EvidenceRequest) {
    if (!data) return;
    const answer = responses[request.request_id] ?? { result: "unknown", details: "" };
    setLoading(true); setError("");
    try { setData(await api.evidence(data.case_id, request, answer.result, answer.details)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to submit evidence."); }
    finally { setLoading(false); }
  }

  async function approve(action: string, approved: boolean) {
    if (!data) return;
    setLoading(true); setError("");
    try { setData(await api.approve(data.case_id, action, approved)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to record approval."); }
    finally { setLoading(false); }
  }

  const requests = data?.evidence_requests ?? [];
  const assessedCase = data?.case;
  return <main className="workbench-shell">
    <header className="topbar"><div className="brand-mark"><span className="brand-shield">◇</span><div><strong>SENTINEL</strong><small>Agentic Fraud Intelligence</small></div></div><div className="global-search"><span>⌕</span><input aria-label="Search cases, customers, transactions" placeholder="Search cases, customers, transactions…" /></div><div className="topbar-right"><span className={`connection ${api.isConfigured ? "ready" : "offline"}`}><i />{api.isConfigured ? "TigerGraph Connected" : "API Offline"}</span><span className="analyst-pill">AD <b>Analyst</b>⌄</span></div></header>
    <div className="workbench-layout">
      <aside className="case-queue"><nav className="side-nav" aria-label="Primary navigation"><p className="nav-label">Workspace</p><button className={`nav-item ${tab === "Overview" ? "active" : ""}`} onClick={() => setTab("Overview")} type="button">⌂ <span>Dashboard</span></button><button className={`nav-item ${data ? "active" : ""}`} onClick={() => setTab("Overview")} type="button">◉ <span>Investigations</span></button><button className="nav-item" onClick={() => document.querySelector(".case-queue")?.scrollIntoView({ behavior: "smooth" })} type="button">▣ <span>Cases</span></button><button className={`nav-item ${tab === "Graph Evidence" ? "active" : ""}`} onClick={() => setTab("Graph Evidence")} type="button">⌘ <span>Graph Explore</span></button><button className={`nav-item ${tab === "SAR" ? "active" : ""}`} onClick={() => setTab("SAR")} type="button">▤ <span>Reports</span></button><button className={`nav-item ${tab === "Audit Trail" ? "active" : ""}`} onClick={() => setTab("Audit Trail")} type="button">▥ <span>Audit Log</span></button><button className="nav-item nav-disabled" onClick={() => setError("Knowledge Base is not configured for this local reference runtime.")} type="button">▧ <span>Knowledge Base</span></button><p className="nav-label nav-system">System</p><button className="nav-item nav-disabled" onClick={() => setError("Settings are managed through environment configuration, not the browser.")} type="button">⚙ <span>Settings</span></button></nav><div className="queue-head"><div><p className="eyebrow">Backend queue</p><h2>Case intake</h2></div><span>{availableCases.length}</span></div><p className="queue-copy">Cases are loaded from the backend; no benchmark IDs are generated in the browser.</p><div className="case-list">{availableCases.map((item) => <button className={item.case_id === selected ? "selected" : ""} key={item.case_id} onClick={() => setSelected(item.case_id)} type="button"><strong>{item.case_id}</strong><small>{item.trigger_type || "Ready"}</small></button>)}</div><button className="start-button" disabled={loading || !selected || !api.isConfigured} onClick={start} type="button">{loading ? "Working…" : `Start ${selected || "case"}`}</button><div className="graph-health"><i /> <span>TigerGraph<br/><b>{api.isConfigured ? "Connected" : "Not connected"}</b></span></div></aside>
      <section className="workspace">{error && <p className="notice error" role="alert">{error}</p>}{!api.isConfigured && <p className="notice config"><strong>Connect the investigation API.</strong><span>Set <code>NEXT_PUBLIC_API_BASE_URL</code> in <code>frontend/.env.local</code>, then restart Next.js.</span></p>}
        {!data ? <section className="intake-state"><p className="eyebrow">Investigation intake</p><h2>{api.isConfigured ? "Select a backend case" : "API connection required"}</h2><p>{api.isConfigured ? "Start a case to load graph evidence, deterministic decisions, evidence requests, and audit events." : "The workbench will not fabricate a queue or investigation result while the API is unavailable."}</p></section> : <>
          <section className="case-hero"><div><p className="eyebrow">Fraud investigation</p><h2>{data.case_id} <span className="case-status">{data.status ?? "INVESTIGATING"}</span></h2><p>{assessedCase?.summary || data.message || data.trigger_text}</p></div><div className="case-meta"><span>Customer <b>{data.customer_id || "Not returned"}</b></span><span>Card <b>{data.card_id || "Not returned"}</b></span><span>Flagged transaction <b>{data.flagged_txn_id || "Not returned"}</b></span></div></section>
          <section className="case-metrics"><article><span>Bank risk score</span><strong className="risk-value">{data.risk_score ?? "Not returned"}</strong><small>Input signal only</small></article><article><span>Fraud probability</span><strong className="probability-value">{assessedCase?.fraud_probability == null ? "Not assessed" : `${Math.round(assessedCase.fraud_probability * 100)}%`}</strong><small>Deterministic evidence assessment</small></article><article><span>Exposure</span><strong>{formatExposure(assessedCase?.exposure_usd)}</strong><small>{data.timeline?.length ?? 0} transaction(s) returned</small></article><article><span>Pattern</span><strong>{assessedCase?.pattern?.replaceAll("_", " ") || "Not assessed"}</strong><small>Evidence-derived pattern</small></article><article><span>Status</span><strong>{assessedCase?.status || data.status || "Open"}</strong><small>{data.evidence_requests?.length ? "Awaiting evidence" : "Investigation state"}</small></article></section>
          <nav className="tabs" aria-label="Case workspace views">{tabs.map((item) => <button className={tab === item ? "active" : ""} key={item} onClick={() => setTab(item)} type="button">{item}</button>)}</nav>
          <section className="workspace-panel">
            {tab === "Overview" && <div className="metric-grid"><article><span>Flagged transaction</span><strong>{data.flagged_txn_id || "Not returned"}</strong></article><article><span>Bank risk score</span><strong className="risk-value">{data.risk_score ?? "Not returned"}</strong><small>Input signal only</small></article><article><span>Fraud probability</span><strong className="probability-value">{assessedCase?.fraud_probability == null ? "Not assessed" : `${Math.round(assessedCase.fraud_probability * 100)}%`}</strong><small>Deterministic evidence assessment</small></article><article><span>Exposure</span><strong>{formatExposure(assessedCase?.exposure_usd)}</strong></article></div>}
            {tab === "Graph Evidence" && <div className="graph-workspace"><GraphEvidence graph={data.graph} /><aside className="evidence-summary"><div className="panel-heading"><h3>Evidence Summary</h3><span>{assessedCase?.evidence?.length ?? 0}</span></div>{assessedCase?.evidence?.length ? assessedCase.evidence.map((item, index) => <article key={`${item.ref}-${index}`}><b>{item.claim}</b><small>{item.source} · {item.ref}</small></article>) : <p>No deterministic evidence returned yet.</p>}<div className="progress-card"><div className="panel-heading"><h3>Investigation Progress</h3><b>{data.status === "evidence_available" ? "Evidence available" : data.status}</b></div><div className="progress-track"><i style={{ width: data.status === "evidence_available" ? "45%" : "15%" }} /></div><small>Progress reflects returned workflow state, not a fabricated fraud outcome.</small></div></aside></div>}
            {tab === "Transaction Timeline" && <Timeline rows={data.timeline ?? []} />}
            {tab === "Evidence" && <div>{[...(assessedCase?.evidence ?? []), ...(data.evidence_responses ?? [])].map((item, index) => <EvidenceRow item={item} key={`${item.ref}-${index}`} />)}{requests.map((request) => <article className="request-card" key={request.request_id}><p className="panel-title">Evidence request · {request.type.replaceAll("_", " ")}</p><strong>{request.question}</strong><p>{request.reason}</p><select aria-label={`Result for ${request.request_id}`} value={responses[request.request_id]?.result ?? "unknown"} onChange={(event) => setResponses({ ...responses, [request.request_id]: { ...(responses[request.request_id] ?? { details: "" }), result: event.target.value } })}><option value="unknown">Unknown</option><option value="confirmed">Confirmed</option><option value="denied">Denied</option><option value="no_reply">No reply</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="not_completed">Not completed</option></select><textarea aria-label={`Details for ${request.request_id}`} placeholder="Response details (optional)" value={responses[request.request_id]?.details ?? ""} onChange={(event) => setResponses({ ...responses, [request.request_id]: { ...(responses[request.request_id] ?? { result: "unknown" }), details: event.target.value } })} /><button disabled={loading} onClick={() => submitEvidence(request)} type="button">Submit evidence</button></article>)}</div>}
            {tab === "Similar Cases" && <SimilarCases rows={data.similar_cases ?? []} />}
            {tab === "Actions" && <div className="action-layout"><section className="nba-panel"><div className="panel-heading"><h3>Next Best Action</h3><span>Policy-controlled</span></div><div className="action-columns"><div><p>Initial action</p><ActionList title="Before evidence" items={data.next_best_actions?.initial} /></div><div className="action-arrow">→</div><div><p>Final action</p><ActionList title="After evidence" items={data.next_best_actions?.final} /></div></div><p className="what-changed">{data.next_best_actions?.what_changed || "No action change returned."}</p></section>{data.approval_requests?.filter((item) => item.approval_status === "pending").map((item) => <article className="approval-panel" key={item.action}><strong>{item.action} · {item.route} approval</strong><p>{item.reason}</p><button onClick={() => approve(item.action, true)} type="button">Approve</button><button onClick={() => approve(item.action, false)} type="button">Reject</button></article>)}</div>}
            {tab === "SAR" && data.sar && <Sar sar={data.sar} pending={data.approval_requests?.some((item) => item.action === "FILE_REPORT" && item.approval_status === "pending")} />}
            {tab === "Audit Trail" && <Audit events={data.audit ?? []} />}
          </section>
        </>}
      </section>
    </div>
  </main>;
}
