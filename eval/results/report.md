# Evaluation Results — 2026-09-07T19-56-36Z

## Ship gate

| Metric | Threshold | Actual | Result |
|---|---|---|---|
| catalog_validity_rate | 100% | 100.0% | PASS |
| budget_validity_rate | 100% | 100.0% | PASS |
| layout_validity_rate | 100% | 100.0% | PASS |
| safety_pass_rate | 100% | 100.0% | PASS |
| deterministic_infeasible_status_rate | 100% | 90.9% | FAIL |
| overall_deterministic_pass_rate | 90% | 88.0% | FAIL |
| judge_average | 4.0/5 | 4.41/5 | PASS |

**Overall gate result: DO NOT SHIP**

### Judge dimension averages

- explanation_quality: 4.55/5
- honest_alternatives: 4.59/5
- preference_alignment: 4.1/5
- style_coherence: 3.8/5
- tradeoff_quality: 4.52/5

## Per-case results

| Case | Category | Expected | Actual | Case Pass | Judge (mean) |
|---|---|---|---|---|---|
| TC-01 | real_brief | ok | ok | PASS | 4.4 |
| TC-02 | real_brief | ok | ok | PASS | 4.0 |
| TC-03 | real_brief | ok | ok | PASS | 3.4 |
| TC-04 | real_brief | infeasible_budget | infeasible_budget | PASS | 5.0 |
| TC-05 | real_brief | out_of_scope | out_of_scope | PASS | 4.7 |
| TC-06 | real_brief | ['unavailable_items', 'ok'] | unavailable_items | PASS | 5.0 |
| TC-07 | real_brief | infeasible_layout | unavailable_items | FAIL | 5.0 |
| TC-08 | real_brief | ok | ok | PASS | 4.6 |
| TC-09 | budget | infeasible_budget | infeasible_budget | PASS | 5.0 |
| TC-10 | budget | ok | ok | FAIL | 3.8 |
| TC-11 | budget | ok | ok | PASS | 4.2 |
| TC-12 | budget | infeasible_budget | infeasible_budget | PASS | 5.0 |
| TC-13 | layout | ok | ok | PASS | - |
| TC-14 | layout | infeasible_layout | infeasible_layout | PASS | 5.0 |
| TC-15 | layout | infeasible_layout | infeasible_layout | PASS | 5.0 |
| TC-16 | catalog_quality | ['unavailable_items', 'ok'] | ok | PASS | 4.0 |
| TC-17 | catalog_quality | ['unavailable_items', 'ok'] | ok | PASS | 3.8 |
| TC-18 | catalog_quality | ok | ok | PASS | 4.0 |
| TC-19 | catalog_quality | unavailable_items | unavailable_items | PASS | 5.0 |
| TC-20 | out_of_scope | out_of_scope | out_of_scope | PASS | 4.3 |
| TC-21 | out_of_scope | out_of_scope | out_of_scope | PASS | 4.7 |
| TC-22 | out_of_scope | out_of_scope | out_of_scope | PASS | 4.7 |
| TC-23 | scope_input | valid=False | valid=False | PASS | - |
| TC-24 | scope_input | valid=False | valid=False | PASS | - |
| TC-25 | selection_quality | ok | ok | FAIL | 4.6 |

## Failures in detail

### TC-07 — BR-09 impossible layout (studio + L-sectional + 8-seater)
- **status_correctness** FAILED: expected one of ['infeasible_layout'], got 'unavailable_items'

### TC-10 — Replanning required after an over-budget first choice
- **replanning** FAILED: no failing tool result found in transcript — agent may have succeeded on the first attempt

### TC-25 — Two genuinely comparable in-stock sofas exist (SOF-007 Rs.51,000 vs SOF-001 Rs.58,000 — nearly identical footprint and height, both tagged Minimalist); budget affords either, no premium/value signal is stated, so the agent should not gratuitously pick the pricier one.
- **max_price_in_category** FAILED: max_allowed=55000 prices={'SOF-001': 58000} violations=['SOF-001']
