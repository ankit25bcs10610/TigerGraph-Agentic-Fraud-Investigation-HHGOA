"use client";

import { ReactNode, useState } from "react";
import { clock, dateTime, flaggedRow, humanize, money, percent, rowAmount, rowTime, toNumber } from "../lib/format";
import { Action, ApprovalRequest, Evidence, EvidenceRequest, Investigation, LedgerEntry, SimilarCase, TimelineRow } from "../lib/types";
import { Icon, IconName } from "./icons";

export function Panel({ icon, title, subtitle, action, className = "", children }: { icon: IconName; title: string; subtitle?: string; action?: ReactNode; className?: string; children: ReactNode }) {
  return <section className={`panel ${className}`}>
    <header className="panel-head"><span className="panel-icon"><Icon name={icon} /></span><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</header>
    {children}
  </section>;
}

export function LinkButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return <button className="link-button" onClick={onClick} type="button">{children}</button>;
}

/* ---------- Key figures ---------- */

function Sparkline({ values, highlight }: { values: number[]; highlight?: number }) {
  if (values.length < 2) return null;
  const max = Math.max(...values); const min = Math.min(...values); const span = max - min || 1;
  const points = values.map((value, index) => [(index / (values.length - 1)) * 120, 34 - ((value - min) / span) * 30]);
  const path = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const marker = highlight !== undefined ? points[highlight] : undefined;
  return <svg aria-hidden="true" className="spark" viewBox="-2 -2 124 40"><path className="spark-area" d={`${path} L120 38 L0 38Z`} /><path className="spark-line" d={path} />{marker && <circle cx={marker[0]} cy={marker[1]} r="3" />}</svg>;
}

function Bars({ values, highlight }: { values: number[]; highlight?: number }) {
  if (!values.length) return null;
  const max = Math.max(...values) || 1;
  return <svg aria-hidden="true" className="bars" viewBox={`0 0 ${values.length * 9} 38`}>{values.map((value, index) => { const height = Math.max(2, (value / max) * 36); return <rect className={index === highlight ? "hot" : ""} height={height} key={index} rx="1" width="5" x={index * 9 + 2} y={38 - height} />; })}</svg>;
}

function Gauge({ value }: { value: number }) {
  const clamped = Math.min(1, Math.max(0, value));
  return <div aria-hidden="true" className="gauge"><i style={{ width: `${clamped * 100}%` }} /><b style={{ left: `${clamped * 100}%` }} /></div>;
}

function Meter({ value }: { value: number }) {
  return <div aria-hidden="true" className="meter">{Array.from({ length: 12 }, (_, index) => <i className={(index + 0.5) / 12 <= value ? "on" : ""} key={index} style={{ height: `${10 + index * 2.4}px` }} />)}</div>;
}

export function KeyFigures({ data }: { data: Investigation }) {
  const rows = data.timeline ?? [];
  const flagged = flaggedRow(data);
  const flaggedIndex = flagged ? rows.indexOf(flagged) : undefined;
  const risks = rows.map((row) => toNumber(row.risk_score)).filter((value): value is number => value !== null);
  const amounts = rows.map((row) => rowAmount(row) ?? 0);
  const risk = toNumber(data.risk_score ?? flagged?.risk_score);
  const previousRisk = flaggedIndex && flaggedIndex > 0 ? toNumber(rows[flaggedIndex - 1].risk_score) : null;
  const delta = risk !== null && previousRisk !== null ? risk - previousRisk : null;
  const assessed = data.case;
  const probability = toNumber(assessed?.fraud_probability);
  const total = amounts.reduce((sum, value) => sum + value, 0);

  return <section className="figures" aria-label="Key figures">
    <article className="figure">
      <span className="figure-label">Bank risk score</span>
      <div className="figure-row"><strong>{risk === null ? "—" : risk.toFixed(2)}</strong>{delta !== null && delta !== 0 && <em className={delta > 0 ? "up" : "down"}>{delta > 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(2)}</em>}</div>
      <small>{delta !== null ? "Change from the previous transaction" : "Source input signal, not a verdict"}</small>
      {risks.length > 1 ? <Sparkline highlight={flagged && toNumber(flagged.risk_score) !== null ? rows.slice(0, flaggedIndex).filter((row) => toNumber(row.risk_score) !== null).length : undefined} values={risks} /> : risk !== null && risk <= 1 && <Gauge value={risk} />}
    </article>
    <article className="figure">
      <span className="figure-label">Exposure</span>
      <div className="figure-row"><strong className={money(assessed?.exposure_usd) ? "" : "pending"}>{money(assessed?.exposure_usd, true) ?? "Not assessed"}</strong></div>
      <small>{rows.length ? `${rows.length} transaction${rows.length === 1 ? "" : "s"} totalling ${money(total, true)}` : "No transaction history returned"}</small>
      <Bars highlight={flaggedIndex} values={amounts} />
    </article>
    <article className="figure">
      <span className="figure-label">Pattern</span>
      <div className="figure-row"><strong className={assessed?.pattern ? "figure-text" : "pending"}>{assessed?.pattern ? humanize(assessed.pattern) : "Not assessed"}</strong></div>
      <small>{assessed?.verdict ? `Verdict: ${humanize(assessed.verdict)}` : "Detected from graph and behaviour evidence"}</small>
      <Icon className="figure-glyph" name="graph" size={40} />
    </article>
    <article className="figure">
      <span className="figure-label">Fraud probability</span>
      <div className="figure-row"><strong className={probability === null ? "pending" : ""}>{percent(probability) ?? "Not assessed"}</strong></div>
      <small>{probability === null ? "Available after the full workflow runs" : "Deterministic evidence assessment"}</small>
      {probability !== null && <Meter value={probability} />}
    </article>
  </section>;
}

