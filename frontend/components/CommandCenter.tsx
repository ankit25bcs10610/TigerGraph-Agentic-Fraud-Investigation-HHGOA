"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { dateTime, humanize, money, relative, toNumber } from "../lib/format";
import { CaseAssessment, CaseOverview, Ring } from "../lib/types";
import { api } from "../lib/api";
import { entityColor, Icon, iconDataUri } from "./icons";
import { Connection } from "./Sidebar";

export type Activity = { id: number; text: string; detail?: string; at: number; tone: "ok" | "warn" | "risk" | "info" };

type Tab = "queue" | "network" | "timeline" | "rings";
type SortKey = "risk" | "probability" | "exposure" | "opened" | "case";
type Filters = { verdict: string; trigger: string; status: string; amount: string };
const NO_FILTERS: Filters = { verdict: "all", trigger: "all", status: "all", amount: "all" };

const verdictLabel: Record<string, string> = { fraud: "Fraud", uncertain: "Needs review", legitimate: "Legitimate", none: "Not assessed" };
const statusLabel: Record<string, string> = { not_started: "New", awaiting_evidence: "Needs evidence", awaiting_approval: "Needs approval", completed: "Completed" };
const statusOrder = ["not_started", "awaiting_evidence", "awaiting_approval", "completed"];
const amountBuckets: Record<string, [string, (value: number) => boolean]> = {
  small: ["Under $100", (value) => value < 100],
  medium: ["$100 to $1,000", (value) => value >= 100 && value <= 1000],
  large: ["Over $1,000", (value) => value > 1000],
};

const wholeDollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

const verdictOf = (item: CaseOverview) => item.assessment?.verdict ?? "none";
const statusOf = (item: CaseOverview) => item.assessment?.status ?? "not_started";

function compare(a: CaseOverview, b: CaseOverview, key: SortKey): number {
  const num = (value: unknown) => toNumber(value) ?? -Infinity;
  if (key === "risk") return num(b.risk_score) - num(a.risk_score);
  if (key === "probability") return num(b.assessment?.fraud_probability) - num(a.assessment?.fraud_probability);
  if (key === "exposure") return num(b.assessment?.exposure_usd) - num(a.assessment?.exposure_usd);
  if (key === "opened") return (Date.parse(b.opened_at ?? "") || 0) - (Date.parse(a.opened_at ?? "") || 0);
  return a.case_id.localeCompare(b.case_id, undefined, { numeric: true });
}

/* ------------------------------------------------------------------ risk strip */

function Donut({ parts, total }: { parts: { label: string; value: number; slot: number }[]; total: number }) {
  const radius = 36; const circumference = 2 * Math.PI * radius; const gap = total > 1 ? 3 : 0;
  let offset = 0;
  return <svg aria-hidden="true" className="donut" viewBox="0 0 96 96">
    <circle className="donut-track" cx="48" cy="48" r={radius} />
    {parts.filter((part) => part.value).map((part) => {
      const length = (part.value / Math.max(1, total)) * circumference;
      const segment = <circle cx="48" cy="48" key={part.label} r={radius} strokeDasharray={`${Math.max(0, length - gap)} ${circumference}`} strokeDashoffset={-offset} style={{ stroke: `var(--series-${part.slot})` }} transform="rotate(-90 48 48)"><title>{`${part.label}: ${part.value}`}</title></circle>;
      offset += length;
      return segment;
    })}
    <text className="donut-value" x="48" y="50">{total}</text>
    <text className="donut-label" x="48" y="64">cases</text>
  </svg>;
}

