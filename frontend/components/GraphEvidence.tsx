"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { humanize } from "../lib/format";
import { Graph } from "../lib/types";
import { entityColor, Icon, iconDataUri } from "./icons";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function GraphEvidence({ graph, theme }: { graph?: Graph; theme?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [layout, setLayout] = useState("breadthfirst");
  const [focus, setFocus] = useState("all");
  const [picked, setPicked] = useState<Record<string, unknown> | null>(null);
  const [find, setFind] = useState("");
  const types = useMemo(() => [...new Set((graph?.nodes ?? []).map((node) => node.data.entity_type).filter(Boolean))] as string[], [graph]);

  useEffect(() => {
    if (!ref.current || !graph?.nodes.length) return;
    const text = cssVar("--text"); const muted = cssVar("--muted"); const line = cssVar("--line-strong");
    const surface = cssVar("--surface-2"); const risk = cssVar("--risk"); const info = cssVar("--info");
    const cy = cytoscape({
      container: ref.current,
      elements: [...graph.nodes, ...graph.edges] as ElementDefinition[],
      wheelSensitivity: 0.2,
      style: [
        { selector: "node", style: { "background-color": surface, "border-width": 2, "border-color": info, label: "data(label)", color: text, "font-size": 11, "font-family": "IBM Plex Sans, system-ui, sans-serif", "text-valign": "bottom", "text-margin-y": 8, "text-wrap": "ellipsis", "text-max-width": "120px", width: 42, height: 42 } },
        ...Object.keys(entityColor).map((type) => ({ selector: `node[entity_type = "${type}"]`, style: { "border-color": entityColor[type], "background-image": iconDataUri(type, entityColor[type]), "background-width": "55%", "background-height": "55%" } })),
        { selector: "node[?flagged]", style: { "border-color": risk, "border-width": 3, "underlay-color": risk, "underlay-opacity": 0.18, "underlay-padding": 8 } },
        ...Object.keys(entityColor).map((type) => ({ selector: `node[?flagged][entity_type = "${type}"]`, style: { "background-image": iconDataUri(type, risk) } })),
        { selector: "node:selected", style: { "border-color": text } },
        { selector: "node.match", style: { "border-color": text, "border-width": 4, "underlay-color": text, "underlay-opacity": 0.15, "underlay-padding": 10 } },
        { selector: "node.faded, edge.faded", style: { opacity: 0.2 } },
        { selector: "edge", style: { width: 1.4, "line-color": line, "target-arrow-color": line, "target-arrow-shape": "triangle", "curve-style": "bezier", label: "data(label)", color: muted, "font-size": 9, "text-rotation": "autorotate", "text-margin-y": -8 } },
      ],
      layout: (layout === "breadthfirst" ? { name: "breadthfirst", directed: true, spacingFactor: 1.3, padding: 30 } : { name: layout, padding: 30 }) as cytoscape.LayoutOptions,
    });
    cy.on("tap", "node", (event) => setPicked(event.target.data()));
    cy.on("tap", (event) => { if (event.target === cy) setPicked(null); });
    cyRef.current = cy;
    return () => { cy.destroy(); cyRef.current = null; };
  }, [graph, layout, theme]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    cy.nodes().forEach((node) => { node.style("display", focus === "all" || node.data("entity_type") === focus ? "element" : "none"); });
    cy.edges().forEach((edge) => { edge.style("display", edge.source().style("display") === "none" || edge.target().style("display") === "none" ? "none" : "element"); });
  }, [focus, layout, graph, theme]);

  useEffect(() => {
    const cy = cyRef.current; if (!cy) return;
    const needle = find.trim().toLowerCase();
    cy.elements().removeClass("match faded");
    if (!needle) return;
    const hits = cy.nodes().filter((node) => [node.id(), node.data("label"), node.data("entity_id")].some((value) => String(value ?? "").toLowerCase().includes(needle)));
    if (!hits.length) return;
    hits.addClass("match");
    cy.elements().not(hits.closedNeighborhood()).addClass("faded");
    cy.animate({ fit: { eles: hits.closedNeighborhood(), padding: 60 } }, { duration: 250 });
  }, [find, graph, layout, theme]);

  return <section className="panel explorer">
    <header className="panel-head">
      <span className="panel-icon"><Icon name="graph" /></span>
      <div><h2>Graph explorer</h2><p>{graph?.nodes.length ?? 0} entities, {graph?.edges.length ?? 0} links. Drag to rearrange; select an entity to inspect it.</p></div>
      <div className="toolbar">
        <label>Find<input onChange={(event) => setFind(event.target.value)} placeholder="Entity ID" type="text" value={find} /></label>
        <label>Show<select value={focus} onChange={(event) => setFocus(event.target.value)}><option value="all">All entities</option>{types.map((type) => <option key={type} value={type}>{humanize(type.replace(/([a-z])([A-Z])/g, "$1_$2"))}</option>)}</select></label>
        <label>Layout<select value={layout} onChange={(event) => setLayout(event.target.value)}><option value="breadthfirst">Hierarchy</option><option value="cose">Force</option><option value="circle">Circle</option><option value="concentric">Concentric</option></select></label>
        <button className="button ghost" onClick={() => cyRef.current?.fit(undefined, 30)} type="button">Fit view</button>
      </div>
    </header>
    {!graph?.nodes.length ? <p className="empty">This investigation returned no graph entities.</p> : <div className="explorer-body"><div className="explorer-canvas" ref={ref} aria-label="Interactive investigation graph" />{picked && <aside className="map-detail"><div className="map-detail-head"><strong>{String(picked.entity_id ?? picked.label ?? picked.id)}</strong><button aria-label="Close entity details" className="icon-button small" onClick={() => setPicked(null)} type="button"><Icon name="x" size={14} /></button></div><dl>{Object.entries(picked).filter(([key, value]) => !["id", "label"].includes(key) && value !== "" && value !== undefined).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></aside>}</div>}
  </section>;
}
