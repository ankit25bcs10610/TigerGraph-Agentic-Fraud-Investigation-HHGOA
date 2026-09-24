# Submission runbook

From "we have the dataset and a TigerGraph instance" to "submitted". Deadline: **Sept 24, 2026, 11:59 PM IST**, one submission by the team lead, no resubmissions.

Every command runs from the repository root with the Python environment active.

## 0. Prerequisites (15 min)

Run the preflight before spending time on calibration or graph setup:

```bash
python scripts/submission_preflight.py --dataset-dir "$DATA" --require-graph
```

It must report **PREFLIGHT: PASSED**. The repository's `data/sample/` pack is only a six-case UI demo and must not be used as the 20-case submission input.

1. Download the **HHGOA_IEEE** dataset folder. It must contain `transactions.csv`, `identity.csv`, `closed_cases_history.csv`, `case_pack.csv`, the dataset `README`, the fraud policy, the five fraud patterns and the regulatory references.
2. Read the dataset README's **answer format** section and compare it with `backend/models/answer.py`. If a field differs, tell whoever maintains the answer model before running the benchmark.
3. Create a TigerGraph Savanna workspace (<https://savanna.tgcloud.io>) with **auto-stop and auto-start enabled**, or install Community Edition.
4. Copy `.env.example` to `.env` and fill in `TG_HOST`, `TG_GRAPHNAME=FraudInvestigationGraph`, and `TG_SECRET` (or `TG_USERNAME`/`TG_PASSWORD`). For explanations, set `LLM_PROVIDER=openai`, `LLM_MODEL=gpt-4o-mini` and `OPENAI_API_KEY`.
5. `pip install -r requirements.txt`

Point these at the dataset folder (in `.env` or your shell):

```bash
export DATA=/absolute/path/to/HHGOA_IEEE
export TRANSACTIONS_PATH=$DATA/transactions.csv
export IDENTITY_PATH=$DATA/identity.csv
export CLOSED_CASES_PATH=$DATA/closed_cases_history.csv
export POLICY_DOCS_PATH=$DATA          # policy, patterns and regulations (.md / .txt) for grounding
export CASE_MEMORY_PATH=outputs/case_memory.jsonl
```

If the policy documents are PDFs, convert them to `.txt` first (for example `pdftotext policy.pdf policy.txt`) so the grounding can cite them.

## 1. Check the card mapping (5 min)

```bash
python scripts/check_card_mapping.py --case-pack $DATA/case_pack.csv
```

It must report **Mismatched: 0** (or very close). If many rows mismatch, the derived card IDs disagree with the dataset's labels and every card history will be wrong: stop and fix `card_id` derivation in `scripts/prepare_graph_data.py` before anything else.

## 1b. Find the undocumented pattern (10 min)

```bash
python scripts/discover_patterns.py --case-pack $DATA/case_pack.csv --out outputs/DISCOVERY.md
```

Rings labelled *candidate undocumented* are the leads. Read their transactions, give the pattern a name and a one-line description, and mention it in the blog and video.

## 1c. Measure before touching TigerGraph (30 min)

Run the agent on the CSVs against the closed cases. This is the honest accuracy number, and it tells you which detectors need tuning before the benchmark:

```bash
python scripts/calibrate_closed_cases.py --limit 400 --out outputs/CALIBRATION.md
```

Look at recall and precision per pattern. If one pattern is consistently missed, check that detector in `backend/investigation/patterns.py` against the dataset's pattern definitions (for example channel names, time windows or amount thresholds) and rerun. Keep the final `CALIBRATION.md`: it goes in the blog post.

## 2. Dry-run the 20 benchmark cases on CSV (10 min)

```bash
python scripts/run_benchmark.py --case-pack $DATA/case_pack.csv --out outputs/dry_run
```

`outputs/dry_run/REPORT.md` should show **Needing review: 0**. Cases listed as *waiting for a graph write* are fine at this stage. Open a few answer files and check that they read correctly.

**Assumed evidence responses.** When the agent asks for customer validation or step-up authentication, the runner assumes a response. The defaults are conservative (`no_reply`, `not_completed`). If the dataset README defines assumed responses, put them in a JSON file and pass `--assumptions`:

```json
{ "HHG-001": { "customer_validation": "denied" }, "HHG-007": { "customer_validation": "confirmed" } }
```

Every assumed response is labelled as simulated in the answer files.

## 3. Build the graph (45–90 min, mostly waiting)

```bash
python scripts/prepare_graph_data.py --data-dir $DATA --output-dir build/graph_data --full
python scripts/setup_tigergraph.py --data-dir build/graph_data
```

The setup script creates the schema and loading job, loads every TSV, and installs all queries, including the seven `agent_*` tools. It finishes by printing vertex counts and running `agent_txn_profile` once. If a query fails to install, the error names the file and line; fix it and rerun with `--skip schema job load`.

Build the GraphRAG vector index (policy passages, pattern documents and closed-case narratives, embedded with `EMBEDDING_MODEL`):

```bash
python scripts/index_fraud_knowledge.py --readme $DATA/README.md --closed-case-limit 5565
```

With `EMBEDDING_PROVIDER` set, the agent's `graphrag_retrieve` step then shows *GraphRAG (TigerGraph vectors)* instead of TF-IDF.

Check the MCP connection:

```bash
python scripts/test_tigergraph_mcp.py
```

## 4. The real benchmark run (20 min)

```bash
DATA_SOURCE=tigergraph python scripts/run_benchmark.py --case-pack $DATA/case_pack.csv --write-graph --out outputs
```

This is the submission run. Every graph question goes through TigerGraph MCP, every formal case is written back to the graph as an `InvestigationCase`, and each answer is validated. `outputs/REPORT.md` must show **Needing review: 0** and every formal case **In graph: yes**. The answers are in `outputs/answers/`.

Commit the answers:

```bash
git add outputs/answers outputs/REPORT.md outputs/CALIBRATION.md
git commit -m "Add agent output for the 20 benchmark cases"
git push
```

## 5. Record the demo (45 min)

Start the app against TigerGraph and follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md):

```bash
DATA_SOURCE=tigergraph CASE_PACK_PATH=$DATA/case_pack.csv FRONTEND_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:3001,http://localhost:3001 \
  python -m uvicorn backend.main:app --port 8000
cd frontend && npm run dev -- --port 3001
```

Check that the **Agent reasoning** panel shows *TigerGraph MCP* as the source before you record.

## 6. Publish (45 min)

1. Blog: paste [BLOG_POST.md](BLOG_POST.md) into Hashnode, Medium or dev.to. Add the calibration table and two screenshots.
2. Social: post one of [SOCIAL_POSTS.md](SOCIAL_POSTS.md) on X or LinkedIn with the blog or video link, tagging **@TigerGraphDB**.
3. Submit the form: <https://forms.gle/yxXzqSULGgZ9VUF56>. Have ready: the repository URL, the video link, the blog link, the social post link and the path to `outputs/answers/`.

## If something breaks

| Symptom | Fix |
|---|---|
| `tigergraph-mcp` not found | `pip install -r requirements.txt` in the same environment that runs the API |
| Authentication errors | Regenerate the Savanna secret; check `TG_HOST` has no trailing slash |
| Query install error | The message names the query; fix the GSQL and rerun `setup_tigergraph.py --skip schema job load` |
| Benchmark answers in `_needs_review` | Read the issue column in `REPORT.md`; it names the failed rule |
| Every case "Not assessed" in the UI | `TRANSACTIONS_PATH` (CSV mode) or `DATA_SOURCE=tigergraph` isn't set for the API process |
