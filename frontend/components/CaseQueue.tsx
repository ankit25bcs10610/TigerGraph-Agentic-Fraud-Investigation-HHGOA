"use client";

import { useMemo, useState } from "react";
import { dateTime, humanize, relative, toNumber } from "../lib/format";
import { CaseOption } from "../lib/types";
import { Icon } from "./icons";
import { Connection } from "./Sidebar";

type SortKey = "case_id" | "opened_at" | "risk_score";
type Sort = { key: SortKey; direction: 1 | -1 };

function compare(a: CaseOption, b: CaseOption, key: SortKey): number {
  if (key === "risk_score") return (toNumber(a.risk_score) ?? -Infinity) - (toNumber(b.risk_score) ?? -Infinity);
  if (key === "opened_at") return (Date.parse(a.opened_at ?? "") || 0) - (Date.parse(b.opened_at ?? "") || 0);
  return a.case_id.localeCompare(b.case_id, undefined, { numeric: true });
}

function dayRange(from: number, to: number) {
  const format = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
  return from === to ? format.format(from) : format.formatRange(from, to);
}

/** Ten equal buckets across the observed risk range, so the histogram follows the data rather than fixed thresholds. */
function histogram(values: number[]) {
  if (!values.length) return [];
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1;
  const buckets = Array.from({ length: 10 }, (_, index) => ({ from: min + (span * index) / 10, count: 0 }));
  values.forEach((value) => { buckets[Math.min(9, Math.floor(((value - min) / span) * 10))].count += 1; });
  return buckets;
}