function Trend({ cases }: { cases: CaseOverview[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const stamps = cases.map((item) => Date.parse(item.opened_at ?? "")).filter(Number.isFinite);
  if (!stamps.length) return <p className="muted-text">No open dates supplied.</p>;
  const end = new Date(Math.max(...stamps)); end.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 7 }, (_, index) => { const day = new Date(end); day.setDate(end.getDate() - 6 + index); return day; });
  const counts = days.map((day) => stamps.filter((stamp) => { const date = new Date(stamp); date.setHours(0, 0, 0, 0); return date.getTime() === day.getTime(); }).length);
  const max = Math.max(1, ...counts);
  const W = 220; const H = 86; const pad = { l: 16, r: 10, t: 12, b: 20 };
  const x = (index: number) => pad.l + (index / 6) * (W - pad.l - pad.r);
  const y = (value: number) => pad.t + (1 - value / max) * (H - pad.t - pad.b);
  const path = counts.map((value, index) => `${index ? "L" : "M"}${x(index)} ${y(value)}`).join(" ");
  const peak = counts.indexOf(max);
  return <svg aria-label={`Cases opened per day: ${counts.join(", ")}`} className="trend" onMouseLeave={() => setHover(null)} role="img" viewBox={`0 0 ${W} ${H}`}>
    {[0, max].map((tick) => <g className="trend-grid" key={tick}><line x1={pad.l} x2={W - pad.r} y1={y(tick)} y2={y(tick)} /><text x={pad.l - 6} y={y(tick) + 3}>{tick}</text></g>)}
    <path className="trend-area" d={`${path} L${x(6)} ${y(0)} L${x(0)} ${y(0)}Z`} />
    <path className="trend-line" d={path} />
    {counts.map((value, index) => <g key={index} onMouseEnter={() => setHover(index)}>
      <rect className="hit" height={H} width={(W - pad.l - pad.r) / 6} x={x(index) - (W - pad.l - pad.r) / 12} y={0} />
      <circle className={`trend-dot ${index === peak || index === hover ? "on" : ""}`} cx={x(index)} cy={y(value)} r={index === peak || index === hover ? 4 : 2.5} />
      <text className="trend-x" x={x(index)} y={H - 5}>{days[index].getDate()}</text>
    </g>)}
    {(hover ?? peak) >= 0 && <g className="trend-tip" transform={`translate(${Math.min(W - 58, Math.max(0, x(hover ?? peak) - 29))} 0)`}><rect height="17" rx="4" width="58" /><text x="29" y="12">{counts[hover ?? peak]} case{counts[hover ?? peak] === 1 ? "" : "s"}</text></g>}
  </svg>;
}

function RiskOverview({ cases }: { cases: CaseOverview[] }) {
  const assessed = cases.filter((item) => item.assessment);
  const exposure = assessed.reduce((sum, item) => sum + (item.assessment?.exposure_usd ?? 0), 0);
  const largest = [...assessed].sort((a, b) => (b.assessment?.exposure_usd ?? 0) - (a.assessment?.exposure_usd ?? 0))[0];
  const verdicts = (["fraud", "uncertain", "legitimate", "none"] as const).map((key) => ({ key, count: cases.filter((item) => verdictOf(item) === key).length }));
  const statuses = statusOrder.map((key, index) => ({ label: statusLabel[key], value: cases.filter((item) => statusOf(item) === key).length, slot: index + 1 }));
  const approvals = cases.flatMap((item) => item.assessment?.pending_approvals ?? []);
  const l2 = approvals.filter((item) => item.route === "L2").length;
  const waiting = cases.filter((item) => item.assessment?.pending_approvals.length).length;
  return <section className="panel risk-strip" aria-labelledby="risk-title">
    <header className="panel-head">
      <span className="panel-icon"><Icon name="pulse" /></span>
      <div><h2 id="risk-title">Operational risk</h2><p>Exposure and assessed risk across the loaded queue</p></div>
      <span className="live-dot">Computed by the investigation engine</span>
    </header>
    <div className="risk-grid">
      <div className="risk-cell">
        <span className="cell-label">Total potential exposure</span>
        <strong className="hero-number">{assessed.length ? wholeDollars.format(exposure) : "Not assessed"}</strong>
        <small>{assessed.length ? `${assessed.length} of ${cases.length} cases assessed${largest ? `; largest ${largest.case_id}` : ""}` : "Load transactions to assess exposure"}</small>
      </div>
      <div className="risk-cell">
        <span className="cell-label">Verdict mix ({cases.length} cases)</span>
        <div className="stack" role="img" aria-label={verdicts.map((item) => `${verdictLabel[item.key]} ${item.count}`).join(", ")}>
          {verdicts.filter((item) => item.count).map((item) => <i className={`v-${item.key}`} key={item.key} style={{ flexGrow: item.count }} title={`${verdictLabel[item.key]}: ${item.count}`} />)}
        </div>
        <ul className="legend">{verdicts.filter((item) => item.count).map((item) => <li key={item.key}><i className={`v-${item.key}`} /><b>{item.count}</b> {verdictLabel[item.key]}</li>)}</ul>
      </div>
      <div className="risk-cell donut-cell">
        <span className="cell-label">Queue health</span>
        <div className="donut-wrap"><Donut parts={statuses} total={cases.length} /><ul className="legend vertical">{statuses.map((item) => <li key={item.label}><i style={{ background: `var(--series-${item.slot})` }} /><b>{item.value}</b> {item.label}</li>)}</ul></div>
      </div>
      <div className="risk-cell">
        <span className="cell-label">Decisions waiting</span>
        <strong className={`hero-number ${approvals.length ? "hot" : ""}`}>{approvals.length}</strong>
        <small>{approvals.length ? `across ${waiting} case${waiting === 1 ? "" : "s"}` : "No approvals pending"}</small>
        {l2 > 0 && <small className="danger-text">{l2} need L2 sign-off</small>}
      </div>
      <div className="risk-cell trend-cell">
        <span className="cell-label">Cases opened, last 7 days</span>
        <Trend cases={cases} />
      </div>
    </div>
  </section>;
}

