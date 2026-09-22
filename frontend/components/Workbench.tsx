"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Action, CaseOption, Evidence, EvidenceRequest, Investigation } from "../lib/types";
import { Audit, Sar, SimilarCases, Timeline } from "./DataPanels";
import { GraphEvidence } from "./GraphEvidence";
import { CaseIntegrity } from "./CaseIntegrity";

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

function safeAudit(events: Record<string, unknown>[]) {
  const secret = /api[_-]?key|token|password|secret|credential|authorization/i;
  return events.map((event) => Object.fromEntries(Object.entries(event).filter(([key]) => !secret.test(key))));
}

export function Workbench() {
  const [availableCases, setAvailableCases] = useState<CaseOption[]>([]);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<Investigation | null>(null);
  const [tab, setTab] = useState<Tab>("Overview");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [connection, setConnection] = useState<"checking" | "online" | "setup" | "offline">(api.isConfigured ? "checking" : "offline");
  const [queueFilter, setQueueFilter] = useState("");
  const [casePackFile, setCasePackFile] = useState<File | null>(null);
  const [responses, setResponses] = useState<Record<string, { result: string; details: string }>>({});

  useEffect(() => {
    if (!api.isConfigured) return;
    let active = true;
    api.health().then((health) => {
      if (!active) return;
      if (!health.workflow_configured) {
        setConnection("setup");
        return;
      }
      setConnection("online");
      return api.cases();
    }).then(async (items) => {
      if (!active || !items) return;
      setAvailableCases(items);
      setSelected((current) => current || items[0]?.case_id || "");
      if (items[0]?.case_id === "DEMO-001") {
        const preview = await api.start("DEMO-001");
        if (active) setData(preview);
      }
    }).catch((caught) => {
      if (!active) return;
      setConnection("offline");
      setError(caught instanceof Error ? caught.message : "Unable to connect to the investigation API.");
    });
    return () => { active = false; };
  }, []);

  const filteredCases = useMemo(() => {
    const query = queueFilter.trim().toLowerCase();
    if (!query) return availableCases;
    return availableCases.filter((item) => `${item.case_id} ${item.trigger_type ?? ""}`.toLowerCase().includes(query));
  }, [availableCases, queueFilter]);

  async function retryConnection() {
    setError(""); setConnection("checking");
    try {
      const health = await api.health();
      if (!health.workflow_configured) { setConnection("setup"); setAvailableCases([]); return; }
      setConnection("online"); setAvailableCases(await api.cases());
    }
    catch (caught) { setConnection("offline"); setError(caught instanceof Error ? caught.message : "Unable to connect to the investigation API."); }
  }

  async function loadCasePack() {
    if (!casePackFile) { setError("Choose the supplied case_pack.csv first."); return; }
    setLoading(true); setError("");
    try {
      await api.uploadCasePack(casePackFile);
      const items = await api.cases();
      setAvailableCases(items); setSelected(items[0]?.case_id ?? ""); setData(null); setConnection("online");
    } catch (caught) {
      setConnection("setup");
      setError(caught instanceof Error ? caught.message : "Unable to load the case pack.");
    } finally { setLoading(false); }
  }

  async function start() {
    if (!selected) return;
    setLoading(true); setError("");
    try { setData(await api.start(selected)); setTab("Graph Evidence"); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to start investigation."); }
    finally { setLoading(false); }
  }

  async function navigate(nextTab: Tab) {
    if (!data && selected) {
      setLoading(true); setError("");
      try { setData(await api.start(selected)); }
      catch (caught) { setError(caught instanceof Error ? caught.message : "Unable to start investigation."); return; }
      finally { setLoading(false); }
    }
    setTab(nextTab);
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

  function exportDossier() {
    if (!data) return;
    const dossier = {
      format: "sentinel-case-dossier/v1",
      exported_at: new Date().toISOString(),
      case_id: data.case_id,
      trigger: data.trigger_type ? { type: data.trigger_type, text: data.trigger_text } : undefined,
      investigation: data.case ?? { status: data.status, message: data.message },
      next_best_actions: data.next_best_actions,
      evidence_requests: data.evidence_requests ?? [],
      evidence_responses: data.evidence_responses ?? [],
      sar: data.sar,
      audit: safeAudit(data.audit ?? []),
      provenance: "Generated by the Sentinel analyst workbench. Values are API-returned evidence and decisions; no browser-side fraud inference is performed.",
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(dossier, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${data.case_id}-dossier.json`; anchor.click(); URL.revokeObjectURL(url);
  }

  const requests = data?.evidence_requests ?? [];
  const assessedCase = data?.case;
  const connectionLabel = connection === "checking" ? "Checking API" : connection === "online" ? "System ready" : connection === "setup" ? "Setup required" : "API offline";
  return <main className="workbench-shell">
    <header className="topbar"><div className="brand-mark"><span className="brand-shield">◇</span><div><strong>SENTINEL</strong><small>Agentic Fraud Intelligence</small></div></div><div className="global-search"><span>⌕</span><input aria-label="Search cases, customers, transactions" placeholder="Search cases, customers, transactions…" value={queueFilter} onChange={(event) => setQueueFilter(event.target.value)} /></div><div className="topbar-right"><span className={`connection ${connection}`}><i />{connectionLabel}</span><span className="analyst-pill"><span className="analyst-avatar">AD</span><b>Analyst</b>⌄</span></div></header>
    <div className="workbench-layout">
      <aside className="case-queue"><nav className="side-nav" aria-label="Primary navigation"><p className="nav-label">Workspace</p><button className={`nav-item ${tab === "Overview" ? "active" : ""}`} onClick={() => navigate("Overview")} type="button">⌂ <span>Dashboard</span></button><button className={`nav-item ${data ? "active" : ""}`} onClick={() => navigate("Overview")} type="button">◉ <span>Investigations</span></button><button className="nav-item" onClick={() => document.querySelector(".queue-head")?.scrollIntoView({ behavior: "smooth" })} type="button">▣ <span>Cases</span></button><button className={`nav-item ${tab === "Graph Evidence" ? "active" : ""}`} onClick={() => navigate("Graph Evidence")} type="button">⌘ <span>Graph Explore</span></button><button className={`nav-item ${tab === "SAR" ? "active" : ""}`} onClick={() => navigate("SAR")} type="button">▤ <span>Reports</span></button><button className={`nav-item ${tab === "Audit Trail" ? "active" : ""}`} onClick={() => navigate("Audit Trail")} type="button">▥ <span>Audit Log</span></button><button className={`nav-item ${tab === "Similar Cases" ? "active" : ""}`} onClick={() => navigate("Similar Cases")} type="button">▧ <span>Knowledge Base</span></button><p className="nav-label nav-system">System</p><button className="nav-item" onClick={() => document.querySelector(".case-pack-import")?.scrollIntoView({ behavior: "smooth" })} type="button">⚙ <span>Settings</span></button></nav><div className="queue-head"><div><p className="eyebrow">Backend queue</p><h2>Case intake</h2></div><span>{availableCases.length}</span></div><p className="queue-copy">Select a case, or load the supplied benchmark case pack below.</p><div className="case-list">{filteredCases.map((item) => <button className={item.case_id === selected ? "selected" : ""} key={item.case_id} onClick={() => { setSelected(item.case_id); setData(null); }} type="button"><strong>{item.case_id}</strong><small>{item.trigger_type || "Ready"}</small></button>)}{!filteredCases.length && <div className="queue-empty">{availableCases.length ? "No cases match your search." : "No cases returned by the API."}</div>}</div><button className="start-button" disabled={loading || !selected || connection !== "online"} onClick={start} type="button">{loading ? "Opening investigation…" : `Start ${selected || "case"}`}</button><section className="case-pack-import"><p className="import-label">Replace preview with benchmark data</p><strong>{casePackFile?.name || "case_pack.csv"}</strong><label className="file-picker"><input type="file" accept=".csv,text/csv" onChange={(event) => setCasePackFile(event.target.files?.[0] ?? null)} />Choose CSV</label><button className="load-pack-button" disabled={!casePackFile || loading} onClick={loadCasePack} type="button">{loading ? "Loading…" : "Load case pack"}</button></section>{connection !== "online" && <button className="retry-button" onClick={retryConnection} type="button">Retry connection</button>}<div className="graph-health"><i /> <span>Investigation API<br/><b>{connectionLabel}</b></span></div></aside>
      <section className="workspace">{error && <p className="notice error" role="alert"><strong>Connection issue</strong><span>{error}</span></p>}{!api.isConfigured && <p className="notice config"><strong>Connect the investigation API.</strong><span>Set <code>NEXT_PUBLIC_API_BASE_URL</code> in <code>frontend/.env.local</code>, then restart Next.js.</span></p>}
        {!data ? <section className="intake-state"><div className="intake-orbit orbit-one" /><div className="intake-orbit orbit-two" /><div className="intake-icon">⌁</div><p className="eyebrow">Fraud operations command center</p><h2>{connection === "online" ? "Select a case. See the full picture." : connection === "checking" ? "Securing your investigation workspace…" : connection === "setup" ? "Your API is online. Load the case pack to investigate." : "Investigation API unavailable"}</h2><p>{connection === "online" ? "Start a benchmark case to assemble graph evidence, policy decisions, evidence requests, and a complete audit record in one defensible workflow." : connection === "setup" ? "Choose the supplied case_pack.csv below. Sentinel validates it locally, loads the twenty benchmark triggers, and keeps benchmark data out of browser-side sample code." : "The workbench cannot reach the local API. Start the FastAPI service, then retry the connection."}</p>{connection === "setup" && <div className="setup-card"><div><span className="setup-kicker">Load benchmark input</span><strong>{casePackFile?.name || "case_pack.csv"}</strong><small>{casePackFile ? `${Math.ceil(casePackFile.size / 1024)} KB selected` : "Choose the supplied benchmark case pack"}</small></div><label className="file-picker"><input type="file" accept=".csv,text/csv" onChange={(event) => setCasePackFile(event.target.files?.[0] ?? null)} />Choose CSV</label><button className="load-pack-button" disabled={!casePackFile || loading} onClick={loadCasePack} type="button">{loading ? "Loading…" : "Load case pack"}</button></div>}{connection !== "online" && connection !== "setup" && <button className="primary-cta" onClick={retryConnection} type="button">Retry connection</button>}<div className="intake-points"><span><i />Graph-grounded evidence</span><span><i />Policy-controlled actions</span><span><i />Auditable decisions</span></div></section> : <>
          <section className="case-hero"><div><p className="eyebrow">Fraud investigation</p><h2>{data.case_id} <span className="case-status">{data.status ?? "INVESTIGATING"}</span></h2><p>{assessedCase?.summary || data.message || data.trigger_text}</p></div><div className="case-hero-actions"><button className="dossier-button" onClick={exportDossier} type="button">⇩ Export case dossier</button><div className="case-meta"><span>Customer <b>{data.customer_id || "Not returned"}</b></span><span>Card <b>{data.card_id || "Not returned"}</b></span><span>Flagged transaction <b>{data.flagged_txn_id || "Not returned"}</b></span></div></div></section>
          <section className="case-metrics"><article><span>Bank risk score</span><strong className="risk-value">{data.risk_score ?? "Not returned"}</strong><small>Input signal only</small></article><article><span>Fraud probability</span><strong className="probability-value">{assessedCase?.fraud_probability == null ? "Not assessed" : `${Math.round(assessedCase.fraud_probability * 100)}%`}</strong><small>Deterministic evidence assessment</small></article><article><span>Exposure</span><strong>{formatExposure(assessedCase?.exposure_usd)}</strong><small>{data.timeline?.length ?? 0} transaction(s) returned</small></article><article><span>Pattern</span><strong>{assessedCase?.pattern?.replaceAll("_", " ") || "Not assessed"}</strong><small>Evidence-derived pattern</small></article><article><span>Status</span><strong>{assessedCase?.status || data.status || "Open"}</strong><small>{data.evidence_requests?.length ? "Awaiting evidence" : "Investigation state"}</small></article></section>
          <nav className="tabs" aria-label="Case workspace views">{tabs.map((item) => <button className={tab === item ? "active" : ""} key={item} onClick={() => setTab(item)} type="button">{item}</button>)}</nav>
          <section className="workspace-panel">
            {tab === "Overview" && <div className="overview-stack"><div className="metric-grid"><article><span>Flagged transaction</span><strong>{data.flagged_txn_id || "Not returned"}</strong></article><article><span>Bank risk score</span><strong className="risk-value">{data.risk_score ?? "Not returned"}</strong><small>Input signal only</small></article><article><span>Fraud probability</span><strong className="probability-value">{assessedCase?.fraud_probability == null ? "Not assessed" : `${Math.round(assessedCase.fraud_probability * 100)}%`}</strong><small>Deterministic evidence assessment</small></article><article><span>Exposure</span><strong>{formatExposure(assessedCase?.exposure_usd)}</strong></article></div><CaseIntegrity evidence={assessedCase?.evidence ?? []} requests={requests} auditCount={data.audit?.length ?? 0} status={assessedCase?.status || data.status} integrity={data.integrity} /></div>}
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