/* ---------- Workflow timeline ---------- */

export function WorkflowTimeline({ data }: { data: Investigation }) {
  const ledger: Pick<LedgerEntry, "event_type" | "recorded_at">[] = data.integrity_ledger?.length ? data.integrity_ledger : (data.audit ?? []).map((event) => ({ event_type: String(event.type ?? event.tool ?? "event"), recorded_at: String(event.recorded_at ?? event.timestamp ?? "") }));
  const pendingApprovals = (data.approval_requests ?? []).filter((item) => item.approval_status === "pending");
  const openRequests = (data.evidence_requests ?? []).filter((item) => item.status !== "completed" && !(data.evidence_responses ?? []).some((response) => (response as { request_id?: string }).request_id === item.request_id));
  const waiting = pendingApprovals.length ? { title: "Awaiting approval", detail: `${pendingApprovals.length} ${pendingApprovals[0].route} action${pendingApprovals.length === 1 ? "" : "s"}` } : openRequests.length ? { title: "Awaiting evidence", detail: `${openRequests.length} open request${openRequests.length === 1 ? "" : "s"}` } : null;
  return <Panel icon="pulse" subtitle="Each step is a sealed event from the investigation workflow" title="Investigation timeline">
    {!ledger.length ? <p className="empty">Workflow events appear here once the investigation starts.</p> :
    <ol className="steps">
      {ledger.map((entry, index) => <li className="done" key={`${entry.event_type}-${index}`}><span className="step-dot"><Icon name="check" size={13} /></span><strong>{humanize(entry.event_type)}</strong><small>{clock(entry.recorded_at) ?? "Time not recorded"}</small></li>)}
      {waiting && <li className="waiting"><span className="step-dot" /><strong>{waiting.title}</strong><small>{waiting.detail}</small></li>}
    </ol>}
  </Panel>;
}

/* ---------- Next best action ---------- */

const routeText: Record<string, string> = { auto: "Runs automatically under policy", L1: "Needs L1 analyst approval", L2: "Needs L2 approver sign-off" };

