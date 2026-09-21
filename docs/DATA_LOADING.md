# TigerGraph data loading

This loading implementation prepares null-safe TSV files and provides one TigerGraph loading job. It loads only transactions, identity/device data, and closed-case history. case_pack.csv is read by validation only and is never emitted or loaded as historical truth.

## Files

- scripts/prepare_graph_data.py reads transactions.csv, identity.csv, and closed_cases_history.csv and writes normalized TSV files plus manifest.json.
- scripts/validate_data.py checks source joins, case references, prepared-file endpoints, and reports unresolved card-label mappings.
- tigergraph/loading_jobs.gsql defines the vertex and edge loads for graph FraudInvestigation.
- case_pack.csv is deliberately absent from the loading job.

The prepared files use tab delimiters, a header row, and the null token \N. Empty source values are converted to \N. The loader never uses public fraud labels; risk_score remains a Transaction input property.

## Card construction

The dataset's visible card label format is customer_id-Kn. transactions.csv has no literal card_id, so the loader constructs a deterministic ordinal from the full raw card1-card6 fingerprint:

1. Collect each customer's distinct non-empty card1-card6 tuples.
2. Sort those tuples canonically.
3. Assign K1, K2, and so on within that customer.
4. Use customer_id-K<ordinal> as the Card vertex ID.

Historical case card labels are also materialized as Card vertices so ClosedCase ON_CARD and CONNECTED_TO references remain loadable. Because the supplied data does not publish the mapping from a case label to a raw transaction fingerprint, validation reports card-label mapping mismatches rather than silently treating this ordinal as ground truth. The same deterministic construction is used consistently for transaction MADE, OWNS, and NEXT edges.

## DeviceProfile construction

Identity rows join transactions on TransactionID. A DeviceProfile is emitted only when at least one of these actual identity fields is present:

- DeviceInfo
- DeviceType
- id_30, stored as os
- id_31, stored as browser
- id_33, stored as screen
- id_15, stored as device_status
- id_23, stored as proxy_type
- id_34, stored as match_status

The profile ID is DP- plus a SHA-256 digest of the canonical ordered values. No absent source field is invented, and missing values do not become the string "None".

## Sample load

The sample mode uses the first N transaction rows and related identity/case records. It does not load case_pack.csv.

Prepare 1,000 transactions:

    python3 scripts/prepare_graph_data.py \
      --data-dir /path/to/data \
      --output-dir build/graph_data_sample \
      --sample 1000

Validate the sample:

    python3 scripts/validate_data.py \
      --data-dir /path/to/data \
      --prepared-dir build/graph_data_sample \
      --sample 1000

Install the schema and loading job in TigerGraph:

    gsql tigergraph/schema.gsql
    gsql tigergraph/loading_jobs.gsql

Run the loading job using the generated filenames. The exact gsql command wrapper varies by TigerGraph deployment; the job expects these filename bindings:

    RUN LOADING JOB load_fraud_data USING
      f_customer="build/graph_data_sample/customer.tsv",
      f_card="build/graph_data_sample/card.tsv",
      f_transaction="build/graph_data_sample/transaction.tsv",
      f_device_profile="build/graph_data_sample/device_profile.tsv",
      f_email_domain="build/graph_data_sample/email_domain.tsv",
      f_billing_region="build/graph_data_sample/billing_region.tsv",
      f_closed_case="build/graph_data_sample/closed_case.tsv",
      f_owns="build/graph_data_sample/owns.tsv",
      f_made="build/graph_data_sample/made.tsv",
      f_from_device="build/graph_data_sample/from_device.tsv",
      f_purchaser_email="build/graph_data_sample/purchaser_email.tsv",
      f_billed_in="build/graph_data_sample/billed_in.tsv",
      f_next="build/graph_data_sample/next.tsv",
      f_involves="build/graph_data_sample/involves.tsv",
      f_on_card="build/graph_data_sample/on_card.tsv",
      f_connected_to="build/graph_data_sample/connected_to.tsv";

For a remote TigerGraph deployment, place or upload the prepared files where the loading service can read them and use the deployment's normal filename binding mechanism.

## Full load

Prepare all source transactions, identity rows, and closed cases:

    python3 scripts/prepare_graph_data.py \
      --data-dir /path/to/data \
      --output-dir build/graph_data \
      --full

Validate:

    python3 scripts/validate_data.py \
      --data-dir /path/to/data \
      --prepared-dir build/graph_data \
      --full

Then run the same loading job with the full build/graph_data paths. case_pack.csv remains excluded.

## Observed full-data counts

The full preparation and validation were run against the supplied files. Expected prepared counts are:

| Item | Count |
|---|---:|
| Transaction vertices | 590,742 |
| Customer vertices | 13,553 |
| Transaction-derived card fingerprints | 14,893 |
| Card vertices including historical case labels | 14,893 |
| OWNS edges | 14,893 |
| MADE edges | 590,742 |
| Identity rows joined | 144,432 |
| DeviceProfile vertices | 17,402 |
| FROM_DEVICE edges | 141,180 |
| EmailDomain vertices | 60 |
| PURCHASER_EMAIL edges | 633,715 |

The implementation emits one edge per non-empty P_emaildomain or R_emaildomain value, retaining the source role as the edge attribute.

The other observed full-data counts are:

| Edge / vertex | Count |
|---|---:|
| BillingRegion vertices | 332 |
| BILLED_IN edges | 525,003 |
| NEXT edges | 575,849 |
| ClosedCase vertices | 5,565 |
| INVOLVES edges | 14,955 |
| ON_CARD edges | 5,565 |
| CONNECTED_TO edges | 92 |

The manifest.json file contains exact counts for every emitted file.

## Validation checks

A passing full validation requires:

- 590,742 unique TransactionID values and no duplicate transaction rows.
- 144,432 unique identity TransactionID values, all present in transactions.
- 5,565 closed cases with 14,955 valid transaction references.
- Every closed-case txn_ids count matches n_txns.
- No closed-case transaction/customer mismatches.
- All 20 case-pack flagged transactions exist and match their customer_id; case_pack remains unloaded.
- Every prepared edge endpoint exists in its target vertex set.
- No missing prepared output files.

Sample mode intentionally reports references outside the selected transaction window as out-of-scope rather than failing.

## Unresolved references and limitations

- The source has no direct transaction card_id column. The constructed K ordinal is deterministic but cannot be proven to match every historical case label. The validator reports closed-case card-label mapping mismatches in the source summary; these are expected unresolved references, not silently corrected data.
- On the inspected full dataset, validation found 1,149 closed-case transaction/card-label mismatches across 274 cases under this deterministic ordinal construction. The graph still loads the case-label vertices and relationships, but those mismatches must be resolved before treating case card labels as transaction-card truth.
- A historical case label may still exist as a Card vertex, so ON_CARD and CONNECTED_TO endpoints load safely even when its transaction fingerprint mapping is unresolved.
- A NEXT edge is emitted only for transactions with a non-empty constructed card fingerprint.
- Identity data is partial and sparse. No FROM_DEVICE edge is created for transactions without a usable identity profile.
- case_pack.csv is benchmark input only and is not loaded into Customer, Card, Transaction, or ClosedCase vertices.
