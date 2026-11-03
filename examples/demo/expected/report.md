# Claim verification report

Engine `claims-verifier 0.1.1` · judge `lexical-v2-guarded` · corpus `afd260b992f0` (5 documents, 22 passages)

## Summary

| Verdict | Claims |
|---|---|
| ✅ Supported | 3 |
| 🟡 Partially supported | 4 |
| ❌ Contradicted | 2 |
| ⚠️ Conflicting sources | 1 |
| ⏸️ Inconclusive (abstention) | 1 |
| ❔ Not enough evidence | 1 |
| **Total** | **12** |

- Need review: **9** of 12
- Claims with related evidence: 92% (does not imply that the corpus is complete)
- Unverifiable segments skipped: 3 (with factual content NOT verified: **0**)
- Documents not cited: none

## Claims

### C1 · ✅ Supported (heuristic score 0.90, not a probability)

> Nimbus Logística recorded revenue of S/ 48.6 million in 2023.

Supported by 1 passage\(s\) in 1 document\(s\).

**Uncertainty and limitations:**
- `SINGLE_SOURCE` — supported only by annual\_report\_2023

- **supports** — annual\_report\_2023.md line 13 (annual\_report\_2023:p3, 2024-02-15; relevance 1.00): “Nimbus Logística's revenue reached S/ 48.6 million in 2023, which represents growth of 12% compared with 2022.” — `NUMBER_MATCH` S/ 48.6 million ≈ S/ 48.6 million
_Examined: 7 passages from annual\_report\_2023, press\_release\_q1\_2024, sustainability\_policy._

### C2 · ❌ Contradicted (heuristic score 0.95, not a probability)

> Revenue grew by 15% compared with 2022.

The evidence contradicts the claim \(claim 15% vs evidence 12%\).

- **contradicts** — annual\_report\_2023.md line 13 (annual\_report\_2023:p3, 2024-02-15; relevance 1.00): “Nimbus Logística's revenue reached S/ 48.6 million in 2023, which represents growth of 12% compared with 2022.” — `NUMBER_MISMATCH` claim 15% vs evidence 12%
_Examined: 5 passages from annual\_report\_2023, fleet\_audit\_2024, press\_release\_q1\_2024._

### C3 · ✅ Supported (heuristic score 0.90, not a probability)

> The company opened a distribution center in Arequipa in March 2023.

Supported by 1 passage\(s\) in 1 document\(s\).

**Uncertainty and limitations:**
- `SINGLE_SOURCE` — supported only by annual\_report\_2023

- **supports** — annual\_report\_2023.md line 19 (annual\_report\_2023:p6, 2024-02-15; relevance 1.00): “In March 2023 the company opened a distribution center in Arequipa.” — term match
_Examined: 2 passages from annual\_report\_2023, press\_release\_q1\_2024._

### C4 · 🟡 Partially supported (heuristic score 0.70, not a probability)

> The company has 1,240 employees.

The evidence supports only part of the claim, or supports it with less certainty.

**Uncertainty and limitations:**
- `STATE_NOT_CURRENT` — the claim describes a current situation; the evidence, a past event or state

- **partially supports** — annual\_report\_2023.md line 21 (annual\_report\_2023:p8, 2024-02-15; relevance 1.00): “The workforce at year-end was 1,240 employees.” — `NUMBER_MATCH` 1,240 ≈ 1,240, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state
- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p2, 2023-12-05; relevance 1.00): “78% of employees declared themselves satisfied with the workplace climate.” — `NUMBER_NOT_FOUND` 1,240 does not appear in this passage, `REPORTED_SPEECH` the evidence attributes the information to a third party \(“declared”\); the claim states it as fact, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: 78% of employees, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state
- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p3, 2023-12-05; relevance 1.00): “Some employees pointed out the need for more training.” — `NUMBER_NOT_FOUND` 1,240 does not appear in this passage, `REPORTED_SPEECH` the evidence attributes the information to a third party \(“pointed”\); the claim states it as fact, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: some, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state
- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p1, 2023-12-05; relevance 1.00): “The annual workplace climate survey achieved a participation rate of 91% of the workforce.” — `NUMBER_NOT_FOUND` 1,240 does not appear in this passage, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: 91% of the workforce, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state
_Examined: 4 passages from annual\_report\_2023, workplace\_survey\_2023._