export function CaseQueue({ cases, total, selected, visited, busy, connection, query, onRun, onLoadPack, onRetry }: { cases: CaseOption[]; total: number; selected: string; visited: Set<string>; busy: boolean; connection: Connection; query: string; onRun: (id: string) => void; onLoadPack: () => void; onRetry: () => void }) {
  const [trigger, setTrigger] = useState("all");
  const [sort, setSort] = useState<Sort>({ key: "case_id", direction: 1 });

  const triggers = useMemo(() => {
    const counts = new Map<string, number>();
    cases.forEach((item) => { const key = item.trigger_type || "unspecified"; counts.set(key, (counts.get(key) ?? 0) + 1); });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [cases]);
  const risks = useMemo(() => cases.map((item) => toNumber(item.risk_score)).filter((value): value is number => value !== null), [cases]);
  const buckets = useMemo(() => histogram(risks), [risks]);
  const opened = useMemo(() => cases.map((item) => Date.parse(item.opened_at ?? "")).filter(Number.isFinite), [cases]);
  const rows = useMemo(() => {
    const matching = trigger === "all" ? cases : cases.filter((item) => (item.trigger_type || "unspecified") === trigger);
    return [...matching].sort((a, b) => compare(a, b, sort.key) * sort.direction);
  }, [cases, trigger, sort]);

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

  const maxBucket = Math.max(1, ...buckets.map((bucket) => bucket.count));
  const header = (key: SortKey, label: string) => <th aria-sort={sort.key === key ? (sort.direction === 1 ? "ascending" : "descending") : "none"}>
    <button className="sort" onClick={() => setSort({ key, direction: sort.key === key ? (sort.direction === 1 ? -1 : 1) : key === "case_id" ? 1 : -1 })} type="button">{label}<Icon name="chevron" size={13} style={{ opacity: sort.key === key ? 1 : 0.3, transform: sort.key === key && sort.direction === 1 ? "rotate(180deg)" : undefined }} /></button>
  </th>;

  return <>
    <section className="queue-hero">
      <div><h1>Case queue</h1><p>{query ? `${cases.length} of ${total} cases match “${query}”.` : `${total} case${total === 1 ? "" : "s"} from the loaded case pack. Open one to start the investigation.`}</p></div>
      <button className="button ghost" disabled={busy} onClick={onLoadPack} type="button"><Icon name="upload" size={15} />Replace case pack</button>
    </section>

    <section className="queue-stats" aria-label="Queue summary">
      <article><span>Cases</span><strong>{cases.length}</strong><small>{visited.size ? `${visited.size} opened this session` : "None opened yet"}</small></article>
      <article><span>Triggers</span><div className="trigger-bars">{triggers.map(([name, count]) => <div key={name}><em>{humanize(name)}</em><i style={{ width: `${(count / Math.max(1, cases.length)) * 100}%` }} /><b>{count}</b></div>)}</div></article>
      <article><span>Risk scores</span>{risks.length ? <>
        <div className="histogram" aria-hidden="true">{buckets.map((bucket, index) => <i key={index} style={{ height: `${Math.max(4, (bucket.count / maxBucket) * 100)}%` }} title={`${bucket.count} case(s) from ${bucket.from.toFixed(2)}`} />)}</div>
        <small>{risks.length} scored, {Math.min(...risks).toFixed(2)} to {Math.max(...risks).toFixed(2)}</small>
      </> : <small>No risk scores in this case pack</small>}</article>
      <article><span>Opened between</span>{opened.length ? <><strong className="stat-date">{dayRange(Math.min(...opened), Math.max(...opened))}</strong><small>Most recent case opened {relative(new Date(Math.max(...opened)).toISOString())}</small></> : <small>No open dates supplied</small>}</article>
    </section>

    <section className="panel queue">
      <div className="chips" role="group" aria-label="Filter by trigger">
        <button aria-pressed={trigger === "all"} onClick={() => setTrigger("all")} type="button">All<b>{cases.length}</b></button>
        {triggers.map(([name, count]) => <button aria-pressed={trigger === name} key={name} onClick={() => setTrigger(name)} type="button">{humanize(name)}<b>{count}</b></button>)}
      </div>
      {!rows.length ? <p className="empty">{total ? "No cases match your search." : "The loaded case pack has no cases."}</p> : <div className="table-wrap"><table className="data-table queue-table">
        <thead><tr>{header("case_id", "Case")}<th>Trigger</th>{header("opened_at", "Opened")}<th>Transaction</th><th>Customer</th>{risks.length > 0 && header("risk_score", "Risk")}<th><span className="sr-only">Open</span></th></tr></thead>
        <tbody>{rows.map((item) => {
          const risk = toNumber(item.risk_score);
          return <tr aria-selected={item.case_id === selected} key={item.case_id} onClick={() => !busy && onRun(item.case_id)}>
            <td className="ids strong">{item.case_id}{visited.has(item.case_id) && <span className="tag muted">Opened</span>}</td>
            <td className="trigger-cell"><span className={`trigger-type t-${(item.trigger_type || "unspecified").replace(/[^a-z]/gi, "")}`}>{item.trigger_type ? humanize(item.trigger_type) : "Unspecified"}</span>{item.trigger_text && <p>{item.trigger_text}</p>}</td>
            <td title={dateTime(item.opened_at) ?? undefined}>{relative(item.opened_at) ?? "—"}<small className="sub">{dateTime(item.opened_at)}</small></td>
            <td className="ids">{item.flagged_txn_id || "—"}</td>
            <td className="ids">{item.customer_id || "—"}{item.card_id && <small className="sub">{item.card_id}</small>}</td>
            {risks.length > 0 && <td>{risk === null ? <span className="muted-text">Not scored</span> : <span className="risk-cell"><span className="track"><i style={{ width: `${Math.min(1, Math.max(0, risk)) * 100}%` }} /></span>{risk.toFixed(2)}</span>}</td>}
            <td className="num"><button className="button small" disabled={busy} onClick={(event) => { event.stopPropagation(); onRun(item.case_id); }} type="button">{busy && item.case_id === selected ? "Opening…" : "Investigate"}</button></td>
          </tr>;
        })}</tbody>
      </table></div>}
    </section>
  </>;
}
