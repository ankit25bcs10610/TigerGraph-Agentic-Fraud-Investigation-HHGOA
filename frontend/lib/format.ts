import { Investigation, TimelineRow } from "./types";

export function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const usdCompact = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });

export function money(value: unknown, compact = false): string | null {
  const amount = toNumber(value);
  if (amount === null) return null;
  return compact && Math.abs(amount) >= 10000 ? usdCompact.format(amount) : usd.format(amount);
}

/** Turns API identifiers such as `account_takeover` into readable text. */
export function humanize(value: unknown): string {
  const text = String(value ?? "").replaceAll("_", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1).toLowerCase() : "";
}

export function dateTime(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function clock(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function relative(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return null;
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of units) if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  return format.format(seconds, "second");
}

export function percent(value: unknown): string | null {
  const number = toNumber(value);
  return number === null ? null : `${Math.round(number * 100)}%`;
}

export function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

export const rowAmount = (row: TimelineRow) => toNumber(row.transaction_amt ?? row.amount_usd);
export const rowTime = (row: TimelineRow) => row.ts ?? row.timestamp;

/** The flagged transaction row, as returned in the investigation timeline. */
export function flaggedRow(data: Investigation): TimelineRow | undefined {
  const rows = data.timeline ?? [];
  return rows.find((row) => row.transaction_id && row.transaction_id === data.flagged_txn_id) ?? rows.find((row) => row.suspicious);
}

export type Severity = "high" | "medium" | "low" | "none";

/** Tone follows the API-returned verdict; the browser never derives a fraud outcome itself. */
export function verdictTone(verdict: unknown): Severity {
  if (verdict === "fraud") return "high";
  if (verdict === "uncertain") return "medium";
  if (verdict === "legitimate") return "low";
  return "none";
}
