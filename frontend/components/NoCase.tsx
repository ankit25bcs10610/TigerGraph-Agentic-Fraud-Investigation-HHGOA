"use client";

import { useMemo, useState } from "react";
import { humanize, relative, toNumber } from "../lib/format";
import { CaseOverview } from "../lib/types";
import { Icon } from "./icons";
import { Connection, sectionFor, View } from "./Sidebar";

/** What each section will contain once a case is open, so an empty section still teaches. */
const previews: Partial<Record<View, string[]>> = {
  overview: ["Risk score, exposure, pattern and fraud probability", "Relationship map around the flagged transaction", "Recommended next action and its approval route"],
  graph: ["Customer, card, transaction, device, email and region entities", "Hierarchy, force, circle and concentric layouts", "Select any entity to inspect its properties"],
  transactions: ["Every transaction for the customer, in time order", "Amount and risk score trend with the flagged payment marked", "Channel, region and email domain for each payment"],
  evidence: ["Grounded claims with their source and entities", "Evidence requests you can answer to resume the workflow", "Closed cases that match this one"],
  actions: ["Recommended actions before and after evidence", "Approval routes: automatic, L1 or L2", "Approve or reject protected actions"],
  report: ["Whether a suspicious activity report must be filed", "Subjects, amount and activity dates", "The report narrative, ready to copy or download"],
  audit: ["The tamper-evident hash chain for the case", "Every tool call and workflow event, credentials removed", "Verification that no event was changed after the fact"],
};

export function NoCase({ view, cases, connection, busy, onOpen, onLoadPack, onRetry }: { view: View; cases: CaseOverview[]; connection: Connection; busy: boolean; onOpen: (caseId: string, view: View) => void; onLoadPack: () => void; onRetry: () => void }) {
  const section = sectionFor(view);
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const matching = needle ? cases.filter((item) => Object.values(item).join(" ").toLowerCase().includes(needle)) : cases;
    // Highest supplied risk first, so the most urgent triggers are one click away.
    return [...matching].sort((a, b) => (toNumber(b.risk_score) ?? -1) - (toNumber(a.risk_score) ?? -1)).slice(0, 8);
  }, [cases, filter]);

  return <section className="no-case">
    <div className="no-case-intro">
      <span className="no-case-icon"><Icon name={section.icon} size={26} /></span>
      <h1>{section.title}</h1>
      <p>{section.hint}. Open a case to fill this view.</p>
      {previews[view] && <ul className="preview-list">{previews[view]!.map((line) => <li key={line}><Icon name="check" size={14} />{line}</li>)}</ul>}
    </div>

    <div className="panel picker">
      {connection !== "online" ? <div className="picker-empty">
        <Icon name={connection === "setup" ? "upload" : "radar"} size={22} />
        <strong>{connection === "setup" ? "No cases loaded yet" : connection === "checking" ? "Connecting to the API…" : "The investigation API isn't reachable"}</strong>
        <p>{connection === "setup" ? "Load your case_pack.csv to start investigating." : connection === "checking" ? "This takes a moment." : "Start the FastAPI service, then retry."}</p>
        {connection === "setup" && <button className="button primary" disabled={busy} onClick={onLoadPack} type="button"><Icon name="upload" size={16} />Choose case_pack.csv</button>}
        {connection === "offline" && <button className="button primary" onClick={onRetry} type="button"><Icon name="refresh" size={16} />Retry connection</button>}
      </div> : <>
        <header className="picker-head">
          <strong>Open a case in {section.label.toLowerCase()}</strong>
          <label className="picker-search"><Icon name="search" size={15} /><input aria-label="Filter cases" onChange={(event) => setFilter(event.target.value)} placeholder={`Filter ${cases.length} cases`} value={filter} /></label>
        </header>
        {!shown.length ? <p className="empty">No cases match “{filter}”.</p> : <ul className="picker-list">{shown.map((item) => {
          const risk = toNumber(item.risk_score);
          return <li key={item.case_id}><button disabled={busy} onClick={() => onOpen(item.case_id, view)} type="button">
            <span className="picker-id">{item.case_id}</span>
            <span className="picker-meta">{[item.trigger_type && humanize(item.trigger_type), relative(item.opened_at)].filter(Boolean).join(", ") || "Ready to investigate"}</span>
            {risk !== null && <span className="picker-risk"><span className="track"><i style={{ width: `${Math.min(1, Math.max(0, risk)) * 100}%` }} /></span>{risk.toFixed(2)}</span>}
            <Icon name="play" size={14} />
          </button></li>;
        })}</ul>}
        {cases.length > shown.length && <p className="picker-more">Showing {shown.length} of {cases.length}, highest risk first. Use the filter or the case queue to see the rest.</p>}
      </>}
    </div>
  </section>;
}
