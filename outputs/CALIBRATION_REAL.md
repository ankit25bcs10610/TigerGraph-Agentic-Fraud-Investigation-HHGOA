# Calibration against closed cases

Replayed 49 closed cases (0 skipped: trigger transaction not found). The case under test and every case opened after it were hidden from the agent.

## Pattern agreement

| Analyst pattern | Cases | Agent agreed | Recall | Most common agent answer |
|---|---|---|---|---|
| account_takeover | 7 | 0 | 0% | undocumented |
| card_not_present_fraud | 7 | 1 | 14% | undocumented |
| card_not_present_new_device | 7 | 1 | 14% | undocumented |
| card_testing | 7 | 0 | 0% | undocumented |
| none | 7 | 0 | 0% | undocumented |
| out_of_region_use | 7 | 3 | 43% | undocumented |
| undocumented | 7 | 2 | 29% | card_not_present_new_device |

| Agent pattern | Times predicted | Precision |
|---|---|---|
| account_takeover | 2 | 0% |
| card_not_present_fraud | 2 | 50% |
| card_not_present_new_device | 5 | 20% |
| none | 3 | 0% |
| out_of_region_use | 3 | 100% |
| undocumented | 34 | 6% |

## Verdict agreement

| Analyst outcome | Agent: fraud | Agent: uncertain | Agent: legitimate |
|---|---|---|---|
| fraud | 0 | 41 | 1 |
| not fraud | 0 | 7 | 0 |

Decided cases: 1; correct among decided: 0%.
