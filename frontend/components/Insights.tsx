"use client";

import { dateTime, humanize, money } from "../lib/format";
import { BlastRadius as Blast, DecisionPath, Execution, Investigation } from "../lib/types";
import { Icon } from "./icons";
import { Panel } from "./Panels";

const tone = (verdict: string) => (verdict === "fraud" ? "v-fraud" : verdict === "legitimate" ? "v-legitimate" : "v-uncertain");
const clamp = (value: number) => Math.max(0, Math.min(1, value));

/** A waterfall of the weighted fraud probability: what each signal added, and which ones decided the verdict. */
export function ScoreBreakdown({ data }: { data: Investigation }) {
  const breakdown = data.score_breakdown;
  if (!breakdown?.contributions.length) return null;
  const { probability, fraud_threshold: high, legitimate_threshold: low } = breakdown;
  const verdict = data.case?.verdict ?? "uncertain";
  let running = 0;
  const rows = breakdown.contributions.map((row) => {
    const start = running;
    running += row.points;
    return { ...row, start: clamp(Math.min(start, running)), width: Math.abs(clamp(running) - clamp(start)) };
  });
  const margin = probability >= high ? probability - high : probability <= low ? low - probability : Math.min(high - probability, probability - low);
  const where = probability >= high ? `${margin.toFixed(3)} above the strong-fraud line` : probability <= low ? `${margin.toFixed(3)} below the strong-legitimate line` : `between the lines: ${(high - probability).toFixed(2)} short of strong fraud`;
  const decisive = breakdown.contributions.filter((row) => row.decisive);
  return <Panel icon="pulse" subtitle={`Fraud probability ${probability.toFixed(3)}, ${where}`} title="How the score was built">
    <div className="waterfall">
      <div aria-hidden="true" className="waterfall-lines"><i style={{ left: `${low * 100}%` }}><span>{low}</span></i><i className="high" style={{ left: `${high * 100}%` }}><span>{high}</span></i></div>
      {rows.map((row) => <div className="wf-row" key={row.signal}>
        <span className="wf-label">{row.label}{row.decisive && <b className="decisive" title={`Without it the probability would be ${row.without.toFixed(3)} and the verdict would change`}>Decisive</b>}</span>
        <span className="wf-track"><i className={row.points < 0 ? "down" : "up"} style={{ left: `${row.start * 100}%`, width: `${Math.max(0.6, row.width * 100)}%` }} /></span>
        <span className="wf-points">{row.points >= 0 ? "+" : ""}{row.points.toFixed(3)}</span>
      </div>)}
      <div className="wf-row total">
        <span className="wf-label">Fraud probability</span>
        <span className="wf-track"><i className={`final ${tone(verdict)}`} style={{ left: 0, width: `${clamp(probability) * 100}%` }} /></span>
        <span className="wf-points">{probability.toFixed(3)}</span>
      </div>
    </div>
    <p className="wf-note">{decisive.length ? <><b>What would change the verdict:</b> removing {decisive.length === 1 ? "this one signal" : "any one of these signals"}: {decisive.map((row) => `${row.label.toLowerCase()} (to ${row.without.toFixed(2)})`).join(", ")}.</> : "No single signal decides this verdict on its own: removing any one of them leaves the outcome unchanged."}</p>
  </Panel>;
}

/** Value of information: what every possible answer to every available request would lead to. */
export function DecisionPaths({ paths }: { paths: DecisionPath[] }) {
  if (!paths.length) return null;
  return <Panel className="paths" icon="target" subtitle="Every possible answer, simulated through the full assessment. The agent asks for the evidence that can change the decision most." title="Decision paths">
    <div className="path-list">{paths.map((path) => <article className={path.chosen ? "chosen" : ""} key={path.request_type}>
      <header>
        <strong>{humanize(path.request_type)}</strong>
        {path.chosen && <span className="tag ok">Asked first</span>}
        <small>{path.distinct_decisions} distinct decision{path.distinct_decisions === 1 ? "" : "s"}, {path.settling_answers} settling answer{path.settling_answers === 1 ? "" : "s"}</small>
      </header>
      <ol>{path.outcomes.map((outcome) => <li key={outcome.answer}>
        <span className="answer">If {humanize(outcome.answer).toLowerCase()}</span>
        <Icon className="arrow" name="play" size={11} />
        <span className={`outcome ${tone(outcome.verdict)}`}><i />{humanize(outcome.verdict)}<em>{outcome.probability.toFixed(2)}</em></span>
        <span className="chips">{outcome.actions.length ? outcome.actions.map((action) => <span className={`chip route-${action.route.toLowerCase()}`} key={action.action}>{humanize(action.action)}<b>{action.route === "auto" ? "Auto" : action.route}</b></span>) : <span className="muted-text">No action</span>}{outcome.sar && <span className="chip sar">SAR</span>}</span>
      </li>)}</ol>
    </article>)}</div>
  </Panel>;
}

