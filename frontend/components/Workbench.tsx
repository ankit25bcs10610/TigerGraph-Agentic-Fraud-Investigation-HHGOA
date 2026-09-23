"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { dateTime, flaggedRow, humanize, initials, money, rowTime, verdictTone } from "../lib/format";
import { CaseOverview, EvidenceRequest, Investigation } from "../lib/types";
import { GraphEvidence } from "./GraphEvidence";
import { Icon } from "./icons";
import { Activity, CommandCenter } from "./CommandCenter";
import { NoCase } from "./NoCase";
import { Connection, sectionFor, Sidebar, View } from "./Sidebar";
import { ActionsView, allEvidence, EvidenceLedger, EvidenceRequests, EvidenceTable, KeyFigures, LinkButton, NextBestAction, Panel, redact, SarView, SimilarCases, WorkflowTimeline } from "./Panels";
import { AuditView } from "./Audit";
import { AgentReasoning, Explanation, PolicyGrounding } from "./Reasoning";
import { RelationshipMap } from "./RelationshipMap";
import { TransactionsView } from "./Transactions";

const connectionText: Record<Connection, string> = { checking: "Connecting", online: "System healthy", setup: "Case pack needed", offline: "API offline" };

function dayRange(values: (string | undefined)[]) {
  const stamps = values.map((value) => Date.parse(value ?? "")).filter(Number.isFinite);
  if (!stamps.length) return null;
  const format = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  return Math.min(...stamps) === Math.max(...stamps) ? format.format(stamps[0]) : format.formatRange(Math.min(...stamps), Math.max(...stamps));
}

function message(caught: unknown, fallback: string) {
  return caught instanceof Error ? caught.message : fallback;
}

function readCollapsed() {
  try { return window.localStorage.getItem("sentinel.nav.collapsed") === "1"; } catch { return false; }
}

