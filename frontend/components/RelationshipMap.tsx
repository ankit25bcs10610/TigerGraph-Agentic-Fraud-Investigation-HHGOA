"use client";

import { useMemo, useState } from "react";
import { humanize } from "../lib/format";
import { Graph, GraphNode } from "../lib/types";
import { entityIcon, Icon } from "./icons";

const COLUMN = 210;
const ROW = 108;
const PAD_X = 90;
const PAD_Y = 56;
const RADIUS = 25;

type Placed = { node: GraphNode; x: number; y: number; layer: number };

/**
 * Lays the returned subgraph out left-to-right by edge direction, so money and
 * ownership read as a flow from customer to transaction to its linked context.
 */
function layout(graph: Graph): { placed: Map<string, Placed>; width: number; height: number } {
  const ids = graph.nodes.map((node) => node.data.id);
  const known = new Set(ids);
  const edges = graph.edges.filter((edge) => known.has(edge.data.source) && known.has(edge.data.target) && edge.data.source !== edge.data.target);
  const layer = new Map(ids.map((id) => [id, 0]));
  // Longest-path layering, bounded by the node count so cycles cannot loop forever.
  for (let pass = 0; pass < ids.length; pass += 1) {
    let changed = false;
    for (const edge of edges) {
      const next = Math.min((layer.get(edge.data.source) ?? 0) + 1, ids.length);
      if (next > (layer.get(edge.data.target) ?? 0)) { layer.set(edge.data.target, next); changed = true; }
    }
    if (!changed) break;
  }
  const columns = new Map<number, GraphNode[]>();
  for (const node of graph.nodes) {
    const index = layer.get(node.data.id) ?? 0;
    columns.set(index, [...(columns.get(index) ?? []), node]);
  }
  const ordered = [...columns.keys()].sort((a, b) => a - b);
  const tallest = Math.max(1, ...[...columns.values()].map((column) => column.length));
  const height = PAD_Y * 2 + (tallest - 1) * ROW + 40;
  const placed = new Map<string, Placed>();
  ordered.forEach((key, columnIndex) => {
    const column = columns.get(key) ?? [];
    const offset = (height - (column.length - 1) * ROW) / 2 - 12;
    column.forEach((node, rowIndex) => placed.set(node.data.id, { node, layer: columnIndex, x: PAD_X + columnIndex * COLUMN, y: offset + rowIndex * ROW }));
  });
  return { placed, width: PAD_X * 2 + (ordered.length - 1) * COLUMN, height };
}