### C5 · ⚠️ Conflicting sources

> The current fleet is 340 trucks.

The sources disagree: some support the claim and others contradict it. Requires human review.

**Uncertainty and limitations:**
- `CONFLICTING_SOURCES` — for: press\_release\_q1\_2024; against: annual\_report\_2023; most recent source: press\_release\_q1\_2024 \(2024-05-10, for\)

- **contradicts** — annual\_report\_2023.md line 20 (annual\_report\_2023:p7, 2024-02-15; relevance 1.00): “At the end of 2023 the fleet was 310 trucks.” — `NUMBER_MISMATCH` claim 340 vs evidence 310
_Examined: 5 passages from annual\_report\_2023, fleet\_audit\_2024, press\_release\_q1\_2024, sustainability\_policy._

### C6 · 🟡 Partially supported (heuristic score 0.70, not a probability)

> The new distribution center in Trujillo will open in 2025.

The evidence supports only part of the claim, or supports it with less certainty.

**Uncertainty and limitations:**
- `CERTAINTY_OVERSTATED` — the evidence is tentative, conditional or projected; the claim states it with more certainty
- `CLAIM_HEDGED` — the claim itself is tentative or opinion-based

- **partially supports** — press\_release\_q1\_2024.md line 13 (press\_release\_q1\_2024:p4, 2024-05-10; relevance 1.00): “The company is evaluating a new distribution center in Trujillo, which could open in 2025 subject to obtaining municipal permits.” — `HEDGED_EVIDENCE` the evidence is tentative, conditional or projected; the claim states it with more certainty
_Examined: 3 passages from annual\_report\_2023, press\_release\_q1\_2024._

### C7 · 🟡 Partially supported (heuristic score 0.70, not a probability)

> All employees are satisfied with the workplace climate.

The evidence supports only part of the claim, or supports it with less certainty.

**Uncertainty and limitations:**
- `REPORTED_SPEECH` — the evidence attributes the information to a third party \(“declared”\); the claim states it as fact
- `SCOPE_OPERATOR` — the evidence restricts or qualifies the scope: 78% of employees
- `STATE_NOT_CURRENT` — the claim describes a current situation; the evidence, a past event or state
- `QUANTIFIER_OVERSTATED` — the claim generalizes; the evidence covers only part

- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p2, 2023-12-05; relevance 1.00): “78% of employees declared themselves satisfied with the workplace climate.” — `REPORTED_SPEECH` the evidence attributes the information to a third party \(“declared”\); the claim states it as fact, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: 78% of employees, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state, `QUANTIFIER_OVERSTATED` the claim generalizes; the evidence covers only part
- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p1, 2023-12-05; relevance 0.69): “The annual workplace climate survey achieved a participation rate of 91% of the workforce.” — `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: 91% of the workforce, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state, `QUANTIFIER_OVERSTATED` the claim generalizes; the evidence covers only part, `MISSING_TERMS` satis
- **partially supports** — workplace\_survey\_2023.json#0 line 1 (workplace\_survey\_2023:p3, 2023-12-05; relevance 0.59): “Some employees pointed out the need for more training.” — `REPORTED_SPEECH` the evidence attributes the information to a third party \(“pointed”\); the claim states it as fact, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: some, `STATE_NOT_CURRENT` the claim describes a current situation; the evidence, a past event or state, `QUANTIFIER_OVERSTATED` the claim generalizes; the evidence covers only part
_Examined: 4 passages from annual\_report\_2023, workplace\_survey\_2023._

### C8 · ⏸️ Inconclusive (abstention)

> The accident rate did not decrease in 2024.

There is related evidence, but it does not allow a confident decision \(same change with opposite polarity; the evidence restricts or qualifies the scope: half of 2024; the evidence covers only part of the period: first half\). Requires human review.

**Uncertainty and limitations:**
- `NEGATION_MISMATCH` — same change with opposite polarity
- `SCOPE_OPERATOR` — the evidence restricts or qualifies the scope: half of 2024
- `PERIOD_SUBSET` — the evidence covers only part of the period: first half

- **related, does not decide** — fleet\_audit\_2024.md line 11 (fleet\_audit\_2024:p2, 2024-06-30; relevance 1.00): “In the first half of 2024, the accident rate decreased by 18% compared with the same period of 2023.” — `NEGATION_MISMATCH` same change with opposite polarity, `SCOPE_OPERATOR` the evidence restricts or qualifies the scope: half of 2024, `PERIOD_SUBSET` the evidence covers only part of the period: first half
_Examined: 4 passages from annual\_report\_2023, fleet\_audit\_2024, sustainability\_policy, workplace\_survey\_2023._

### C9 · ❌ Contradicted (heuristic score 0.85, not a probability)

> The net margin increased to 6.8% in 2023.

The evidence contradicts the claim \(the claim states an increase, the evidence states a decrease\).

- **contradicts** — annual\_report\_2023.md line 14 (annual\_report\_2023:p4, 2024-02-15; relevance 1.00): “The net margin decreased to 6.8% in 2023, compared with 7.4% recorded in 2022.” — `DIRECTION_MISMATCH` the claim states an increase, the evidence states a decrease
_Examined: 5 passages from annual\_report\_2023, press\_release\_q1\_2024._

### C10 · ✅ Supported (heuristic score 0.90, not a probability)

> The general manager is Lucía Ramos.

Supported by 1 passage\(s\) in 1 document\(s\).

**Uncertainty and limitations:**
- `SINGLE_SOURCE` — supported only by annual\_report\_2023

- **supports** — annual\_report\_2023.md line 25 (annual\_report\_2023:p9, 2024-02-15; relevance 1.00): “The general manager of Nimbus Logística is Lucía Ramos, who took office in January 2021.” — term match
_Examined: 2 passages from annual\_report\_2023._

### C11 · ❔ Not enough evidence

> Nimbus Logística has been listed on the Lima Stock Exchange since 2019.

No evidence was found in the corpus that supports or refutes the claim.

**Uncertainty and limitations:**
- `OUT_OF_CORPUS_SCOPE` — terms absent from the corpus: list, stock, excha
- `NO_EVIDENCE` — best term coverage 0.21

_Examined: 8 passages from annual\_report\_2023, press\_release\_q1\_2024, sustainability\_policy._

### C12 · 🟡 Partially supported (heuristic score 0.70, not a probability)

> Nimbus Logística reduced its carbon emissions by 30%.

The evidence supports only part of the claim, or supports it with less certainty.

**Uncertainty and limitations:**
- `NONFINITE_PREDICATE` — the action appears only as an intention, accusation or possibility \(“reduce”\)
- `CERTAINTY_OVERSTATED` — the evidence is tentative, conditional or projected; the claim states it with more certainty

- **partially supports** — sustainability\_policy.txt line 3 (sustainability\_policy:p2; relevance 1.00): “Nimbus Logística plans to reduce its carbon emissions by 30% by 2030 through the electrification of its fleet.” — `NUMBER_MATCH` 30% ≈ 30%, `NONFINITE_PREDICATE` the action appears only as an intention, accusation or possibility \(“reduce”\), `HEDGED_EVIDENCE` the evidence is tentative, conditional or projected; the claim states it with more certainty
_Examined: 8 passages from annual\_report\_2023, fleet\_audit\_2024, press\_release\_q1\_2024, sustainability\_policy._

## Skipped segments

- `heading` — Summary of Nimbus Logística
- `question` — Would you like more details?
- `conversational` — I hope this information is useful to you.

## Corpus provenance and coverage

- Received: 5 · examined: 5 · excluded: 0
- Corpus completeness: **unverifiable (no expected inventory was provided)**
- Search: Bm25Index, 8 passages per claim; “no evidence” refers to what was examined, not to the whole corpus

## Verifier limitations

- Lexical verification with safety guards: it compares terms, figures, dates, negation, direction, modality, stage \(request vs outcome\), entity roles and population scope using lexicons and surface rules; it does not understand meaning. When it sees risk signals it abstains \(INCONCLUSIVE, PARTIALLY\_SUPPORTED\) instead of deciding.
- Only the documents received are considered, and the search examines the most relevant passages for each claim: 'not enough evidence' does not mean that the claim is false. Corpus completeness can only be verified against an expected inventory.
- The score is heuristic and uncalibrated: it is not the probability that the claim is true.
- Evidence is assessed sentence by sentence \(with the title, heading and previous sentence as context\); facts spread over several sentences or expressed through deep paraphrase are usually left undecided.
- The lexicons \(synonyms, stages, modality, populations\) cover administrative and business English and Spanish; outside that register, abstention increases.