/* --------------------------------------------------------------- priority brief */

function PriorityBrief({ cases, onReview }: { cases: CaseOverview[]; onReview: (verdict: string) => void }) {
  const fraud = cases.filter((item) => item.assessment?.verdict === "fraud" && (item.assessment.pending_approvals.length || item.assessment.sar_required || item.assessment.status === "not_started"));
  const review = cases.filter((item) => item.assessment?.verdict === "uncertain");
  const l2 = fraud.filter((item) => item.assessment?.pending_approvals.some((approval) => approval.route === "L2")).length;
  const top = [...fraud, ...review].sort((a, b) => (b.assessment?.exposure_usd ?? 0) - (a.assessment?.exposure_usd ?? 0))[0];
  const assessedAny = cases.some((item) => item.assessment);
  return <section className="panel brief" aria-labelledby="brief-title">
    <svg aria-hidden="true" className="brief-contours" viewBox="0 0 300 200">{Array.from({ length: 9 }, (_, index) => <path d={`M${40 + index * 22} 210 C ${90 + index * 18} ${120 - index * 6}, ${170 + index * 10} ${150 - index * 14}, ${310} ${40 + index * 12}`} key={index} />)}</svg>
    <header className="brief-head"><Icon name="target" size={22} /><h2 id="brief-title">Priority brief</h2></header>
    {!assessedAny ? <>
      <h3 className="brief-title">Assessments appear once transactions are loaded</h3>
      <p>Start the API with <code>TRANSACTIONS_PATH</code> to let the engine score every case in the queue.</p>
    </> : fraud.length ? <>
      <h3 className="brief-title"><em>{fraud.length} fraud case{fraud.length === 1 ? "" : "s"}</em> need a decision</h3>
      <p>{l2 ? `${l2} need${l2 === 1 ? "s" : ""} L2 sign-off. ` : ""}{top?.assessment ? `Largest exposure: ${top.case_id} at ${money(top.assessment.exposure_usd)}.` : ""}{review.length ? ` ${review.length} more case${review.length === 1 ? "" : "s"} need review.` : ""}</p>
      <button className="button danger" onClick={() => onReview("fraud")} type="button">Review fraud cases<Icon name="play" size={13} /></button>
    </> : review.length ? <>
      <h3 className="brief-title"><em className="warn">{review.length} case{review.length === 1 ? "" : "s"}</em> need review</h3>
      <p>The evidence is not yet conclusive. Customer or step-up answers will settle them.</p>
      <button className="button primary" onClick={() => onReview("uncertain")} type="button">Review uncertain cases<Icon name="play" size={13} /></button>
    </> : <>
      <h3 className="brief-title">Nothing needs a decision</h3>
      <p>Every assessed case is settled.</p>
    </>}
  </section>;
}

/* -------------------------------------------------------------------- queue rows */

function Glyph({ item }: { item: CaseOverview }) {
  const entities = item.assessment?.entities;
  const spokes = entities ? Math.max(3, Math.min(8, entities.customers.length + entities.devices.length + entities.closed_cases.length + entities.cards.length)) : 3;
  const shared = Boolean(entities?.shared_devices.length);
  return <svg aria-hidden="true" className={`glyph v-${verdictOf(item)}`} viewBox="0 0 48 48">
    {Array.from({ length: spokes }, (_, index) => {
      const angle = (index / spokes) * Math.PI * 2 - Math.PI / 2; const reach = index % 2 ? 15 : 19;
      const x = 24 + Math.cos(angle) * reach; const y = 24 + Math.sin(angle) * reach;
      return <g key={index}><line x1="24" x2={x} y1="24" y2={y} /><circle className={shared && index === 0 ? "hot" : ""} cx={x} cy={y} r={index % 3 ? 2.6 : 3.4} /></g>;
    })}
    <circle className="core" cx="24" cy="24" r="5" />
  </svg>;
}

