# Submission checklist

## Verified in the repository

- Live TigerGraph MCP connection and all seven `agent_*` GSQL queries pass the smoke test.
- GraphRAG indexes 5,570 policy, pattern and closed-case chunks into `KnowledgeChunk` and returns policy, pattern and prior-case citations.
- The real 20-case benchmark produced 20 valid answer files with zero review failures and wrote formal cases to the graph (rerun after the device-fingerprint fixes: 3 undocumented cases, each tied to a specific device or ring, instead of 13).
- Case writes use `InvestigationCase` plus deployed relationship names; approval routes are policy-derived and role-protected.
- Frontend TypeScript check passes; Python suite passes with 167 tests.
- Calibration report is generated at `outputs/CALIBRATION_REAL.md`.

## Known gaps (need the dataset folder on the machine running the scripts)

- Every `ClosedCase` vertex on the live graph has empty attributes, so closed-case outcomes, patterns and narratives cannot inform live investigations yet. Run `python scripts/load_dataset_to_graph.py --data-dir $DATA`, then rebuild the closed-case chunks with `scripts/index_fraud_knowledge.py`.
- Transactions carry no identity signals (`id_15`, `id_23`, `id_34`) until the same loader runs, so the new-device and account-takeover detectors cannot fire on the live graph.
- `outputs/CALIBRATION_REAL.md` predates the device-fingerprint fixes; rerun `scripts/calibrate_closed_cases.py` on the CSVs.

## Manual before submission

- Record the 3–5 minute demo using `docs/submission/DEMO_SCRIPT.md`.
- Publish `docs/submission/BLOG_POST.md` with two screenshots and the repository/demo links.
- Publish one post from `docs/submission/SOCIAL_POSTS.md`, tagging `@TigerGraphDB`.
- Submit the repository, demo, blog, social links and `outputs/benchmark_final/answers/` in the hackathon form.
