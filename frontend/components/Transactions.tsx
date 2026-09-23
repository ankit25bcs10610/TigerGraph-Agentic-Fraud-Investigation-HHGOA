"use client";

import { useMemo, useState } from "react";
import { dateTime, money, rowAmount, rowTime, toNumber } from "../lib/format";
import { Investigation, TimelineRow } from "../lib/types";
import { Icon } from "./icons";
import { Panel, TransactionsTable } from "./Panels";

const W = 1200;
const H = 250;
const PAD = { top: 16, right: 46, bottom: 28, left: 64 };

/** Amount bars with the risk score drawn over them on a second axis. */
function ActivityChart({ rows }: { rows: TimelineRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const amounts = rows.map((row) => rowAmount(row) ?? 0);
  const risks = rows.map((row) => toNumber(row.risk_score));
  const maxAmount = Math.max(1, ...amounts);
  const riskValues = risks.filter((value): value is number => value !== null);
  const maxRisk = Math.max(1, ...riskValues);
  const innerW = W - PAD.left - PAD.right; const innerH = H - PAD.top - PAD.bottom;
  const step = innerW / rows.length; const bar = Math.max(3, Math.min(34, step * 0.62));
  const x = (index: number) => PAD.left + step * index + step / 2;
  const yAmount = (value: number) => PAD.top + innerH - (value / maxAmount) * innerH;
  const yRisk = (value: number) => PAD.top + innerH - (value / maxRisk) * innerH;
  const riskPath = risks.map((value, index) => value === null ? "" : `${x(index)} ${yRisk(value)}`).filter(Boolean).map((point, index) => `${index ? "L" : "M"}${point}`).join(" ");
  const ticks = [0, 0.5, 1].map((share) => share * maxAmount);
  const active = hover !== null ? rows[hover] : null;

  return <div className="activity">
    <div className="activity-legend"><span><i className="swatch amount" />Amount</span>{riskValues.length > 0 && <span><i className="swatch risk" />Risk score</span>}{rows.some((row) => row.in_episode && !row.suspicious) && <span><i className="swatch episode" />Same fraud episode</span>}<span><i className="swatch flagged" />Flagged transaction</span></div>
    <div className="activity-frame">
      <svg aria-label={`Amounts and risk scores for ${rows.length} transactions`} onMouseLeave={() => setHover(null)} role="img" viewBox={`0 0 ${W} ${H}`}>
        {ticks.map((tick) => <g className="grid-line" key={tick}><line x1={PAD.left} x2={W - PAD.right} y1={yAmount(tick)} y2={yAmount(tick)} /><text x={PAD.left - 10} y={yAmount(tick) + 4}>{money(tick, true)}</text></g>)}
        {riskValues.length > 0 && [0, maxRisk].map((tick) => <text className="risk-axis" key={tick} x={W - PAD.right + 10} y={yRisk(tick) + 4}>{tick.toFixed(2)}</text>)}
        {rows.map((row, index) => <g key={row.transaction_id ?? index} onMouseEnter={() => setHover(index)}>
          <rect className="hit" height={innerH} width={step} x={PAD.left + step * index} y={PAD.top} />
          <rect className={`amount-bar ${row.suspicious ? "flagged" : row.in_episode ? "episode" : ""} ${hover === index ? "hover" : ""}`} height={Math.max(1, PAD.top + innerH - yAmount(amounts[index]))} rx="2" width={bar} x={x(index) - bar / 2} y={yAmount(amounts[index])} />
        </g>)}
        {riskPath && <path className="risk-line" d={riskPath} />}
        {risks.map((value, index) => value !== null && <circle className={`risk-dot ${rows[index].suspicious ? "flagged" : ""}`} cx={x(index)} cy={yRisk(value)} key={index} r={rows[index].suspicious ? 5 : 3} />)}
        {rows.length <= 16 && rows.map((row, index) => <text className="x-label" key={index} x={x(index)} y={H - 8}>{(rowTime(row) ?? "").slice(5, 10)}</text>)}
      </svg>
      {active && hover !== null && <div className="activity-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
        <strong>{active.transaction_id}</strong>
        <span>{dateTime(rowTime(active))}</span>
        <span>{money(rowAmount(active)) ?? "No amount"}{toNumber(active.risk_score) !== null && `, risk ${toNumber(active.risk_score)!.toFixed(2)}`}</span>
        {active.suspicious ? <em>Flagged transaction</em> : active.in_episode && <em className="episode">Part of the fraud episode</em>}
      </div>}
    </div>
  </div>;
}

export function TransactionsView({ data }: { data: Investigation }) {
  const rows = data.timeline ?? [];
  const stats = useMemo(() => {
    const amounts = rows.map(rowAmount).filter((value): value is number => value !== null);
    const times = rows.map((row) => Date.parse(rowTime(row) ?? "")).filter(Number.isFinite);
    const channels = new Set(rows.map((row) => row.channel).filter(Boolean));
    const flagged = rows.find((row) => row.suspicious);
    const flaggedAmount = flagged ? rowAmount(flagged) : null;
    const others = rows.filter((row) => !row.suspicious).map(rowAmount).filter((value): value is number => value !== null);
    const typical = others.length ? others.reduce((sum, value) => sum + value, 0) / others.length : null;
    return {
      total: amounts.reduce((sum, value) => sum + value, 0), largest: amounts.length ? Math.max(...amounts) : null,
      span: times.length > 1 ? Math.max(...times) - Math.min(...times) : null, channels: [...channels],
      flaggedAmount, multiple: flaggedAmount !== null && typical ? flaggedAmount / typical : null,
    };
  }, [rows]);

  if (!rows.length) return <Panel icon="swap" subtitle="Customer history around the flagged transaction" title="Transactions">
    <div className="missing-context">
      <Icon name="swap" size={24} />
      <strong>No transaction history for this case</strong>
      <p>The API didn't find {data.flagged_txn_id ? <>transaction <code>{data.flagged_txn_id}</code></> : "the flagged transaction"} in a transactions file. Start the API with <code>TRANSACTIONS_PATH</code> pointing at your <code>transactions.csv</code> to see the customer&apos;s history, the amount trend and the relationship map in full.</p>
      {data.trigger_text && <blockquote>{data.trigger_text}</blockquote>}
    </div>
  </Panel>;

  const days = stats.span !== null ? stats.span / 86400000 : null;
  return <>
    <section className="figures compact" aria-label="Transaction summary">
      <article className="figure"><span className="figure-label">Transactions</span><div className="figure-row"><strong>{rows.length}</strong></div><small>{stats.channels.length ? `Channels: ${stats.channels.join(", ")}` : "No channel recorded"}</small></article>
      <article className="figure"><span className="figure-label">Total value</span><div className="figure-row"><strong>{money(stats.total, true)}</strong></div><small>Largest {money(stats.largest) ?? "—"}</small></article>
      <article className="figure"><span className="figure-label">Flagged amount</span><div className="figure-row"><strong>{money(stats.flaggedAmount) ?? "—"}</strong></div><small>{stats.multiple ? `${stats.multiple.toFixed(1)}× the customer's other transactions on average` : "No other transactions to compare with"}</small></article>
      <article className="figure"><span className="figure-label">Time span</span><div className="figure-row"><strong>{days === null ? "—" : days < 1 ? `${Math.max(1, Math.round(days * 24))} h` : `${Math.round(days)} d`}</strong></div><small>First to last transaction</small></article>
    </section>
    <Panel icon="pulse" subtitle="Hover a bar to see the transaction" title="Amount and risk over time"><ActivityChart rows={rows} /></Panel>
    <Panel icon="swap" subtitle="Customer history around the flagged transaction, oldest first" title="Transactions"><TransactionsTable rows={rows} /></Panel>
  </>;
}