export function NextBestAction({ data, busy, onApprove, onOpenEvidence }: { data: Investigation; busy: boolean; onApprove: (action: string, approved: boolean) => void; onOpenEvidence: () => void }) {
  const plan = data.next_best_actions;
  const actions: Action[] = plan?.final?.length ? plan.final : plan?.initial ?? [];
  const [primary, ...rest] = actions;
  const pending = (data.approval_requests ?? []).filter((item) => item.approval_status === "pending");
  const decided = (data.approval_requests ?? []).filter((item) => item.approval_status !== "pending");
  const probability = percent(data.case?.fraud_probability);
  const requests = data.evidence_requests ?? [];
  return <Panel className="nba" icon="target" title="Next best action" subtitle="Selected by policy rules from the evidence">
    {!primary ? <p className="empty">{data.case?.verdict === "legitimate" ? "No action needed. The evidence closed this case as legitimate." : data.case?.verdict ? "Policy rules recommended no action for this evidence." : "No action has been recommended yet. The policy step runs after evidence is assessed."}</p> : <>
      <div className="nba-hero">
        {probability && <div className="nba-score"><strong>{probability}</strong><span>Fraud probability</span></div>}
        <div><span className={`route route-${primary.route.toLowerCase()}`}>{primary.route === "auto" ? "Auto" : primary.route}</span><h3>{humanize(primary.action)}</h3><p>{primary.reason}</p></div>
      </div>
      {rest.length > 0 && <ol className="nba-list">{rest.map((item, index) => <li key={`${item.action}-${index}`}><span className="nba-rank">{index + 2}</span><div><strong>{humanize(item.action)}</strong><small>{item.reason}</small></div><span className={`route route-${item.route.toLowerCase()}`}>{item.route === "auto" ? "Auto" : item.route}</span></li>)}</ol>}
      {plan?.what_changed && plan.what_changed !== "nothing" && <p className="nba-change"><b>What changed:</b> {plan.what_changed}</p>}
    </>}
    <div className="policy">
      <Icon name="shield" size={20} />
      <div>
        <span>Policy route</span>
        <strong>{pending.length ? `${pending[0].route} approval required` : primary ? routeText[primary.route] ?? primary.route : "No route yet"}</strong>
        <small>{pending.length ? pending[0].reason : decided.length ? `${decided.length} approval decision${decided.length === 1 ? "" : "s"} recorded` : "Protected actions never run without a recorded human decision."}</small>
      </div>
    </div>
    <div className="nba-buttons">
      {pending.length ? <>
        <button className="button primary" disabled={busy} onClick={() => onApprove(pending[0].action, true)} type="button"><Icon name="check" size={16} />Approve {humanize(pending[0].action).toLowerCase()}</button>
        <button className="button ghost" disabled={busy} onClick={() => onApprove(pending[0].action, false)} type="button">Reject</button>
      </> : <button className="button ghost wide" disabled={!requests.length} onClick={onOpenEvidence} type="button"><Icon name="doc" size={16} />{requests.length ? `Answer ${requests.length} evidence request${requests.length === 1 ? "" : "s"}` : "No evidence requested"}</button>}
    </div>
  </Panel>;
}

/* ---------- Evidence ---------- */

/** Assessed evidence plus recorded responses, skipping responses the assessment already cites. */
export function allEvidence(data: Investigation): Evidence[] {
  const assessed = data.case?.evidence ?? [];
  const cited = new Set(assessed.map((item) => item.ref));
  return [...assessed, ...(data.evidence_responses ?? []).filter((item) => !cited.has(item.ref))];
}

