# Hackathon demo playbook

## The story to tell

Sentinel is not a chatbot that labels a transaction. It is an evidence-first
fraud operations system: it opens a case from a trigger, assembles graph
context, determines whether there is enough evidence to act, controls risky
actions through policy and approval routes, and leaves a verifiable case
record behind.

The key line for judges: **the model may explain an investigation, but it
cannot create facts, alter deterministic probability, or execute a protected
action.**

## Three-to-five minute demo

| Time | Show | Say |
|---|---|---|
| 0:00–0:25 | Sentinel intake and system state | “The UI distinguishes an unreachable API from an API that is online but awaiting benchmark input. We never show fabricated cases.” |
| 0:25–0:45 | Load `case_pack.csv` if needed | “This is the official benchmark trigger set. It is a case input, not historical fraud truth.” |
| 0:45–1:20 | Start a case and open Graph Evidence | “Evidence is graph-grounded: transactions, customer/card context, device, region, email, connections, and prior cases are retrieved as facts.” |
| 1:20–1:50 | Decision Integrity panel | “This makes source diversity, open evidence, and audit coverage visible. It deliberately separates evidence completeness from fraud probability.” |
| 1:50–2:25 | Evidence request and Actions tabs | “When uncertainty remains, the agent asks a controlled question. Policies R1–R10 select a next best action; L1/L2 actions require human approval.” |
| 2:25–2:50 | Tamper-evident case ledger | “Every event extends a SHA-256 hash chain. A later evidence response cannot be silently inserted or changed without breaking the chain.” |
| 2:50–3:20 | Export case dossier | “The dossier is a redacted, portable record of the trigger, evidence, actions, SAR state, and audit trail—ready for review and submission.” |

## Differentiators to emphasize

1. **Truth boundary:** TigerGraph/GSQL supplies facts; deterministic components
   calculate assessment and policy; the LLM is optional and grounded only.
2. **Uncertainty is a first-class state:** the system requests evidence instead
   of overconfidently blocking on a single risk signal.
3. **Controlled execution:** action recommendations and actual execution have
   separate paths. L1/L2 approvals stay visible and auditable.
4. **Case memory:** closed cases, GraphRAG retrieval, and system-created
   `InvestigationCase` records provide historical context without contaminating
   benchmark truth.
5. **Tamper-evident dossier:** a hash-chained case ledger plus redacted export
   makes the decision record practical for regulated operations.

## Before recording

- Confirm the TigerGraph graph, schema, loading job, and installed queries are
  available.
- Set a real `CASE_PACK_PATH`, or load the supplied CSV through the workbench.
- Confirm the API reports `workflow_configured: true` from `/health`.
- Use only graph-returned facts in your explanation. Do not claim a fraud
  result that the evidence/policy layer did not return.
- Capture the output dossiers and SAR artifacts required by the submission.

## Submission checklist

- [ ] Public GitHub repository with setup instructions and `.env.example` only
- [ ] Outputs for all twenty cases in the required answer format
- [ ] Graph-written case records and SARs where policy requires them
- [ ] Before/after-evidence next best action and approval route recorded
- [ ] Three-to-five minute end-to-end video
- [ ] Technical blog post: architecture, TigerGraph, agent design, learning,
  and next improvements
- [ ] Social post tagging `@TigerGraphDB` with the demo or blog link
