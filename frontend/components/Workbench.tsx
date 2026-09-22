"use client";

import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Action, CaseOption, Evidence, EvidenceRequest, Investigation } from "../lib/types";
import { Audit, Sar, SimilarCases, Timeline } from "./DataPanels";
import { GraphEvidence } from "./GraphEvidence";

const tabs = ["Overview", "Graph Evidence", "Transaction Timeline", "Evidence", "Similar Cases", "Actions", "SAR", "Audit Trail"] as const;
type Tab = (typeof tabs)[number];

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
  const [tab, setTab] = useState<Tab>("Overview");
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
    try { setData(await api.start(selected)); setTab("Overview"); }
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
    <header className="topbar"><div><p className="eyebrow">TigerGraph · Fraud operations</p><h1>Investigation workbench</h1></div><span className={`connection ${api.isConfigured ? "ready" : "offline"}`}><i />{api.isConfigured ? "Investigation API configured" : "Investigation API not configured"}</span></header>
    <div className="workbench-layout">
      <aside className="case-queue"><div className="queue-head"><div><p className="eyebrow">Backend queue</p><h2>Case intake</h2></div><span>{availableCases.length}</span></div><p className="queue-copy">Cases are loaded from the backend; no benchmark IDs are generated in the browser.</p><div className="case-list">{availableCases.map((item) => <button className={item.case_id === selected ? "selected" : ""} key={item.case_id} onClick={() => setSelected(item.case_id)} type="button"><strong>{item.case_id}</strong><small>{item.trigger_type || "Ready"}</small></button>)}</div><button className="start-button" disabled={loading || !selected || !api.isConfigured} onClick={start} type="button">{loading ? "Working…" : `Start ${selected || "case"}`}</button></aside>
      <section className="workspace">{error && <p className="notice error" role="alert">{error}</p>}{!api.isConfigured && <p className="notice config"><strong>Connect the investigation API.</strong><span>Set <code>NEXT_PUBLIC_API_BASE_URL</code> in <code>frontend/.env.local</code>, then restart Next.js.</span></p>}
        {!data ? <section className="intake-state"><p className="eyebrow">Investigation intake</p><h2>{api.isConfigured ? "Select a backend case" : "API connection required"}</h2><p>{api.isConfigured ? "Start a case to load graph evidence, deterministic decisions, evidence requests, and audit events." : "The workbench will not fabricate a queue or investigation result while the API is unavailable."}</p></section> : <>
          <section className="case-hero"><div><p className="eyebrow">Active investigation</p><h2>{data.case_id}</h2><p>{assessedCase?.summary || data.message || data.trigger_text}</p></div><div><span className={`verdict ${assessedCase?.verdict ?? "uncertain"}`}>{assessedCase?.verdict ?? data.status ?? "open"}</span></div></section>
          <nav className="tabs" aria-label="Case workspace views">{tabs.map((item) => <button className={tab === item ? "active" : ""} key={item} onClick={() => setTab(item)} type="button">{item}</button>)}</nav>
          <section className="workspace-panel">
            {tab === "Overview" && <div className="metric-grid"><article><span>Flagged transaction</span><strong>{data.flagged_txn_id || "Not returned"}</strong></article><article><span>Bank risk score</span><strong className="risk-value">{data.risk_score ?? "Not returned"}</strong><small>Input signal only</small></article><article><span>Fraud probability</span><strong className="probability-value">{assessedCase?.fraud_probability == null ? "Not assessed" : `${Math.round(assessedCase.fraud_probability * 100)}%`}</strong><small>Deterministic evidence assessment</small></article><article><span>Exposure</span><strong>{assessedCase?.exposure_usd == null ? "Not assessed" : `$${assessedCase.exposure_usd.toLocaleString()}`}</strong></article></div>}
            {tab === "Graph Evidence" && <GraphEvidence graph={data.graph} />}
            {tab === "Transaction Timeline" && <Timeline rows={data.timeline ?? []} />}
            {tab === "Evidence" && <div>{[...(assessedCase?.evidence ?? []), ...(data.evidence_responses ?? [])].map((item, index) => <EvidenceRow item={item} key={`${item.ref}-${index}`} />)}{requests.map((request) => <article className="request-card" key={request.request_id}><p className="panel-title">Evidence request · {request.type.replaceAll("_", " ")}</p><strong>{request.question}</strong><p>{request.reason}</p><select aria-label={`Result for ${request.request_id}`} value={responses[request.request_id]?.result ?? "unknown"} onChange={(event) => setResponses({ ...responses, [request.request_id]: { ...(responses[request.request_id] ?? { details: "" }), result: event.target.value } })}><option value="unknown">Unknown</option><option value="confirmed">Confirmed</option><option value="denied">Denied</option><option value="no_reply">No reply</option><option value="passed">Passed</option><option value="failed">Failed</option><option value="not_completed">Not completed</option></select><textarea aria-label={`Details for ${request.request_id}`} placeholder="Response details (optional)" value={responses[request.request_id]?.details ?? ""} onChange={(event) => setResponses({ ...responses, [request.request_id]: { ...(responses[request.request_id] ?? { result: "unknown" }), details: event.target.value } })} /><button disabled={loading} onClick={() => submitEvidence(request)} type="button">Submit evidence</button></article>)}</div>}
            {tab === "Similar Cases" && <SimilarCases rows={data.similar_cases ?? []} />}
            {tab === "Actions" && <div className="space-y-5"><ActionList title="Initial actions" items={data.next_best_actions?.initial} /><ActionList title="Final actions" items={data.next_best_actions?.final} /><p>{data.next_best_actions?.what_changed}</p>{data.approval_requests?.filter((item) => item.approval_status === "pending").map((item) => <article className="approval-panel" key={item.action}><strong>{item.action} · {item.route}</strong><p>{item.reason}</p><button onClick={() => approve(item.action, true)} type="button">Approve</button><button onClick={() => approve(item.action, false)} type="button">Reject</button></article>)}</div>}
            {tab === "SAR" && data.sar && <Sar sar={data.sar} pending={data.approval_requests?.some((item) => item.action === "FILE_REPORT" && item.approval_status === "pending")} />}
            {tab === "Audit Trail" && <Audit events={data.audit ?? []} />}
          </section>
        </>}
      </section>
    </div>
  </main>;
}