function RiskRing({ value, tone }: { value: number | null; tone: string }) {
  if (value === null) return <span className="ring-empty">—<small>Unscored</small></span>;
  const radius = 17; const circumference = 2 * Math.PI * radius;
  return <svg aria-label={`Risk score ${value.toFixed(2)}`} className={`ring v-${tone}`} role="img" viewBox="0 0 44 44">
    <circle className="ring-track" cx="22" cy="22" r={radius} />
    <circle className="ring-value" cx="22" cy="22" r={radius} strokeDasharray={`${Math.min(1, Math.max(0, value)) * circumference} ${circumference}`} transform="rotate(-90 22 22)" />
    <text x="22" y="26">{value.toFixed(2)}</text>
  </svg>;
}

function QueueTable({ rows, selected, visited, busy, onOpen }: { rows: CaseOverview[]; selected: string; visited: Set<string>; busy: boolean; onOpen: (id: string) => void }) {
  if (!rows.length) return <p className="empty">No cases match these filters.</p>;
  return <div className="table-wrap"><table className="cc-table">
    <thead><tr><th>Case</th><th><span className="sr-only">Network</span></th><th>Trigger</th><th>Customer</th><th>Finding</th><th className="num">Amount</th><th>Opened</th><th>Risk</th><th>Status</th><th><span className="sr-only">Action</span></th></tr></thead>
    <tbody>{rows.map((item) => {
      const verdict = verdictOf(item); const assessment = item.assessment; const status = statusOf(item);
      return <tr aria-selected={item.case_id === selected} className={`v-row v-${verdict}`} key={item.case_id} onClick={() => !busy && onOpen(item.case_id)}>
        <td><strong className="cc-id">{item.case_id}</strong>{verdict === "fraud" && <i className="pulse-dot" aria-hidden="true" />}{visited.has(item.case_id) && <i aria-label="Opened this session" className="seen-dot" role="img" title="Opened this session" />}<small className={`v-text v-${verdict}`}>{verdictLabel[verdict]}</small></td>
        <td><Glyph item={item} /></td>
        <td><strong>{item.trigger_type ? humanize(item.trigger_type) : "Unspecified"}</strong><small className="sub">{assessment && assessment.pattern !== "none" ? humanize(assessment.pattern) : assessment ? "No documented pattern" : "Awaiting assessment"}</small></td>
        <td className="nowrap"><strong className="mono">{item.customer_id || "—"}</strong><small className="sub mono">{item.card_id}</small></td>
        <td className="finding"><p>{assessment?.finding ?? item.trigger_text ?? "—"}</p></td>
        <td className="num nowrap"><strong>{money(assessment?.flagged_amount) ?? "—"}</strong><small className="sub">{assessment?.channel ? humanize(assessment.channel) : ""}</small></td>
        <td className="nowrap" title={dateTime(item.opened_at) ?? undefined}><strong>{relative(item.opened_at) ?? "—"}</strong><small className="sub">{item.opened_at ? new Date(item.opened_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}</small></td>
        <td><RiskRing tone={verdict} value={toNumber(item.risk_score)} /></td>
        <td><span className={`status-pill s-${status}`}>{statusLabel[status] ?? humanize(status)}</span>{assessment?.pending_approvals.length ? <small className="sub">{status === "not_started" ? "Will need " : "Needs "}{[...new Set(assessment.pending_approvals.map((approval) => approval.route))].join(" + ")}</small> : null}</td>
        <td><button className="button ink small" disabled={busy} onClick={(event) => { event.stopPropagation(); onOpen(item.case_id); }} type="button">{busy && item.case_id === selected ? "Opening…" : "Open case"}<Icon name="play" size={12} /></button></td>
      </tr>;
    })}</tbody>
  </table></div>;
}

/* -------------------------------------------------------------- relationship view */

function cssVar(name: string) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function RelationshipView({ rows, theme, onOpen }: { rows: CaseOverview[]; theme: string; onOpen: (id: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const elements = useMemo(() => {
    const nodes = new Map<string, ElementDefinition>(); const edges: ElementDefinition[] = [];
    rows.forEach((item) => {
      nodes.set(`case:${item.case_id}`, { data: { id: `case:${item.case_id}`, label: item.case_id, kind: "case", verdict: verdictOf(item) } });
      const entities = item.assessment?.entities;
      const linked: [string, string[]][] = entities ? [["Customer", entities.customers], ["DeviceProfile", entities.devices], ["ClosedCase", entities.closed_cases]] : [["Customer", item.customer_id ? [item.customer_id] : []]];
      linked.forEach(([type, ids]) => ids.forEach((id) => {
        const nodeId = `${type}:${id}`;
        nodes.set(nodeId, { data: { id: nodeId, label: id, kind: "entity", entity_type: type, shared: entities?.shared_devices.includes(id) } });
        edges.push({ data: { id: `${item.case_id}->${nodeId}`, source: `case:${item.case_id}`, target: nodeId } });
      }));
    });
    return [...nodes.values(), ...edges];
  }, [rows]);
  useEffect(() => {
    if (!ref.current) return;
    const text = cssVar("--text"); const line = cssVar("--line-strong"); const surface = cssVar("--surface");
    const tones: Record<string, string> = { fraud: cssVar("--risk"), uncertain: cssVar("--warn"), legitimate: cssVar("--ok"), none: cssVar("--faint") };
    const cy: Core = cytoscape({
      container: ref.current, elements, wheelSensitivity: 0.2,
      style: [
        { selector: "node", style: { label: "data(label)", color: text, "font-size": 10, "font-family": "IBM Plex Sans, system-ui, sans-serif", "text-valign": "bottom", "text-margin-y": 6, width: 22, height: 22, "background-color": surface, "border-width": 2 } },
        ...Object.entries(tones).map(([verdict, color]) => ({ selector: `node[kind = "case"][verdict = "${verdict}"]`, style: { width: 40, height: 40, "background-color": color, "border-color": surface, "border-width": 3, "font-size": 12, "font-weight": 600, "underlay-color": color, "underlay-opacity": 0.18, "underlay-padding": 8 } })),
        ...Object.keys(entityColor).map((type) => ({ selector: `node[entity_type = "${type}"]`, style: { "border-color": entityColor[type], "background-image": iconDataUri(type, entityColor[type]), "background-width": "58%", "background-height": "58%" } })),
        { selector: "node[?shared]", style: { "border-color": tones.fraud, "border-width": 3 } },
        { selector: "edge", style: { width: 1.3, "line-color": line, "curve-style": "bezier" } },
      ],
      layout: { name: "cose", padding: 24, animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 60 } as cytoscape.LayoutOptions,
    });
    cy.on("tap", 'node[kind = "case"]', (event) => onOpen(String(event.target.data("label"))));
    return () => cy.destroy();
  }, [elements, theme, onOpen]);
  return <div className="network-view"><div className="network-canvas" ref={ref} aria-label="Cases and the entities they share" /><p className="network-note"><Icon name="target" size={14} />Large nodes are cases, coloured by verdict; select one to open it. Entities shared by several cases join their clusters.</p></div>;
}

/* ------------------------------------------------------------------- timeline view */

function TimelineView({ rows, onOpen }: { rows: CaseOverview[]; onOpen: (id: string) => void }) {
  const days = useMemo(() => {
    const groups = new Map<string, CaseOverview[]>();
    [...rows].sort((a, b) => (Date.parse(b.opened_at ?? "") || 0) - (Date.parse(a.opened_at ?? "") || 0)).forEach((item) => {
      const date = new Date(item.opened_at ?? "");
      const key = Number.isNaN(date.getTime()) ? "Undated" : date.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" });
      groups.set(key, [...(groups.get(key) ?? []), item]);
    });
    return [...groups.entries()];
  }, [rows]);
  if (!rows.length) return <p className="empty">No cases match these filters.</p>;
  return <ol className="day-list">{days.map(([day, items]) => <li key={day}>
    <h3><span>{day}</span><b>{items.length} case{items.length === 1 ? "" : "s"}</b></h3>
    <ul>{items.map((item) => <li key={item.case_id}><button className={`day-card v-${verdictOf(item)}`} onClick={() => onOpen(item.case_id)} type="button">
      <span className="day-time">{new Date(item.opened_at ?? "").toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>
      <span className="day-body"><strong>{item.case_id}<em className={`v-text v-${verdictOf(item)}`}>{verdictLabel[verdictOf(item)]}</em></strong><small>{item.assessment?.finding ?? item.trigger_text}</small></span>
      <span className="day-amount">{money(item.assessment?.exposure_usd) ?? ""}</span>
    </button></li>)}</ul>
  </li>)}</ol>;
}

/* --------------------------------------------------------------------- rings tab */

function RingsView({ onOpen }: { onOpen: (id: string) => void }) {
  const [rings, setRings] = useState<Ring[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.rings().then(setRings).catch((caught) => setError(caught instanceof Error ? caught.message : "Rings could not be loaded.")); }, []);
  if (error) return <p className="empty">{error}</p>;
  if (!rings) return <p className="empty">Running community detection across the graph…</p>;
  if (!rings.length) return <p className="empty">No card-device community spans three or more customers.</p>;
  const candidates = rings.filter((ring) => ring.label === "candidate_undocumented").length;
  return <div className="rings">
    <p className="rings-intro"><Icon name="graph" size={15} />Weakly connected components over cards and devices, across the whole graph. <b>{candidates} of {rings.length}</b> match no documented pattern: candidates for the undocumented fraud the brief warns about.</p>
    <div className="ring-grid">{rings.map((ring, index) => <article className={ring.label} key={ring.community_id}>
      <header><strong>Ring {index + 1}</strong><span className={`tag ${ring.label === "candidate_undocumented" ? "warn" : "risk"}`}>{ring.label === "candidate_undocumented" ? "Undocumented pattern" : "Known pattern"}</span></header>
      <dl>
        <div><dt>Customers</dt><dd>{ring.customers}</dd></div><div><dt>Cards</dt><dd>{ring.cards}</dd></div><div><dt>Devices</dt><dd>{ring.devices}</dd></div>
        <div><dt>Total</dt><dd>{ring.total_amount_usd !== null ? money(ring.total_amount_usd, true) : "—"}</dd></div>
      </dl>
      <p className="ring-facts">{[ring.online_share !== null ? `${Math.round(ring.online_share * 100)}% online` : "", ring.span_hours !== null ? `over ${ring.span_hours < 48 ? `${Math.round(ring.span_hours)} h` : `${Math.round(ring.span_hours / 24)} days`}` : "",
        ring.confirmed_cases.length ? `${ring.confirmed_cases.length} confirmed fraud case${ring.confirmed_cases.length === 1 ? "" : "s"} (${Object.keys(ring.confirmed_patterns).map((name) => humanize(name).toLowerCase()).join(", ")})` : "no closed case touches it"].filter(Boolean).join(", ")}.</p>
      <p className="ring-ids mono">{ring.sample_devices.join(", ")}</p>
      {ring.benchmark_cases.length > 0 && <div className="ring-cases">{ring.benchmark_cases.map((id) => <button className="button ghost small" key={id} onClick={() => onOpen(id)} type="button">Open {id}</button>)}</div>}
    </article>)}</div>
  </div>;
}

/* -------------------------------------------------------------- live intelligence */

function IntelGraph({ cases }: { cases: CaseOverview[] }) {
  const entities = cases.flatMap((item) => item.assessment ? [
    ...item.assessment.entities.customers.map((id) => ({ id, type: "Customer" })),
    ...item.assessment.entities.devices.map((id) => ({ id, type: "DeviceProfile", shared: item.assessment!.entities.shared_devices.includes(id) })),
    ...item.assessment.entities.closed_cases.map((id) => ({ id, type: "ClosedCase" })),
  ] : []);
  const unique = [...new Map(entities.map((item) => [item.id, item])).values()].slice(0, 16);
  if (!unique.length) return null;
  return <svg aria-hidden="true" className="intel-graph" viewBox="0 0 200 150">
    {unique.map((item, index) => {
      const ring = index % 2 ? 44 : 64; const angle = (index / unique.length) * Math.PI * 2;
      const x = 100 + Math.cos(angle) * ring * 1.25; const y = 75 + Math.sin(angle) * ring * 0.95;
      const hub = index % 3 === 0 ? [100, 75] : [100 + Math.cos(angle - 0.4) * 30, 75 + Math.sin(angle - 0.4) * 24];
      return <g key={item.id}><line x1={hub[0]} x2={x} y1={hub[1]} y2={y} /><circle cx={x} cy={y} r={"shared" in item && item.shared ? 7 : 4.5} style={{ fill: "shared" in item && item.shared ? "var(--risk)" : entityColor[item.type] }}><title>{item.id}</title></circle></g>;
    })}
    <circle className="intel-core" cx="100" cy="75" r="11" />
  </svg>;
}

function LiveIntelligence({ cases, activity }: { cases: CaseOverview[]; activity: Activity[] }) {
  const union = (field: keyof CaseAssessment["entities"]) => new Set(cases.flatMap((item) => item.assessment?.entities[field] ?? [])).size;
  const counts = [["Related customers", union("customers")], ["Linked transactions", union("transactions")], ["Devices", union("devices")], ["Linked closed cases", union("closed_cases")]] as const;
  const shared = cases.filter((item) => item.assessment?.entities.shared_devices.length);
  const patterns = new Map<string, string[]>();
  cases.forEach((item) => { const pattern = item.assessment?.pattern; if (pattern && pattern !== "none") patterns.set(pattern, [...(patterns.get(pattern) ?? []), item.case_id]); });
  const [topPattern, topCases] = [...patterns.entries()].sort((a, b) => b[1].length - a[1].length)[0] ?? [];
  const assessed = cases.filter((item) => item.assessment).length;
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(timer); }, []);
  return <section className="panel intel" aria-labelledby="intel-title">
    <header className="panel-head"><span className="panel-icon"><Icon name="radar" /></span><div><h2 id="intel-title">Live intelligence</h2><p>Network signals across every case in the queue</p></div><span className="live-dot">Live</span></header>
    {!assessed ? <p className="empty">Network signals appear once the engine has assessed cases.</p> : <>
      <div className="intel-body"><IntelGraph cases={cases} /><dl className="intel-counts">{counts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></div>
      <div className="emerging">
        <Icon name="target" size={18} />
        <div>
          {shared.length ? <><strong>Shared device cluster</strong><p>{shared.map((item) => `${item.assessment!.entities.shared_devices.join(", ")} links ${item.assessment!.entities.customers.length} customers in ${item.case_id}`).join("; ")}. Likely coordinated activity.</p></>
            : topPattern ? <><strong>{humanize(topPattern)}</strong><p>Seen in {topCases!.length} of {assessed} assessed cases ({topCases!.join(", ")}).</p></>
            : <><strong>No cross-case pattern</strong><p>The assessed cases don&apos;t share a documented pattern.</p></>}
        </div>
      </div>
    </>}
    <div className="activity-head"><h3>Session activity</h3><small>{activity.length ? `${activity.length} event${activity.length === 1 ? "" : "s"}` : ""}</small></div>
    {!activity.length ? <p className="muted-text">Open a case, record evidence or approve an action to build the trail.</p> : <ol className="activity-list">{activity.slice(0, 5).map((item) => <li key={item.id}><i className={`tone-${item.tone}`} /><div><strong>{item.text}</strong>{item.detail && <small>{item.detail}</small>}</div><time>{relative(new Date(Math.min(item.at, now)).toISOString())}</time></li>)}</ol>}
  </section>;
}

/* ------------------------------------------------------------------------ filters */

function FilterPanel({ filters, setFilters, cases }: { filters: Filters; setFilters: (filters: Filters) => void; cases: CaseOverview[] }) {
  const triggers = [...new Set(cases.map((item) => item.trigger_type || "unspecified"))];
  const statuses = statusOrder.filter((key) => cases.some((item) => statusOf(item) === key));
  const select = (key: keyof Filters, label: string, options: [string, string][]) => <label>{label}<select onChange={(event) => setFilters({ ...filters, [key]: event.target.value })} value={filters[key]}>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>;
  const active = Object.values(filters).some((value) => value !== "all");
  return <section className="panel filters" aria-labelledby="filter-title">
    <header className="filters-head"><Icon name="queue" size={18} /><h2 id="filter-title">Filters</h2>{active && <button className="link-button" onClick={() => setFilters(NO_FILTERS)} type="button">Reset all</button>}</header>
    <div className="filter-grid">
      {select("verdict", "Verdict", [["all", "All verdicts"], ...(["fraud", "uncertain", "legitimate", "none"] as const).filter((key) => cases.some((item) => verdictOf(item) === key)).map((key): [string, string] => [key, verdictLabel[key]])])}
      {select("trigger", "Trigger", [["all", "All triggers"], ...triggers.map((key): [string, string] => [key, humanize(key)])])}
      {select("status", "Status", [["all", "All statuses"], ...statuses.map((key): [string, string] => [key, statusLabel[key]])])}
      {select("amount", "Flagged amount", [["all", "Any amount"], ...Object.entries(amountBuckets).map(([key, [text]]): [string, string] => [key, text])])}
    </div>
  </section>;
}

/* ------------------------------------------------------------------ command center */

export function CommandCenter({ cases, query, selected, visited, busy, connection, activity, theme, onOpen, onLoadPack, onRetry }: { cases: CaseOverview[]; query: string; selected: string; visited: Set<string>; busy: boolean; connection: Connection; activity: Activity[]; theme: string; onOpen: (id: string) => void; onLoadPack: () => void; onRetry: () => void }) {
  const [tab, setTab] = useState<Tab>("queue");
  const [sort, setSort] = useState<SortKey>("risk");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const queueRef = useRef<HTMLElement>(null);
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return cases.filter((item) => {
      if (needle && ![item.case_id, item.customer_id, item.card_id, item.flagged_txn_id, item.trigger_text, item.assessment?.finding, item.assessment?.pattern].join(" ").toLowerCase().includes(needle)) return false;
      if (filters.verdict !== "all" && verdictOf(item) !== filters.verdict) return false;
      if (filters.trigger !== "all" && (item.trigger_type || "unspecified") !== filters.trigger) return false;
      if (filters.status !== "all" && statusOf(item) !== filters.status) return false;
      if (filters.amount !== "all") { const amount = item.assessment?.flagged_amount; if (amount === undefined || !amountBuckets[filters.amount][1](amount)) return false; }
      return true;
    }).sort((a, b) => compare(a, b, sort));
  }, [cases, query, filters, sort]);

  if (connection !== "online") {
    const copy = connection === "checking" ? { title: "Connecting to the investigation API", body: "Checking that the API is running and has cases loaded." }
      : connection === "setup" ? { title: "Load a case pack to begin", body: "The API is running but has no cases yet. Choose your case_pack.csv, or start the API with CASE_PACK_PATH set." }
      : { title: "The investigation API isn't reachable", body: "Start the FastAPI service and check NEXT_PUBLIC_API_BASE_URL, then retry." };
    return <section className="panel onboarding">
      <span className="onboarding-mark"><Icon className={connection === "checking" ? "spin" : undefined} name={connection === "setup" ? "upload" : connection === "checking" ? "refresh" : "radar"} size={28} /></span>
      <h1>{copy.title}</h1><p>{copy.body}</p>
      {connection === "setup" && <button className="button primary" disabled={busy} onClick={onLoadPack} type="button"><Icon name="upload" size={16} />{busy ? "Loading…" : "Choose case_pack.csv"}</button>}
      {connection === "offline" && <button className="button primary" onClick={onRetry} type="button"><Icon name="refresh" size={16} />Retry connection</button>}
    </section>;
  }

  return <div className="command">
    <div className="command-top"><RiskOverview cases={cases} /><PriorityBrief cases={cases} onReview={(verdict) => { setFilters({ ...NO_FILTERS, verdict }); setTab("queue"); queueRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }} /></div>
    <div className="command-main">
      <section className="panel queue-panel" ref={queueRef}>
        <header className="queue-bar">
          <div className="tabs-row" role="tablist">
            {([["queue", "Queue", "queue"], ["network", "Relationship view", "graph"], ["rings", "Fraud rings", "radar"], ["timeline", "Timeline", "pulse"]] as const).map(([key, label, icon]) => <button aria-selected={tab === key} className="tab" key={key} onClick={() => setTab(key)} role="tab" type="button"><Icon name={icon} size={15} />{label}{key === "queue" && <b>{rows.length}</b>}</button>)}
          </div>
          {tab === "queue" && <label className="sort-by">Sort by<select onChange={(event) => setSort(event.target.value as SortKey)} value={sort}><option value="risk">Risk score, high to low</option><option value="probability">Fraud probability</option><option value="exposure">Exposure</option><option value="opened">Newest first</option><option value="case">Case ID</option></select></label>}
        </header>
        {tab === "queue" && <QueueTable busy={busy} onOpen={onOpen} rows={rows} selected={selected} visited={visited} />}
        {tab === "network" && <RelationshipView onOpen={onOpen} rows={rows} theme={theme} />}
        {tab === "timeline" && <TimelineView onOpen={onOpen} rows={rows} />}
        {tab === "rings" && <RingsView onOpen={onOpen} />}
      </section>
      <aside className="command-side"><LiveIntelligence activity={activity} cases={cases} /><FilterPanel cases={cases} filters={filters} setFilters={setFilters} /></aside>
    </div>
  </div>;
}