export function Workbench() {
  const [connection, setConnection] = useState<Connection>(api.isConfigured ? "checking" : "offline");
  const [cases, setCases] = useState<CaseOverview[]>([]);
  const [selected, setSelected] = useState("");
  const [data, setData] = useState<Investigation | null>(null);
  const [view, setView] = useState<View>("command");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [visited, setVisited] = useState<Set<string>>(() => new Set());
  const [activity, setActivity] = useState<Activity[]>([]);
  const log = useCallback((text: string, tone: Activity["tone"], detail?: string) => setActivity((items) => [{ id: Date.now() + Math.random(), text, detail, tone, at: Date.now() }, ...items].slice(0, 30)), []);
  const refreshCases = useCallback(async () => { try { setCases(await api.overview()); } catch { /* keep the last list */ } }, []);
  const [toasts, setToasts] = useState<{ id: number; text: string; tone: "ok" | "warn" }[]>([]);
  const notify = useCallback((text: string, tone: "ok" | "warn" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items.slice(-2), { id, text, tone }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 4000);
  }, []);
  const searchRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [theme, setTheme] = useState<"dark" | "light">("light");
  useEffect(() => { setCollapsed(readCollapsed()); setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark"); }, []);
  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try { window.localStorage.setItem("sentinel.theme", next); } catch { /* storage unavailable */ }
  }
  useEffect(() => { try { window.localStorage.setItem("sentinel.nav.collapsed", collapsed ? "1" : "0"); } catch { /* storage unavailable */ } }, [collapsed]);

  const connect = useCallback(async () => {
    if (!api.isConfigured) { setConnection("offline"); return; }
    setConnection("checking"); setError("");
    try {
      const health = await api.health();
      if (!health.workflow_configured) { setConnection("setup"); setCases([]); return; }
      const items = await api.overview();
      setCases(items); setConnection("online");
      setSelected((current) => current || items[0]?.case_id || "");
    } catch (caught) {
      setConnection("offline"); setError(message(caught, "The investigation API could not be reached."));
    }
  }, []);
  useEffect(() => { void connect(); }, [connect]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === "Escape") setBellOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = useCallback(async (caseId: string, target: View = "overview") => {
    if (!caseId) return;
    setSelected(caseId); setBusy(true); setError("");
    try {
      const state = await api.start(caseId);
      setData(state); setVisited((seen) => new Set(seen).add(caseId)); setView(target);
      log(`Investigation run on ${caseId}`, state.case?.verdict === "fraud" ? "risk" : state.case?.verdict === "uncertain" ? "warn" : "info", state.case?.verdict ? `${humanize(state.case.verdict)}, ${humanize(state.status ?? "")}` : humanize(state.status ?? ""));
      void refreshCases();
    }
    catch (caught) { setError(message(caught, "The investigation could not be started.")); }
    finally { setBusy(false); }
  }, [log, refreshCases]);

  async function uploadPack(file: File) {
    setBusy(true); setError("");
    try {
      await api.uploadCasePack(file);
      const items = await api.overview();
      setCases(items); setSelected(items[0]?.case_id ?? ""); setData(null); setVisited(new Set()); setConnection("online"); setView("command");
      notify(`Loaded ${items.length} case${items.length === 1 ? "" : "s"} from ${file.name}`);
      log(`Case pack loaded: ${items.length} cases`, "info", file.name);
    } catch (caught) { setError(message(caught, "The case pack could not be loaded.")); }
    finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  async function approve(action: string, approved: boolean) {
    if (!data) return;
    setBusy(true); setError("");
    try {
      setData(await api.approve(data.case_id, action, approved));
      notify(`${humanize(action)} ${approved ? "approved" : "rejected"} and sealed in the audit log`, approved ? "ok" : "warn");
      log(`${humanize(action)} ${approved ? "approved" : "rejected"}`, approved ? "ok" : "warn", data.case_id);
      void refreshCases();
    }
    catch (caught) { setError(message(caught, "The approval decision could not be recorded.")); }
    finally { setBusy(false); }
  }

  async function submitEvidence(request: EvidenceRequest, result: string, details: string) {
    if (!data) return;
    setBusy(true); setError("");
    try {
      setData(await api.evidence(data.case_id, request, result, details));
      notify(`Response recorded: ${humanize(result)}`);
      log(`${humanize(request.type)}: ${humanize(result)}`, result === "denied" || result === "failed" ? "risk" : "ok", data.case_id);
      void refreshCases();
    }
    catch (caught) { setError(message(caught, "The evidence response could not be recorded.")); }
    finally { setBusy(false); }
  }

  function exportCase() {
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
      integrity: data.integrity,
      audit: redact(data.audit ?? []),
      provenance: "Exported from the Sentinel workbench. Every value was returned by the investigation API; the browser performs no fraud inference.",
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(dossier, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${data.case_id}-dossier.json`; anchor.click(); URL.revokeObjectURL(url);
  }

  const alerts = useMemo<{ key: string; text: string; view: View; caseId?: string }[]>(() => {
    const queue = cases.filter((item) => item.assessment?.pending_approvals.length && item.case_id !== data?.case_id).map((item) => ({ key: `q-${item.case_id}`, text: `${item.case_id}: ${item.assessment!.pending_approvals.map((approval) => `${humanize(approval.action)} (${approval.route})`).join(", ")}`, view: "command" as View, caseId: item.case_id }));
    if (!data) return queue;
    const approvals = (data.approval_requests ?? []).filter((item) => item.approval_status === "pending").map((item) => ({ key: `a-${item.action}`, text: `${humanize(item.action)} needs ${item.route} approval`, view: "actions" as View }));
    const answered = new Set((data.evidence_responses ?? []).map((item) => (item as { request_id?: string }).request_id));
    const requests = (data.evidence_requests ?? []).filter((item) => item.status !== "completed" && !answered.has(item.request_id)).map((item) => ({ key: `e-${item.request_id}`, text: item.question, view: "evidence" as View }));
    return [...approvals, ...requests, ...queue];
  }, [data, cases]);

  const openFromQueue = useCallback((id: string) => { void run(id); }, [run]);
  const identity = api.identity;
  const position = data ? cases.findIndex((item) => item.case_id === data.case_id) : -1;
  const neighbours = { previous: position > 0 ? cases[position - 1].case_id : undefined, next: position >= 0 && position < cases.length - 1 ? cases[position + 1].case_id : undefined, position: position + 1, total: cases.length };
  const current = view;
  const page = sectionFor(current);
  const range = dayRange(cases.map((item) => item.opened_at));

  return <div className={`shell ${collapsed ? "collapsed" : ""}`}>
    <Sidebar busy={busy} caseCount={cases.length} collapsed={collapsed} connection={connection} data={data} onLoadPack={() => fileRef.current?.click()} onNavigate={setView} onRetry={() => void connect()} onToggle={() => setCollapsed(!collapsed)} view={view} />
    <input accept=".csv,text/csv" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadPack(file); }} ref={fileRef} type="file" />

    <div className="main">
      <header className="topbar">
        <div className="page-title"><h1>{page.title}</h1><p>{page.hint}</p></div>
        <label className="search"><Icon name="search" size={16} /><input aria-label="Search cases" onChange={(event) => { setQuery(event.target.value); if (event.target.value) setView("command"); }} placeholder="Search cases, customers, transactions or findings…" ref={searchRef} value={query} /><kbd>Ctrl K</kbd></label>
        {range && <span className="range-chip" title="Dates the loaded cases were opened"><Icon name="ledger" size={15} />{range}</span>}
        <div className="topbar-right">
          <button className={`status ${connection}`} onClick={() => void connect()} title="Check the API connection again" type="button"><i />{connectionText[connection]}</button>
          <button aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} className="icon-button theme-toggle" onClick={toggleTheme} title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} type="button"><Icon name={theme === "dark" ? "sun" : "moon"} /></button>
          <div className="bell-wrap">
            <button aria-expanded={bellOpen} aria-label={`${alerts.length} items need attention`} className="icon-button" onClick={() => setBellOpen(!bellOpen)} type="button"><Icon name="bell" />{alerts.length > 0 && <b className="badge">{alerts.length}</b>}</button>
            {bellOpen && <div className="bell-menu" role="menu">{alerts.length ? alerts.map((alert) => <button key={alert.key} onClick={() => { setBellOpen(false); if (alert.caseId) void run(alert.caseId, "actions"); else setView(alert.view); }} role="menuitem" type="button">{alert.text}</button>) : <p>Nothing needs your attention.</p>}</div>}
          </div>
          {(identity.name || identity.role) && <span className="who"><span className="avatar">{initials(identity.name || identity.role)}</span><span><b>{identity.name || humanize(identity.role)}</b>{identity.name && identity.role && <small>{humanize(identity.role)}</small>}</span></span>}
        </div>
      </header>

      {busy && <div aria-hidden="true" className="progress" />}
      <div aria-live="polite" className="toasts">{toasts.map((toast) => <div className={`toast ${toast.tone}`} key={toast.id} role="status"><Icon name={toast.tone === "ok" ? "check" : "target"} size={16} />{toast.text}</div>)}</div>
      <main aria-busy={busy} className="content">
        {error && <div className="alert" role="alert"><strong>{error}</strong>{connection === "offline" && <button className="button ghost" onClick={() => void connect()} type="button"><Icon name="refresh" size={15} />Retry</button>}<button aria-label="Dismiss" className="icon-button small" onClick={() => setError("")} type="button"><Icon name="x" size={14} /></button></div>}
        {!api.isConfigured && <div className="alert"><strong>Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local, then restart the workbench.</strong></div>}

        {current === "command" ? <CommandCenter activity={activity} busy={busy} cases={cases} connection={connection} onLoadPack={() => fileRef.current?.click()} onOpen={openFromQueue} onRetry={() => void connect()} query={query} selected={selected} theme={theme} visited={visited} /> : !data ? <NoCase busy={busy} cases={cases} connection={connection} onLoadPack={() => fileRef.current?.click()} onOpen={(id, target) => void run(id, target)} onRetry={() => void connect()} view={current} /> : <>
          <CaseHeader busy={busy} data={data} neighbours={neighbours} onExport={exportCase} onOpen={(id) => void run(id, current)} onRun={() => void run(data.case_id, current)} />
          {current === "overview" && <>
            <KeyFigures data={data} />
            <div className="grid">
              <div className="col-main">
                <RelationshipMap graph={data.graph} onExpand={() => setView("graph")} />
                <WorkflowTimeline data={data} />
              </div>
              <NextBestAction busy={busy} data={data} onApprove={(action, ok) => void approve(action, ok)} onOpenEvidence={() => setView("evidence")} />
            </div>
            <div className="grid lower reasoning-row">
              <AgentReasoning data={data} />
              <Explanation data={data} />
            </div>
            <div className="grid lower">
              <Panel action={allEvidence(data).length > 4 ? <LinkButton onClick={() => setView("evidence")}>View all {allEvidence(data).length}</LinkButton> : undefined} icon="doc" subtitle="Grounded claims, each tied to a source and the entities it concerns" title="Evidence ledger"><EvidenceTable items={allEvidence(data)} limit={4} /></Panel>
              <Panel action={(data.similar_cases?.length ?? 0) > 3 ? <LinkButton onClick={() => setView("evidence")}>View all</LinkButton> : undefined} icon="folder" subtitle="Closed cases retrieved by graph and text similarity" title="Similar cases"><SimilarCases limit={3} rows={data.similar_cases ?? []} /></Panel>
            </div>
          </>}
          {current === "graph" && <GraphEvidence graph={data.graph} theme={theme} />}
          {current === "transactions" && <TransactionsView data={data} />}
          {current === "evidence" && <>
            {(data.evidence_requests?.length ?? 0) > 0 && <Panel icon="target" subtitle="Record what the customer or step-up check returned. The workflow resumes with your answer." title="Evidence requests"><EvidenceRequests busy={busy} onSubmit={(request, result, details) => void submitEvidence(request, result, details)} requests={data.evidence_requests ?? []} responses={data.evidence_responses ?? []} /></Panel>}
            <Panel icon="doc" subtitle="Grounded claims, each tied to a source and the entities it concerns" title="Evidence ledger"><EvidenceLedger items={allEvidence(data)} /></Panel>
            <Panel icon="folder" subtitle="Closed cases retrieved by graph and text similarity" title="Similar cases"><SimilarCases rows={data.similar_cases ?? []} /></Panel>
          </>}
          {current === "actions" && <><ActionsView busy={busy} data={data} onApprove={(action, ok) => void approve(action, ok)} /><PolicyGrounding items={data.policy_grounding ?? []} /></>}
          {current === "report" && <SarView data={data} />}
          {current === "audit" && <AuditView data={data} />}
        </>}
      </main>
    </div>
  </div>;
}

type Neighbours = { previous?: string; next?: string; position: number; total: number };

function CaseHeader({ data, busy, neighbours, onRun, onExport, onOpen }: { data: Investigation; busy: boolean; neighbours: Neighbours; onRun: () => void; onExport: () => void; onOpen: (caseId: string) => void }) {
  const row = flaggedRow(data);
  const verdict = data.case?.verdict;
  const tone = verdictTone(verdict);
  const meta: [string, string | null | undefined][] = [
    ["Customer", data.customer_id],
    ["Card", data.card_id],
    ["Transaction", data.flagged_txn_id],
    ["Amount", money(row?.transaction_amt ?? row?.amount_usd)],
    ["Time", dateTime(rowTime(row ?? {}) ?? data.opened_at)],
    ["Channel", row?.channel ? humanize(row.channel) : null],
    ["Region", row?.billing_region],
  ];
  return <section className="case-header">
    <div className="case-title">
      <div className="case-name"><h1>{data.case_id}</h1><span className={`verdict ${tone}`}>{verdict ? humanize(verdict) : humanize(data.case?.status ?? data.status ?? "open")}</span>{data.trigger_type && <span className="tag muted">{humanize(data.trigger_type)}</span>}</div>
      <p>{data.case?.summary || data.trigger_text || data.message}</p>
      {data.message && data.message !== (data.case?.summary || data.trigger_text) && <p className="case-note"><Icon name="target" size={14} />{data.message}</p>}
    </div>
    <dl className="case-meta">{meta.filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    <div className="case-actions">
      {neighbours.position > 0 && <div className="stepper" role="group" aria-label="Move between cases">
        <button aria-label={neighbours.previous ? `Previous case, ${neighbours.previous}` : "No previous case"} className="icon-button" disabled={busy || !neighbours.previous} onClick={() => neighbours.previous && onOpen(neighbours.previous)} type="button"><Icon name="collapse" size={16} /></button>
        <span>{neighbours.position} of {neighbours.total}</span>
        <button aria-label={neighbours.next ? `Next case, ${neighbours.next}` : "No next case"} className="icon-button" disabled={busy || !neighbours.next} onClick={() => neighbours.next && onOpen(neighbours.next)} type="button"><Icon name="collapse" size={16} style={{ transform: "rotate(180deg)" }} /></button>
      </div>}
      <button className="button light" disabled={busy} onClick={onRun} type="button"><Icon name={busy ? "refresh" : "play"} size={15} className={busy ? "spin" : undefined} />{busy ? "Running…" : "Run investigation"}</button>
      <button className="button ghost" onClick={onExport} type="button"><Icon name="download" size={15} />Export case</button>
    </div>
  </section>;
}