/** The other cards the same device or fraud ring reaches right now. */
export function BlastRadiusPanel({ blast }: { blast: Blast | null | undefined }) {
  if (!blast?.cards.length) return null;
  return <Panel icon="graph" subtitle="Other cards this device or fraud ring reaches. One alert becomes protection for all of them." title="Blast radius">
    <div className="blast-stats">
      <div><strong>{blast.card_count}</strong><span>cards at risk</span></div>
      <div><strong>{blast.customers}</strong><span>other customers</span></div>
      <div><strong>{money(blast.recent_spend_usd, true)}</strong><span>recent spend on the shared device</span></div>
      <div><strong className={blast.confirmed_cases.length ? "hot" : ""}>{blast.confirmed_cases.length}</strong><span>confirmed fraud cases in the ring</span></div>
    </div>
    <RingTimeline blast={blast} />
    <div className="table-wrap"><table className="data-table">
      <thead><tr><th>Card</th><th>Customer</th><th>Linked by</th><th className="num">Transactions</th><th className="num">Spend</th><th>Last seen</th></tr></thead>
      <tbody>{blast.cards.map((row) => <tr key={row.card_id || row.customer_id}>
        <td className="ids">{row.card_id || "—"}</td><td className="ids">{row.customer_id || "—"}</td><td>{row.link}</td>
        <td className="num">{row.transactions || "—"}</td><td className="num">{row.spend_usd ? money(row.spend_usd) : "—"}</td><td>{dateTime(row.last_seen) ?? "—"}</td>
      </tr>)}</tbody>
    </table></div>
  </Panel>;
}

const systemLabel: Record<string, string> = { "card-platform": "Card platform", "customer-messaging": "Customer messaging", "case-management": "Case management",
  "regulatory-filing": "Regulatory filing", "transaction-monitoring": "Transaction monitoring", payments: "Payments", identity: "Identity" };

/** What the agent actually did, through simulated bank systems, with a receipt for each action. */
export function ActionsTaken({ executions }: { executions: Execution[] }) {
  if (!executions.length) return null;
  return <Panel icon="check" subtitle="Automatic actions run when recommended; protected actions run only after approval. All systems are simulated." title="Actions taken">
    <ol className="executions">{executions.map((item, index) => <li className={item.status} key={`${item.action}-${index}`}>
      <span className="exec-icon"><Icon name={item.status === "executed" ? "check" : "x"} size={14} /></span>
      <div>
        <div className="exec-head"><strong>{humanize(item.action)}</strong><span className={`chip route-${item.route.toLowerCase()}`}>{item.route === "auto" ? "Auto" : item.route}</span>{item.status === "rejected" && <span className="tag risk">Not executed</span>}</div>
        <p>{item.detail}</p>
        <small>{item.status === "executed" ? (item.route === "auto" ? "Ran automatically under policy" : `Approved by ${item.approved_by}`) : "Rejected by the approver"}, {systemLabel[item.system] ?? item.system}{item.receipt_id ? `, receipt ${item.receipt_id}` : ""}, {dateTime(item.executed_at)}</small>
      </div>
    </li>)}</ol>
  </Panel>;
}

/** When each card in the ring was first touched, relative to the flagged transaction. */
function RingTimeline({ blast }: { blast: Blast }) {
  const points = [
    ...blast.cards.filter((row) => row.first_seen).map((row) => ({ label: row.card_id || row.customer_id, time: Date.parse(row.first_seen!), spend: row.spend_usd, flagged: false })),
    ...(blast.target?.first_seen ? [{ label: blast.target.card_id, time: Date.parse(blast.target.first_seen), spend: blast.target.spend_usd, flagged: true }] : []),
  ].filter((point) => Number.isFinite(point.time)).sort((a, b) => a.time - b.time);
  if (points.length < 2) return null;
  const start = points[0].time; const span = Math.max(1, points[points.length - 1].time - start);
  const hours = span / 3600000;
  return <div className="ring-timeline" aria-label="Ring timeline">
    <div className="rt-head"><strong>Ring timeline</strong><small>{points.length} cards touched within {hours < 48 ? `${Math.round(hours)} hours` : `${Math.round(hours / 24)} days`}</small></div>
    <div className="rt-track">
      {points.map((point, index) => <span className={`rt-point ${point.flagged ? "flagged" : ""} ${index % 2 ? "below" : ""}`} key={point.label} style={{ left: `${((point.time - start) / span) * 100}%` }} title={`${point.label}, ${dateTime(new Date(point.time).toISOString())}`}>
        <i /><em>{point.label}</em><b>{dateTime(new Date(point.time).toISOString())}</b>
      </span>)}
    </div>
  </div>;
}
