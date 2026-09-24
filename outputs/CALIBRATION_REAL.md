# Calibration against closed cases

Replayed 49 closed cases (0 skipped: trigger transaction not found). The case under test and every case opened after it were hidden from the agent.

## Pattern agreement

| Analyst pattern | Cases | Agent agreed | Recall | Most common agent answer |
|---|---|---|---|---|
| account_takeover | 7 | 1 | 14% | none |
| card_not_present_fraud | 7 | 0 | 0% | undocumented |
| card_not_present_new_device | 7 | 2 | 29% | undocumented |
| card_testing | 7 | 0 | 0% | undocumented |
| none | 7 | 0 | 0% | card_not_present_new_device |
| out_of_region_use | 7 | 3 | 43% | out_of_region_use |
| undocumented | 7 | 1 | 14% | card_not_present_new_device |

| Agent pattern | Times predicted | Precision |
|---|---|---|
| account_takeover | 9 | 11% |
| card_not_present_fraud | 3 | 0% |
| card_not_present_new_device | 7 | 29% |
| none | 11 | 0% |
| out_of_region_use | 4 | 75% |
| undocumented | 15 | 7% |

## Verdict agreement

| Analyst outcome | Agent: fraud | Agent: uncertain | Agent: legitimate |
|---|---|---|---|
| fraud | 0 | 38 | 4 |
| not fraud | 0 | 7 | 0 |

Decided cases: 4; correct among decided: 0%.
