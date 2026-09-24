# Calibration against closed cases

Replayed 49 closed cases (0 skipped: trigger transaction not found). The case under test and every case opened after it were hidden from the agent.

## Pattern agreement

| Analyst pattern | Cases | Agent agreed | Recall | Most common agent answer |
|---|---|---|---|---|
| account_takeover | 7 | 4 | 57% | account_takeover |
| card_not_present_fraud | 7 | 2 | 29% | undocumented |
| card_not_present_new_device | 7 | 2 | 29% | undocumented |
| card_testing | 7 | 5 | 71% | card_testing |
| none | 7 | 1 | 14% | undocumented |
| out_of_region_use | 7 | 3 | 43% | out_of_region_use |
| undocumented | 7 | 2 | 29% | card_not_present_new_device |

| Agent pattern | Times predicted | Precision |
|---|---|---|
| account_takeover | 7 | 57% |
| card_not_present_fraud | 5 | 40% |
| card_not_present_new_device | 7 | 29% |
| card_testing | 5 | 100% |
| none | 7 | 14% |
| out_of_region_use | 4 | 75% |
| undocumented | 14 | 14% |

## Verdict agreement

| Analyst outcome | Agent: fraud | Agent: uncertain | Agent: legitimate |
|---|---|---|---|
| fraud | 0 | 40 | 2 |
| not fraud | 0 | 7 | 0 |

Decided cases: 2; correct among decided: 0%.
