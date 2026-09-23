import { SVGProps } from "react";

const paths = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  radar: "M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0-18 0M12 12m-5 0a5 5 0 1 0 10 0a5 5 0 1 0-10 0M12 12l6-6",
  queue: "M4 5h16M4 10h16M4 15h10M4 20h7",
  graph: "M6 6m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M18 6m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M12 18m-2.5 0a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0-5 0M8.2 7.3l2.6 8.4M15.8 7.3l-2.6 8.4M8.5 6h7",
  pulse: "M3 12h4l2.5-6 5 12 2.5-6H21",
  shield: "M12 3 4.5 6v5.5c0 4.6 3.2 8.2 7.5 9.5 4.3-1.3 7.5-4.9 7.5-9.5V6z M8.8 12.2l2.2 2.2 4.4-4.6",
  doc: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM14 3v5h5M9 13h6M9 17h6",
  ledger: "M5 4h14v16H5zM9 4v16M12 8h4M12 12h4M12 16h4",
  bell: "M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20.5a2 2 0 0 0 4 0",
  search: "M11 11m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0M20.5 20.5 16 16",
  play: "M7 4.5v15l12.5-7.5z",
  download: "M12 4v11M7 10.5l5 5 5-5M5 20h14",
  upload: "M12 20V9M7 13.5l5-5 5 5M5 4h14",
  expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7",
  collapse: "M15 5l-7 7 7 7",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  target: "M12 12m-8 0a8 8 0 1 0 16 0a8 8 0 1 0-16 0M12 12m-3.5 0a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0M12 2v4M12 18v4M2 12h4M18 12h4",
  refresh: "M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4",
  user: "M12 8m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M4.5 20.5c1.2-3.6 4.1-5.5 7.5-5.5s6.3 1.9 7.5 5.5",
  card: "M3 6.5h18v11H3zM3 10h18M6.5 14.5h4",
  swap: "M4 8h13l-3.5-3.5M20 16H7l3.5 3.5",
  mail: "M3.5 6h17v12h-17zM4 6.5l8 6.5 8-6.5",
  pin: "M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11zM12 10m-2.3 0a2.3 2.3 0 1 0 4.6 0a2.3 2.3 0 1 0-4.6 0",
  device: "M4 5h16v10H4zM2.5 19h19M10 15v4M14 15v4",
  folder: "M3.5 6.5h6l2 2h9v10.5h-17z",
  bank: "M3 9.5 12 4l9 5.5M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3.5 20.5h17",
  node: "M12 12m-6 0a6 6 0 1 0 12 0a6 6 0 1 0-12 0",
  chevron: "M6 9l6 6 6-6",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  sun: "M12 12m-4 0a4 4 0 1 0 8 0a4 4 0 1 0-8 0M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
} as const;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18, ...props }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return <svg aria-hidden="true" fill="none" height={size} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.7} viewBox="0 0 24 24" width={size} {...props}><path d={paths[name]} /></svg>;
}

/** Icon used for each graph entity type the API may return. */
export const entityIcon: Record<string, IconName> = {
  Customer: "user",
  Card: "card",
  Account: "bank",
  Transaction: "swap",
  EmailDomain: "mail",
  BillingRegion: "pin",
  DeviceProfile: "device",
  IdentityRecord: "device",
  ClosedCase: "folder",
  InvestigationCase: "folder",
};

/** One mid-tone colour per entity type, legible on both themes and shared by the map and explorer. */
export const entityColor: Record<string, string> = {
  Customer: "#3b82f6",
  Card: "#10b981",
  Account: "#10b981",
  Transaction: "#eaa21a",
  EmailDomain: "#8b5cf6",
  BillingRegion: "#14b8a6",
  DeviceProfile: "#f97316",
  IdentityRecord: "#f97316",
  ClosedCase: "#ec4899",
  InvestigationCase: "#ec4899",
};

/** An entity icon as a data URI, for canvas renderers that cannot use inline SVG. */
export function iconDataUri(type: string, color: string) {
  const d = paths[entityIcon[type] ?? "node"];
  return `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`)}`;
}
