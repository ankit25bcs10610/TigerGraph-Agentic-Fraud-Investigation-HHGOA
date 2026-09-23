# Sample investigation data

Synthetic, clearly labelled data (every ID starts with `SMP-`) for exercising the
full analyst workflow locally: evidence, transactions, evidence requests,
recommended actions, L1/L2 approvals, SAR drafting and the audit ledger.

None of this is benchmark data, and nothing loads it automatically. Start the
API with it explicitly:

```bash
CASE_PACK_PATH=data/sample/case_pack.csv \
TRANSACTIONS_PATH=data/sample/transactions.csv \
CLOSED_CASES_PATH=data/sample/closed_cases_history.csv \
FRONTEND_ORIGINS=http://127.0.0.1:3001 \
python -m uvicorn backend.main:app --port 8000
```

The outcomes below are not scripted. The local investigation engine
(`backend/local_engine.py`) runs the repository's deterministic pattern
detectors, fraud-probability weights, stopping rules, policy R1-R10, approval
routing and SAR rules over these rows, so changing a row changes the result.

| Case | Scenario | What to try |
|---|---|---|
| SMP-001 | Three sub-$5 online authorisations, then a $389.99 purchase on a new device | Answer the customer request with **Denied**: the card block joins the L1 decline for approval |
| SMP-002 | Online burst on a new device that two other customers also used; one of them has a confirmed fraud case | Strong fraud straight away: the SAR must be filed, which needs L2 approval |
| SMP-003 | Card-present spending in a new region while home-region spending continues | Uncertain and escalated. Answer **Confirmed** to close it as legitimate travel |
| SMP-004 | Mixed-channel activity with a new device, an anonymous proxy and a match-status change | Answer **Denied**: exposure over $2,500 routes the card block to L2 |
| SMP-005 | A routine purchase that matches the card's history and known device | Closes as legitimate with no action needed |
| SMP-006 | Customer report of a $2,940 purchase at the end of an online burst | Customer denial already settles it: block card (L2) and file the SAR (L2) |
