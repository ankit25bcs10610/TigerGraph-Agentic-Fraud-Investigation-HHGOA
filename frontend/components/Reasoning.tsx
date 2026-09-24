"use client";

import { useState } from "react";
import { humanize } from "../lib/format";
import { AgentStep, Investigation, PolicyCitation } from "../lib/types";
import { Icon, IconName } from "./icons";
import { Panel } from "./Panels";

const toolIcon: Record<string, IconName> = {
  get_transaction: "swap", get_customer_activity: "user", get_device_activity: "device", detect_device_ring: "graph",
  get_linked_closed_cases: "folder", get_closed_cases_by_pattern: "folder", recall_case_memory: "ledger", synthesize_explanation: "doc",
  graphrag_retrieve: "search", finish_investigation: "check", skip_device_tools: "shield", find_ring_membership: "graph", recall_graph_memory: "ledger",
};

const plannerLabel: Record<string, string> = { llm: "Chosen by LLM", "llm-fallback": "LLM fallback: rules", rules: "Rule planner", required: "Required step" };

export const sourceLabel: Record<string, string> = { "tigergraph-mcp": "TigerGraph MCP", csv: "CSV files", "case-memory": "Case memory", llm: "LLM", none: "No graph",
  rules: "Rule planner", "graphrag:tfidf": "GraphRAG (TF-IDF)", "graphrag:tigergraph-vector": "GraphRAG (TigerGraph vectors)", "planner:llm": "LLM planner", "planner:rules": "Rule planner" };

function args(step: AgentStep) {
  return Object.entries(step.args).map(([key, value]) => `${key}=${String(value)}`).join(", ");
}

/** Every tool the agent called, in order, with why it called it and what came back. */
export function AgentReasoning({ data }: { data: Investigation }) {
  const steps = data.agent_trace ?? [];
  const [open, setOpen] = useState(false);
  const shown = open ? steps : steps.slice(0, 8);
  const total = steps.reduce((sum, step) => sum + (step.ms || 0), 0);
  return <Panel action={<span className="source-chip"><i className={data.data_source === "tigergraph-mcp" ? "live" : ""} />{sourceLabel[data.data_source ?? "none"] ?? data.data_source}</span>}
    className="reasoning" icon="radar" subtitle={steps.length ? `${steps.length} tool calls in ${total < 1 ? "under 1 ms" : total < 1000 ? `${Math.round(total)} ms` : `${(total / 1000).toFixed(1)} s`}. Each step says why it ran.` : "Tool calls appear once the agent investigates"} title="Agent reasoning">
    {!steps.length ? <p className="empty">The agent hasn&apos;t called any graph tools for this case.</p> : <>
      <ol className="trace">{shown.map((step) => <li className={step.ok ? "" : "failed"} key={step.step}>
        <span className="trace-icon"><Icon name={toolIcon[step.tool] ?? "node"} size={15} /></span>
        <div className="trace-body">
          <div className="trace-head"><code>{step.tool}</code><span className="trace-args">{args(step)}</span>{step.planner && step.planner !== "rules" && <span className={`planner-badge p-${step.planner}`}>{plannerLabel[step.planner] ?? step.planner}</span>}<span className="trace-meta">{sourceLabel[step.source] ?? step.source}{step.ms ? `, ${step.ms} ms` : ""}</span></div>
          <p className="trace-reason">{step.reason}</p>
          <p className="trace-result"><Icon name={step.ok ? "check" : "x"} size={13} />{step.result}</p>
        </div>
      </li>)}</ol>
      {steps.length > 8 && <button className="link-button" onClick={() => setOpen(!open)} type="button">{open ? "Show fewer steps" : `Show all ${steps.length} steps`}</button>}
    </>}
  </Panel>;
}

/** The agent's own account of the verdict, the evidence, what is still uncertain and why it acted. */
export function Explanation({ data }: { data: Investigation }) {
  const explanation = data.explanation;
  if (!explanation) return null;
  const rows: [string, string | undefined, IconName][] = [
    ["Verdict", explanation.verdict, "target"],
    ["Evidence", explanation.evidence, "doc"],
    ["What is still uncertain", explanation.uncertainty, "pulse"],
    ["Why these actions", explanation.actions, "shield"],
  ];
  return <Panel className="explain" icon="doc" subtitle={explanation.narrative ? `Written by ${data.llm_usage?.model ?? "the LLM"} from cited evidence only` : "Built from the investigation's own evidence and policy"} title="Why the agent decided this">
    {explanation.narrative && <p className="narrative-lead">{explanation.narrative}</p>}
    <dl className="why">{rows.filter(([, value]) => value).map(([label, value, icon]) => <div key={label}><dt><Icon name={icon} size={14} />{label}</dt><dd>{value}</dd></div>)}</dl>
  </Panel>;
}

/** The policy text each recommended action is grounded in. */
export function PolicyGrounding({ items }: { items: PolicyCitation[] }) {
  if (!items.length) return null;
  return <Panel icon="shield" subtitle="The rule behind each recommendation, plus the policy passages GraphRAG retrieved for this case" title="Policy grounding">
    <ul className="grounding">{items.map((item) => <li key={item.ref}>
      <div className="grounding-head"><span className="tag">{item.title}</span>{item.source.startsWith("graphrag") ? <span className="tag graphrag">Retrieved by {sourceLabel[item.source] ?? "GraphRAG"}{item.score !== undefined ? `, similarity ${item.score.toFixed(2)}` : ""}</span> : item.supports.length ? <span className="tag ok">Applied rule</span> : null}{item.supports.map((action) => <span className="tag muted" key={action}>{humanize(action)}</span>)}<code>{item.ref}</code></div>
      <p>{item.text}</p>
    </li>)}</ul>
  </Panel>;
}
