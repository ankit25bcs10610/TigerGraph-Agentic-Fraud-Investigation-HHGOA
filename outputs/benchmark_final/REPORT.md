# Benchmark run

Source: `tigergraph-mcp`. Cases: 20. Valid and written to the graph: 20. Valid but waiting for a graph write: 0. Needing review: 0.

| Case | Pattern | Verdict | P(fraud) | Exposure | Evidence requested (assumed) | Final actions | SAR | In graph | Issue |
|---|---|---|---|---|---|---|---|---|---|
| HHG-001 | none | legitimate | 0.09 | $0.00 | none | none | no | yes |  |
| HHG-002 | none | uncertain | 0.27 | $292.36 | customer_validation=no_reply, step_up_auth=not_completed | VERIFY_WITH_CUSTOMER (auto), MONITOR_CARD (auto), DECLINE_TRANSACTION (L1) | no | yes |  |
| HHG-003 | none | fraud | 0.36 | $49.00 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-004 | card_not_present_fraud | fraud | 0.79 | $221.19 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-005 | none | legitimate | 0.13 | $0.00 | none | VERIFY_WITH_CUSTOMER (auto) | no | yes |  |
| HHG-006 | none | fraud | 0.49 | $482.12 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-007 | none | legitimate | 0.13 | $0.00 | none | none | no | yes |  |
| HHG-008 | none | fraud | 0.36 | $55.68 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-009 | none | fraud | 0.34 | $30.02 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-010 | none | uncertain | 0.34 | $1,000.03 | customer_validation=no_reply, step_up_auth=not_completed | MONITOR_CARD (auto), DECLINE_TRANSACTION (L1), ESCALATE_TO_ANALYST (auto) | no | yes |  |
| HHG-011 | card_testing | fraud | 0.89 | $2,586.86 | none | BLOCK_CARD (L2), CREATE_CASE (auto), FILE_REPORT (L2), DECLINE_TRANSACTION (L1), STEP_UP_AUTH (auto), MONITOR_CONNECTED_CARDS (auto) | yes | yes |  |
| HHG-012 | none | legitimate | 0.08 | $0.00 | none | none | no | yes |  |
| HHG-013 | none | uncertain | 0.16 | $35.66 | customer_validation=no_reply, step_up_auth=not_completed | VERIFY_WITH_CUSTOMER (auto), MONITOR_CARD (auto), DECLINE_TRANSACTION (L1) | no | yes |  |
| HHG-014 | undocumented | uncertain | 0.35 | $111.00 | customer_validation=no_reply, step_up_auth=not_completed | MONITOR_CARD (auto), DECLINE_TRANSACTION (L1), CREATE_CASE (auto), FILE_REPORT (L2), MONITOR_CONNECTED_CARDS (auto), ESCALATE_TO_ANALYST (auto) | no | yes |  |
| HHG-015 | none | uncertain | 0.42 | $599.94 | customer_validation=no_reply, step_up_auth=not_completed | MONITOR_CARD (auto), DECLINE_TRANSACTION (L1), ESCALATE_TO_ANALYST (auto) | no | yes |  |
| HHG-016 | undocumented | fraud | 0.65 | $59.67 | none | BLOCK_CARD (L1), CREATE_CASE (auto), FILE_REPORT (L2), MONITOR_CONNECTED_CARDS (auto), ESCALATE_TO_ANALYST (auto) | yes | yes |  |
| HHG-017 | none | legitimate | 0.09 | $0.00 | none | none | no | yes |  |
| HHG-018 | none | fraud | 0.37 | $39.08 | none | BLOCK_CARD (L1), CREATE_CASE (auto) | no | yes |  |
| HHG-019 | undocumented | uncertain | 0.47 | $216.83 | customer_validation=no_reply, step_up_auth=not_completed | MONITOR_CARD (auto), DECLINE_TRANSACTION (L1), CREATE_CASE (auto), FILE_REPORT (L2), MONITOR_CONNECTED_CARDS (auto), ESCALATE_TO_ANALYST (auto) | no | yes |  |
| HHG-020 | none | legitimate | 0.13 | $0.00 | none | VERIFY_WITH_CUSTOMER (auto) | no | yes |  |