function shorten(text: string, max = 22) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function RelationshipMap({ graph, onExpand }: { graph?: Graph; onExpand?: () => void }) {
  const [active, setActive] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const { placed, width, height } = useMemo(() => layout(graph ?? { nodes: [], edges: [] }), [graph]);
  const types = useMemo(() => [...new Set((graph?.nodes ?? []).map((node) => node.data.entity_type).filter(Boolean))] as string[], [graph]);
  const focus = active ?? selected;
  const neighbours = useMemo(() => {
    if (!focus || !graph) return null;
    const linked = new Set([focus]);
    graph.edges.forEach((edge) => { if (edge.data.source === focus) linked.add(edge.data.target); if (edge.data.target === focus) linked.add(edge.data.source); });
    return linked;
  }, [focus, graph]);
  const detail = selected ? placed.get(selected)?.node : undefined;

  return <section className="panel map-panel" aria-labelledby="map-title">
    <header className="panel-head">
      <span className="panel-icon"><Icon name="graph" /></span>
      <div><h2 id="map-title">Fraud relationship map</h2><p>Entities and links the investigation returned for this case</p></div>
      <div className="map-legend" aria-label="Legend">
        <span><i className="dot flagged" />Flagged</span>
        {types.map((type) => <span key={type}><Icon name={entityIcon[type] ?? "node"} size={13} />{humanize(type.replace(/([a-z])([A-Z])/g, "$1_$2"))}</span>)}
      </div>
      {onExpand && <button aria-label="Open graph explorer" className="icon-button" onClick={onExpand} type="button"><Icon name="expand" size={16} /></button>}
    </header>
    {!graph?.nodes.length ? <p className="empty">Run the investigation to see how the customer, card and transaction are connected.</p> :
    <div className="map-body">
      <div className="map-scroll">
        <svg className="map-svg" role="img" aria-label={`Relationship map with ${graph.nodes.length} entities and ${graph.edges.length} links`} viewBox={`0 0 ${Math.max(width, 420)} ${height}`} style={{ minWidth: Math.max(width, 420) * 0.78 }}>
          <defs>
            <marker id="arrow" markerHeight="8" markerWidth="8" orient="auto-start-reverse" refX="7" refY="4" viewBox="0 0 8 8"><path d="M0 0 8 4 0 8z" fill="currentColor" /></marker>
          </defs>
          {graph.edges.map((edge) => {
            const from = placed.get(edge.data.source); const to = placed.get(edge.data.target);
            if (!from || !to) return null;
            const forward = to.x > from.x;
            const sx = from.x + (forward ? RADIUS + 4 : 0); const sy = from.y + (forward ? 0 : RADIUS + 4);
            const tx = to.x - (forward ? RADIUS + 8 : 0); const ty = to.y - (forward ? 0 : RADIUS + 8);
            const bend = forward ? (tx - sx) * 0.5 : 60;
            const d = forward ? `M${sx} ${sy} C${sx + bend} ${sy} ${tx - bend} ${ty} ${tx} ${ty}` : `M${sx} ${sy} C${sx + bend} ${sy + bend} ${tx + bend} ${ty - bend} ${tx} ${ty}`;
            const dim = neighbours && !(neighbours.has(edge.data.source) && neighbours.has(edge.data.target));
            const flaggedLink = Boolean(from.node.data.flagged || to.node.data.flagged);
            return <g className={`map-edge ${dim ? "dim" : ""} ${flaggedLink ? "hot" : ""}`} key={edge.data.id}>
              <path d={d} markerEnd="url(#arrow)" />
              {edge.data.label && <text x={(sx + tx) / 2} y={(sy + ty) / 2 - 8}>{humanize(edge.data.label).toLowerCase()}</text>}
            </g>;
          })}
          {[...placed.values()].map(({ node, x, y }) => {
            const type = node.data.entity_type ?? "Entity";
            const dim = neighbours && !neighbours.has(node.data.id);
            const label = node.data.entity_id ?? node.data.label ?? node.data.id;
            return <g aria-label={`${humanize(type)} ${label}`} className={`map-node ${node.data.flagged ? "flagged" : ""} ${dim ? "dim" : ""} ${selected === node.data.id ? "selected" : ""}`} key={node.data.id} onBlur={() => setActive(null)} onClick={() => setSelected(selected === node.data.id ? null : node.data.id)} onFocus={() => setActive(node.data.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelected(selected === node.data.id ? null : node.data.id); } }} onMouseEnter={() => setActive(node.data.id)} onMouseLeave={() => setActive(null)} role="button" tabIndex={0} transform={`translate(${x} ${y})`}>
              {node.data.flagged && <circle className="halo" r={RADIUS + 9} />}
              <circle className="disc" r={RADIUS} />
              <Icon name={entityIcon[type] ?? "node"} size={22} x={-11} y={-11} />
              <text className="node-label" y={RADIUS + 20}>{shorten(String(label))}</text>
              <text className="node-type" y={RADIUS + 35}>{humanize(type.replace(/([a-z])([A-Z])/g, "$1_$2"))}</text>
            </g>;
          })}
        </svg>
      </div>
      {detail && <aside className="map-detail" aria-live="polite">
        <div className="map-detail-head"><Icon name={entityIcon[detail.data.entity_type ?? ""] ?? "node"} size={16} /><strong>{String(detail.data.entity_id ?? detail.data.label ?? detail.data.id)}</strong><button aria-label="Close entity details" className="icon-button small" onClick={() => setSelected(null)} type="button"><Icon name="x" size={14} /></button></div>
        <dl>{Object.entries(detail.data).filter(([key, value]) => !["id", "label"].includes(key) && value !== "" && value !== undefined).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
        <p>{graph.edges.filter((edge) => edge.data.source === detail.data.id || edge.data.target === detail.data.id).length} direct links</p>
      </aside>}
    </div>}
  </section>;
}