export function EvidenceTable({ items, limit }: { items: Evidence[]; limit?: number }) {
  const shown = limit ? items.slice(0, limit) : items;
  if (!items.length) return <p className="empty">No grounded evidence has been returned for this case yet.</p>;
  return <div className="table-wrap"><table className="data-table">
    <thead><tr><th>Claim</th><th>Source</th><th>Entities</th><th>Reference</th></tr></thead>
    <tbody>{shown.map((item, index) => <tr key={`${item.ref}-${index}`}>
      <td className="claim">{item.claim ?? `${humanize(item.result)}${item.details ? `: ${item.details}` : ""}`}{item.simulated && <span className="tag warn">Simulated{item.assumption ? `: ${item.assumption}` : ""}</span>}</td>
      <td><span className="tag">{humanize(item.source)}</span></td>
      <td className="ids">{item.entity_ids?.length ? item.entity_ids.join(", ") : "—"}</td>
      <td className="ids">{item.ref ?? "—"}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function EvidenceLedger({ items }: { items: Evidence[] }) {
  const [source, setSource] = useState("all");
  const sources = [...new Set(items.map((item) => item.source || "unknown"))];
  const shown = source === "all" ? items : items.filter((item) => (item.source || "unknown") === source);
  return <>
    {sources.length > 1 && <div className="chips" role="group" aria-label="Filter by source">
      <button aria-pressed={source === "all"} onClick={() => setSource("all")} type="button">All sources<b>{items.length}</b></button>
      {sources.map((name) => <button aria-pressed={source === name} key={name} onClick={() => setSource(name)} type="button">{humanize(name)}<b>{items.filter((item) => (item.source || "unknown") === name).length}</b></button>)}
    </div>}
    <EvidenceTable items={shown} />
  </>;
}

const resultOptions: Record<EvidenceRequest["type"], string[]> = {
  customer_validation: ["confirmed", "denied", "no_reply"],
  step_up_auth: ["passed", "failed", "not_completed"],
  analyst_info: ["confirmed", "denied", "unknown"],
};

export function EvidenceRequests({ requests, responses, busy, onSubmit }: { requests: EvidenceRequest[]; responses: Evidence[]; busy: boolean; onSubmit: (request: EvidenceRequest, result: string, details: string) => void }) {
  const [answers, setAnswers] = useState<Record<string, { result: string; details: string }>>({});
  if (!requests.length) return null;
  return <div className="requests">{requests.map((request) => {
    const answer = answers[request.request_id] ?? { result: resultOptions[request.type]?.[0] ?? "unknown", details: "" };
    const update = (patch: Partial<typeof answer>) => setAnswers({ ...answers, [request.request_id]: { ...answer, ...patch } });
    const recorded = responses.find((item) => (item as { request_id?: string }).request_id === request.request_id);
    if (recorded || request.status === "completed") return <article className="request answered" key={request.request_id}>
      <div className="request-head"><span className="tag">{humanize(request.type)}</span><span className="tag ok">Answered</span></div>
      <strong>{request.question}</strong>
      <p>{recorded ? <><b>{humanize(recorded.result ?? "recorded")}</b>{recorded.details ? `: ${recorded.details}` : ""}</> : "Response recorded."}</p>
    </article>;
    return <form className="request" key={request.request_id} onSubmit={(event) => { event.preventDefault(); onSubmit(request, answer.result, answer.details); }}>
      <div className="request-head"><span className="tag">{humanize(request.type)}</span>{request.status && <span className="tag muted">{humanize(request.status)}</span>}</div>
      <strong>{request.question}</strong>
      <p>{request.reason}</p>
      <div className="request-fields">
        <label>Result<select value={answer.result} onChange={(event) => update({ result: event.target.value })}>{(resultOptions[request.type] ?? ["unknown"]).map((option) => <option key={option} value={option}>{humanize(option)}</option>)}</select></label>
        <label className="grow">Details<input placeholder="What the customer or system reported" value={answer.details} onChange={(event) => update({ details: event.target.value })} /></label>
        <button className="button primary" disabled={busy} type="submit">Record response</button>
      </div>
    </form>;
  })}</div>;
}

/* ---------- Similar cases ---------- */

export function SimilarCases({ rows, limit }: { rows: SimilarCase[]; limit?: number }) {
  const shown = limit ? rows.slice(0, limit) : rows;
  if (!rows.length) return <p className="empty">No comparable closed cases were retrieved for this investigation.</p>;
  return <div className="similar">{shown.map((row, index) => <article key={String(row.case_id ?? index)}>
    <div className="similar-head"><strong>{row.case_id ?? "Closed case"}</strong>{row.outcome && <span className={`tag ${/fraud|confirm/i.test(row.outcome) ? "risk" : /review|pending/i.test(row.outcome) ? "warn" : "ok"}`}>{humanize(row.outcome)}</span>}</div>
    <dl>
      {row.pattern && <div><dt>Pattern</dt><dd>{humanize(row.pattern)}</dd></div>}
      {toNumber(row.similarity_score) !== null && <div><dt>Retrieval score</dt><dd>{toNumber(row.similarity_score)!.toFixed(2)}</dd></div>}
    </dl>
    <p>{row.reason_for_match ?? row.matched_text ?? "No match explanation returned."}</p>
  </article>)}</div>;
}

/* ---------- Transactions ---------- */

export function TransactionsTable({ rows }: { rows: TimelineRow[] }) {
  if (!rows.length) return <p className="empty">No transactions were returned. Set TRANSACTIONS_PATH on the API to load transaction context.</p>;
  const columns: [keyof TimelineRow, string][] = [["channel", "Channel"], ["billing_region", "Region"], ["email_domain", "Email domain"], ["device_profile_id", "Device"]];
  const present = columns.filter(([key]) => rows.some((row) => row[key]));
  return <div className="table-wrap"><table className="data-table">
    <thead><tr><th>Transaction</th><th>Time</th><th className="num">Amount</th><th className="num">Risk score</th>{present.map(([, label]) => <th key={label}>{label}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr className={row.suspicious ? "flag-row" : ""} key={String(row.transaction_id ?? index)}>
      <td className="ids">{row.transaction_id ?? "—"}{row.suspicious ? <span className="tag risk">Flagged</span> : row.in_episode && <span className="tag warn">In episode</span>}</td>
      <td>{dateTime(rowTime(row)) ?? "—"}</td>
      <td className="num">{money(rowAmount(row)) ?? "—"}</td>
      <td className="num">{toNumber(row.risk_score)?.toFixed(2) ?? "—"}</td>
      {present.map(([key, label]) => <td key={label}>{String(row[key] ?? "—")}</td>)}
    </tr>)}</tbody>
  </table></div>;
}

/* ---------- Actions ---------- */

function ActionColumn({ title, items }: { title: string; items?: Action[] }) {
  return <div className="action-col"><h3>{title}</h3>{items?.length ? items.map((item, index) => <article key={`${item.action}-${index}`}><div><strong>{humanize(item.action)}</strong><span className={`route route-${item.route.toLowerCase()}`}>{item.route === "auto" ? "Auto" : item.route}</span></div><p>{item.reason}</p></article>) : <p className="empty">None returned.</p>}</div>;
}

export function ActionsView({ data, busy, onApprove }: { data: Investigation; busy: boolean; onApprove: (action: string, approved: boolean) => void }) {
  const approvals: ApprovalRequest[] = data.approval_requests ?? [];
  return <>
    <Panel icon="target" title="Recommended actions" subtitle="How the recommendation moved as evidence arrived">
      <div className="action-cols"><ActionColumn items={data.next_best_actions?.initial} title="Before evidence" /><ActionColumn items={data.next_best_actions?.final} title="After evidence" /></div>
      {data.next_best_actions?.what_changed && <p className="nba-change"><b>What changed:</b> {data.next_best_actions.what_changed}</p>}
    </Panel>
    <Panel icon="shield" title="Approvals" subtitle="Protected actions and their recorded decisions">
      {!approvals.length ? <p className="empty">No action in this case needs approval.</p> : <ul className="approvals">{approvals.map((item) => <li key={item.action}>
        <div><strong>{humanize(item.action)}</strong><small>{item.reason}</small></div>
        <span className={`route route-${item.route.toLowerCase()}`}>{item.route}</span>
        {item.approval_status === "pending" ? <span className="approval-buttons"><button className="button primary" disabled={busy} onClick={() => onApprove(item.action, true)} type="button">Approve</button><button className="button ghost" disabled={busy} onClick={() => onApprove(item.action, false)} type="button">Reject</button></span> : <span className={`tag ${item.approval_status === "approved" ? "ok" : "risk"}`}>{humanize(item.approval_status)}</span>}
      </li>)}</ul>}
    </Panel>
  </>;
}

/* ---------- SAR ---------- */

function sarText(data: Investigation) {
  const sar = data.sar!;
  return [`Suspicious activity report: case ${data.case_id}`, `Decision: ${sar.file ? "Filing required" : "No filing required"}`, `Reason: ${sar.reason}`, `Subjects: ${sar.subjects.join(", ") || "None"}`, `Amount: ${money(sar.total_amount_usd) ?? "Not stated"}`, `Activity dates: ${sar.activity_dates.join(" to ") || "Not stated"}`, "", sar.narrative].join("\n");
}

export function SarView({ data }: { data: Investigation }) {
  const sar = data.sar;
  const [copied, setCopied] = useState(false);
  const pending = data.approval_requests?.some((item) => item.action === "FILE_REPORT" && item.approval_status === "pending");
  async function copy() {
    try { await navigator.clipboard.writeText(sarText(data)); setCopied(true); setTimeout(() => setCopied(false), 1800); } catch { setCopied(false); }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([sarText(data)], { type: "text/plain" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${data.case_id}-sar.txt`; anchor.click(); URL.revokeObjectURL(url);
  }
  return <Panel action={sar ? <div className="panel-actions"><button className="button ghost small" onClick={() => void copy()} type="button"><Icon name={copied ? "check" : "doc"} size={14} />{copied ? "Copied" : "Copy report"}</button><button className="button ghost small" onClick={download} type="button"><Icon name="download" size={14} />Download .txt</button></div> : undefined} icon="doc" subtitle="Generated from the investigation record" title="Suspicious activity report">
    {!sar ? <div className="missing-context"><Icon name="ledger" size={24} /><strong>No report decision yet</strong><p>The investigation workflow drafts the report after policy rules run. The local reference runtime records evidence only, so no report is produced for this case.</p></div> : <div className="sar">
      <div className="sar-status"><span className={`tag ${sar.file ? "risk" : "ok"}`}>{sar.file ? "Filing required" : "No filing required"}</span>{pending && <span className="tag warn">L2 approval pending</span>}</div>
      <p>{sar.reason}</p>
      <dl className="facts">
        <div><dt>Subjects</dt><dd>{sar.subjects.join(", ") || "—"}</dd></div>
        <div><dt>Amount</dt><dd>{money(sar.total_amount_usd) ?? "—"}</dd></div>
        <div><dt>Activity dates</dt><dd>{sar.activity_dates.map((date) => dateTime(date) ?? date).join(" to ") || "—"}</dd></div>
      </dl>
      {sar.narrative ? <article className="narrative">{sar.narrative}</article> : <p className="empty">No narrative was returned.</p>}
    </div>}
  </Panel>;
}

/* ---------- Audit ---------- */

const secret = /api[_-]?key|token|password|secret|credential|authorization/i;
export function redact(events: Record<string, unknown>[]) {
  return events.map((event) => Object.fromEntries(Object.entries(event).filter(([key]) => !secret.test(key))));
}
