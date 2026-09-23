"use client";

import { useEffect, useState } from "react";
import { dateTime, humanize } from "../lib/format";
import { Investigation } from "../lib/types";
import { Icon } from "./icons";
import { Panel, redact } from "./Panels";

/** Mirrors Python's json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True). */
function canonical(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${canonical(key)}:${canonical(item)}`).join(",")}}`;
  }
  if (typeof value === "string") return JSON.stringify(value).replace(/[\u007f-￿]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return JSON.stringify(value);
}

async function sha256(text: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

type Check = "verified" | "mismatch" | "unavailable";

/**
 * Recomputes every ledger hash in the browser from the audit events the API
 * returned. A match proves the events shown are exactly the ones that were sealed.
 */
function useChainCheck(data: Investigation) {
  const [checks, setChecks] = useState<Check[] | null>(null);
  useEffect(() => {
    const ledger = data.integrity_ledger ?? []; const audit = data.audit ?? [];
    if (!ledger.length || !globalThis.crypto?.subtle) { setChecks(null); return; }
    let live = true;
    (async () => {
      const results: Check[] = [];
      for (const [index, entry] of ledger.entries()) {
        const event = audit[index];
        if (!event || audit.length !== ledger.length) { results.push("unavailable"); continue; }
        const hash = await sha256(canonical({ case_id: data.case_id, previous_hash: entry.previous_hash, event }));
        results.push(hash === entry.hash ? "verified" : "mismatch");
      }
      if (live) setChecks(results);
    })();
    return () => { live = false; };
  }, [data]);
  return checks;
}

export function AuditView({ data }: { data: Investigation }) {
  const ledger = data.integrity_ledger ?? [];
  const events = redact(data.audit ?? []);
  const checks = useChainCheck(data);
  const linked = ledger.every((entry, index) => entry.previous_hash === (index ? ledger[index - 1].hash : "GENESIS"));
  const headMatches = !data.integrity || !ledger.length || ledger[ledger.length - 1].hash === data.integrity.latest_hash;
  const recomputed = checks?.filter((check) => check === "verified").length ?? 0;
  const mismatched = checks?.some((check) => check === "mismatch");
  const verdict = !ledger.length ? null : !linked || !headMatches || mismatched ? "broken" : checks && recomputed === ledger.length ? "verified" : "linked";

  return <>
    {verdict && <section className={`seal seal-${verdict}`}>
      <span className="seal-icon"><Icon name={verdict === "broken" ? "x" : "shield"} size={26} /></span>
      <div>
        <h2>{verdict === "verified" ? "Case record verified" : verdict === "linked" ? "Hash chain intact" : "Case record does not verify"}</h2>
        <p>{verdict === "verified" ? `Your browser recomputed all ${ledger.length} SHA-256 hashes from the audit events, and every one matches the sealed ledger.`
          : verdict === "linked" ? "Every entry points at the hash before it. The events themselves could not be re-hashed in this browser."
          : !linked ? "An entry does not point at the hash before it, so the chain was altered." : "A recomputed hash differs from the sealed ledger."}</p>
      </div>
      {data.integrity && <dl><div><dt>Sealed events</dt><dd>{data.integrity.event_count}</dd></div><div><dt>Latest hash</dt><dd className="hash">{data.integrity.latest_hash.slice(0, 12)}…{data.integrity.latest_hash.slice(-6)}</dd></div></dl>}
    </section>}

    {ledger.length > 0 && <Panel icon="ledger" subtitle="Each block seals one event and the hash of the block before it" title="Hash chain">
      <ol className="chain">{ledger.map((entry, index) => {
        const check = checks?.[index];
        return <li className={check ?? "pending"} key={entry.sequence}>
          <span className="chain-seq">{entry.sequence}</span>
          <div className="chain-body">
            <div className="chain-head"><strong>{humanize(entry.event_type)}</strong><span className={`tag ${check === "verified" ? "ok" : check === "mismatch" ? "risk" : "muted"}`}>{check === "verified" ? "Hash verified" : check === "mismatch" ? "Hash differs" : check === "unavailable" ? "Event not returned" : "Checking…"}</span></div>
            <small>{dateTime(entry.recorded_at)}</small>
            <div className="chain-hashes"><span><em>Previous</em><code>{entry.previous_hash === "GENESIS" ? "Genesis" : `${entry.previous_hash.slice(0, 16)}…`}</code></span><span><em>Hash</em><code>{entry.hash.slice(0, 16)}…</code></span></div>
          </div>
        </li>;
      })}</ol>
    </Panel>}

    <Panel icon="pulse" subtitle="Tool calls and workflow events, with credentials removed" title="Audit events">
      {!events.length ? <p className="empty">No audit events recorded yet.</p> : <ol className="audit">{events.map((event, index) => <li key={index}>
        <div className="audit-head"><strong>{humanize(event.type ?? event.tool ?? "event")}</strong>{Object.entries(event).filter(([key, value]) => key !== "type" && typeof value !== "object").slice(0, 4).map(([key, value]) => <span className="tag muted" key={key}>{humanize(key)}: {String(value)}</span>)}</div>
        <details><summary>Raw event</summary><pre>{JSON.stringify(event, null, 2)}</pre></details>
      </li>)}</ol>}
    </Panel>
  </>;
}
