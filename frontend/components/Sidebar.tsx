"use client";

import { humanize, verdictTone } from "../lib/format";
import { Investigation } from "../lib/types";
import { Icon, IconName } from "./icons";

export type View = "overview" | "cases" | "graph" | "transactions" | "evidence" | "actions" | "report" | "audit";
export type Connection = "checking" | "online" | "setup" | "offline";

type Item = { view: View; label: string; hint: string; icon: IconName };

export const sections: { title: string; items: Item[] }[] = [
  { title: "Workspace", items: [
    { view: "cases", label: "Case queue", hint: "Every case in the loaded case pack", icon: "queue" },
    { view: "overview", label: "Investigation", hint: "The full picture for one case", icon: "radar" },
  ] },
  { title: "Case analysis", items: [
    { view: "graph", label: "Graph explorer", hint: "Entities and links around the flagged transaction", icon: "graph" },
    { view: "transactions", label: "Transactions", hint: "Customer history around the flagged transaction", icon: "swap" },
    { view: "evidence", label: "Evidence", hint: "Grounded claims, open requests and similar cases", icon: "doc" },
    { view: "actions", label: "Actions & approvals", hint: "Recommended actions and approval decisions", icon: "shield" },
  ] },
  { title: "Records", items: [
    { view: "report", label: "SAR report", hint: "Suspicious activity report draft", icon: "ledger" },
    { view: "audit", label: "Audit log", hint: "Sealed events and tool calls", icon: "pulse" },
  ] },
];

export const sectionFor = (view: View) => sections.flatMap((group) => group.items).find((item) => item.view === view)!;

type Badge = { value: string | number; tone?: "risk" | "warn" | "ok" };

/** Counts shown beside each section, all taken from the open investigation. */
function badges(data: Investigation | null, caseCount: number): Partial<Record<View, Badge>> {
  const result: Partial<Record<View, Badge>> = {};
  if (caseCount) result.cases = { value: caseCount };
  if (!data) return result;
  const pending = (data.approval_requests ?? []).filter((item) => item.approval_status === "pending").length;
  const answered = new Set((data.evidence_responses ?? []).map((item) => (item as { request_id?: string }).request_id));
  const open = (data.evidence_requests ?? []).filter((item) => item.status !== "completed" && !answered.has(item.request_id)).length;
  const evidence = (data.case?.evidence?.length ?? 0) + (data.evidence_responses?.length ?? 0);
  if (data.graph?.nodes.length) result.graph = { value: data.graph.nodes.length };
  if (data.timeline?.length) result.transactions = { value: data.timeline.length };
  if (open) result.evidence = { value: `${open} open`, tone: "warn" };
  else if (evidence) result.evidence = { value: evidence };
  if (pending) result.actions = { value: pending, tone: "risk" };
  if (data.sar?.file) result.report = { value: "File", tone: "risk" };
  if (data.integrity?.event_count ?? data.audit?.length) result.audit = { value: data.integrity?.event_count ?? data.audit?.length ?? 0 };
  return result;
}

const connectionText: Record<Connection, [string, string]> = {
  checking: ["Connecting", "Checking the investigation API"],
  online: ["API connected", "Cases loaded and ready"],
  setup: ["Case pack needed", "API is running with no cases"],
  offline: ["API offline", "Start the API, then retry"],
};

export function Sidebar({ view, data, caseCount, connection, collapsed, busy, onNavigate, onLoadPack, onToggle, onRetry }: { view: View; data: Investigation | null; caseCount: number; connection: Connection; collapsed: boolean; busy: boolean; onNavigate: (view: View) => void; onLoadPack: () => void; onToggle: () => void; onRetry: () => void }) {
  const counts = badges(data, caseCount);
  const tone = verdictTone(data?.case?.verdict);
  const [status, detail] = connectionText[connection];
  return <aside className="sidebar">
    <div className="brand">
      <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M16 2 29 9.5v13L16 30 3 22.5v-13z" /><path d="M16 9 23 13v6l-7 4-7-4v-6z" /></svg></span>
      <div className="brand-text"><strong>Sentinel</strong><small>Graph fraud investigation</small></div>
    </div>

    <button className={`active-case ${data ? "open" : ""}`} onClick={() => onNavigate(data ? "overview" : "cases")} title={collapsed ? (data ? `Open case ${data.case_id}` : "No case open") : undefined} type="button">
      <span className={`case-dot ${tone}`} aria-hidden="true">{data ? <Icon name="radar" size={16} /> : <Icon name="queue" size={16} />}</span>
      <span className="active-case-text">
        {data ? <><small>Open case</small><strong>{data.case_id}</strong><em>{data.case?.verdict ? humanize(data.case.verdict) : humanize(data.trigger_type ?? data.status ?? "In review")}</em></>
          : <><small>No case open</small><strong>{caseCount ? "Pick one from the queue" : "Load a case pack"}</strong></>}
      </span>
    </button>

    <nav aria-label="Sections" className="nav-scroll">
      {sections.map((group) => <div className="nav-group" key={group.title}>
        <p className="nav-title">{group.title}</p>
        {group.items.map((item) => {
          const badge = counts[item.view];
          return <button aria-current={view === item.view ? "page" : undefined} className={`nav-item ${!data && item.view !== "cases" ? "waiting" : ""}`} key={item.view} onClick={() => onNavigate(item.view)} title={collapsed ? item.label : item.hint} type="button">
            <Icon name={item.icon} />
            <span>{item.label}</span>
            {badge && <b className={`count ${badge.tone ?? ""}`}>{badge.value}</b>}
          </button>;
        })}
      </div>)}
    </nav>

    <div className="sidebar-foot">
      <button className={`api-card ${connection}`} onClick={onRetry} title="Check the connection again" type="button">
        <i aria-hidden="true" />
        <span><strong>{status}</strong><small>{detail}</small></span>
        <Icon className={connection === "checking" ? "spin" : undefined} name="refresh" size={14} />
      </button>
      <button className="nav-item upload" disabled={busy} onClick={onLoadPack} title={collapsed ? "Load case pack" : undefined} type="button"><Icon name="upload" /><span>{caseCount ? "Replace case pack" : "Load case pack"}</span></button>
      <button aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="nav-item" onClick={onToggle} type="button"><Icon name="collapse" style={{ transform: collapsed ? "rotate(180deg)" : undefined }} /><span>Collapse</span></button>
    </div>
  </aside>;
}
