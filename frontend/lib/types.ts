export type Route = "auto" | "L1" | "L2";
export type Action = { action: string; route: Route; reason: string };
export type Evidence = { claim: string; source: string; ref: string; entity_ids: string[]; simulated?: boolean; assumption?: string; result?: string; details?: string };
export type EvidenceRequest = { request_id: string; case_id: string; type: "customer_validation" | "step_up_auth" | "analyst_info"; question: string; reason: string; status?: string };
export type CaseOption = { case_id: string; trigger_type?: string; trigger_text?: string; opened_at?: string; flagged_txn_id?: string; customer_id?: string; card_id?: string; risk_score?: string | number };

export type GraphNode = { data: { id: string; label?: string; entity_type?: string; entity_id?: string; flagged?: boolean; [key: string]: unknown } };
export type GraphEdge = { data: { id: string; source: string; target: string; label?: string; [key: string]: unknown } };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type TimelineRow = { transaction_id?: string; ts?: string; timestamp?: string; transaction_amt?: string | number; amount_usd?: string | number; channel?: string; risk_score?: string | number; device_profile_id?: string; billing_region?: string; email_domain?: string; suspicious?: boolean; in_episode?: boolean };
export type SimilarCase = { case_id?: string; pattern?: string; outcome?: string; similarity_score?: string | number; reason_for_match?: string; matched_text?: string };
export type LedgerEntry = { sequence: number; event_type: string; recorded_at: string; previous_hash: string; hash: string };
export type ApprovalRequest = { action: string; route: "L1" | "L2"; reason: string; approval_status: string };
export type Sar = { file: boolean; reason: string; narrative: string; subjects: string[]; total_amount_usd: number; activity_dates: string[] };

export type AssessedCase = { status?: string; verdict?: string; fraud_probability?: number; pattern?: string; exposure_usd?: number; summary?: string; evidence?: Evidence[]; similar_prior_cases?: string[] };

export type Investigation = {
  case_id: string;
  trigger_type?: string;
  trigger_text?: string;
  opened_at?: string;
  customer_id?: string;
  card_id?: string;
  flagged_txn_id?: string;
  risk_score?: number | string;
  message?: string;
  status?: string;
  case?: AssessedCase;
  stop_reason?: string;
  next_best_actions?: { initial: Action[]; final: Action[]; what_changed: string };
  sar?: Sar;
  graph?: Graph;
  timeline?: TimelineRow[];
  similar_cases?: SimilarCase[];
  audit?: Record<string, unknown>[];
  integrity?: { status: string; event_count: number; latest_hash: string; chain_root: string };
  integrity_ledger?: LedgerEntry[];
  approval_requests?: ApprovalRequest[];
  evidence_requests?: EvidenceRequest[];
  evidence_responses?: Evidence[];
  agent_trace?: AgentStep[];
  explanation?: { verdict?: string; evidence?: string; uncertainty?: string; actions?: string; narrative?: string };
  policy_grounding?: PolicyCitation[];
  data_source?: string;
  llm_usage?: { model: string; total_tokens: number };
  decision_paths?: DecisionPath[];
  score_breakdown?: { probability: number; fraud_threshold: number; legitimate_threshold: number; contributions: Contribution[] };
  blast_radius?: BlastRadius | null;
};

export type DecisionPath = { request_type: string; distinct_decisions: number; settling_answers: number; changes_decision: number; chosen: boolean;
  outcomes: { answer: string; verdict: string; probability: number; settles: boolean; sar: boolean; actions: { action: string; route: string }[] }[] };
export type Contribution = { signal: string; label: string; value: number; weight: number; points: number; without: number; decisive: boolean };
export type BlastRadius = { cards: { card_id: string; customer_id: string; transactions: number; spend_usd: number; last_seen: string; link: string }[]; card_count: number; customers: number; recent_spend_usd: number; confirmed_cases: string[] };

export type AgentStep = { step: number; tool: string; source: string; args: Record<string, unknown>; reason: string; result: string; ok: boolean; ms: number };
export type PolicyCitation = { ref: string; title: string; text: string; source: string; supports: string[] };

export type CaseAssessment = {
  verdict: "fraud" | "uncertain" | "legitimate";
  pattern: string;
  fraud_probability: number;
  exposure_usd: number;
  finding: string;
  flagged_amount: number;
  channel: string;
  status: "not_started" | "awaiting_evidence" | "awaiting_approval" | "completed" | string;
  pending_approvals: { action: string; route: "L1" | "L2" }[];
  open_requests: number;
  sar_required: boolean;
  entities: { customers: string[]; cards: string[]; devices: string[]; shared_devices: string[]; transactions: string[]; closed_cases: string[] };
};
export type CaseOverview = CaseOption & { assessment: CaseAssessment | null };
