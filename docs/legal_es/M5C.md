# KeepMeHonest Legal ES — M5-C / Expert review and adjudication workflow

**Status: research workflow candidate; zero expert-reviewed cases at handoff.**

The M5-C software creates *blank independent reviewer assignments* only for cases that have already passed the separate M5-A source/publication/reuse attestation gate. It then checks the formal completeness of two human-authored assessments and a third-person adjudication, preserving the original case, claim/evidence digests and reviewer-submission digests. **It never writes any expert answer, legal decision, professional credential, or reuse declaration by itself.**

M5-A and M5-B are local and uncommitted. All M5 increments must remain private and uncommitted until M5-D is genuinely accepted. Do not put raw official snapshots, reviewer submissions, personal identifiers or receipts into the public Git repository.

## 1. The current operational state

- M5-A contains 36 *AI-drafted* candidate propositions, 13 source/section clusters, no human labels.
- M5-B has demonstrated a BOE and TC raw capture and deterministic offline replay in the developer environment. This is **not** external confirmation of legal authenticity, permissible reuse, or applicability.
- M5-C **cannot begin human review** until each selected case has independent *real* source/publication and rights checks, limited to `INTERNAL_EXPERT_REVIEW_ONLY`, with records produced through the M5-A `stage_pending` gate. M5-B snapshot verification is a technical prerequisite, not a replacement for this human gate.
- Zero external lawyers have been recruited/credential-verified in this delivery; zero human assessment files exist; `expert_gold_cases=0` and `legal_accuracy_measured=false` remain mandatory.

## 2. Protocol and responsibilities

**Two qualified independent legal reviewers** review a frozen proposition and hypothetical facts, identified source and full relevant material. They must not see each other's labels or rationale before submission. They independently record:

- documentary label: `EXACT_QUOTE`, `INCORRECT_QUOTE`, `SOURCE_MISSING`, `UNDETERMINED`;
- legal relation: `DIRECT_SUPPORT`, `PARTIAL_SUPPORT`, `NO_SUPPORT`, `CONTRADICTED`, `CONTEXT_DEPENDENT`, `INSUFFICIENT_EVIDENCE`;
- whether facts are available and temporal applicability reviewed;
- reason and exact evidence locator.

A **third person**, different from both reviewers for that case, adjudicates independently recorded differences with a reasoned decision. Do not mark `DIRECT_SUPPORT` or `CONTRADICTED` where facts are absent; the M4 validator blocks this. Reviewers must consider the *full* legal source in context: exceptions, transitional rules, competence, posture, later jurisprudence, relevant facts and temporal scope. Absence of evidence is not proof of the opposite.

Credential checks, actual independence, provenance authenticity, rights and reviewer conflict-of-interest screening are **external human governance tasks**; comparing self-declared reviewer identifiers is not proof of independent people. A hash shows content integrity relative to a local snapshot, not a cryptographic signature or publisher authenticity.

## 3. CLI: plan (works today, no network)

From the fork root (after applying the M5-C patch over local M5-A/B):

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_expert_review plan \
  --candidates evals/legal_es/m5/pilot_candidates.json
```

Expect `candidates=36`, `source_section_clusters=13`, `reviewable_now=0`, `expert_gold_cases=0`, `legal_accuracy_measured=false`. **Do not advance to the next command yet** without real human source-and-rights review.

## 4. CLI: prepare private assignments (only when the gate is genuinely met)

M5-A `stage_pending` first generates `m4_pending_reviews.json` and `m5_capture_receipts.json` from real reviewed material and the human `capture_attestations` ledger. These files *do not exist merely because M5-B replay passed*. Use a new private output folder outside the Git repository, owned by the operator with restrictive permissions:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_expert_review prepare \
  --candidates evals/legal_es/m5/pilot_candidates.json \
  --pending "$HOME/Spoel-Work/KMH-private-review/staged/m4_pending_reviews.json" \
  --receipts "$HOME/Spoel-Work/KMH-private-review/staged/m5_capture_receipts.json" \
  --output-dir "$HOME/Spoel-Work/KMH-private-review/packet-001"
```

If a prerequisite is missing, expect exit code `2`; **never construct fictional attestations to bypass the gate**. The output `packet.json` contains the frozen proposition, hypothetical facts, official locator and hashes (not raw source text). The `reviewer_a/assignment.json` and `reviewer_b/assignment.json` files are separate **blank** forms. The adjudication template is blank. Distribution to reviewers needs a lawful, access-controlled channel; **only distribute the assigned reviewer form plus authorized supporting evidence**, never other reviewers' submissions. The packet remains private.

## 5. CLI: check independent submissions and adjudication (later)

After each real expert independently completes their assigned JSON form and a **different** adjudicator considers the evidence and decisions, validate the procedural structure:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_expert_review validate \
  --packet "$HOME/Spoel-Work/KMH-private-review/packet-001/packet.json" \
  --reviewer-a "$HOME/Spoel-Work/KMH-private-review/review_a_completed.json" \
  --reviewer-b "$HOME/Spoel-Work/KMH-private-review/review_b_completed.json" \
  --adjudication "$HOME/Spoel-Work/KMH-private-review/adjudication_completed.json" \
  --output-dir "$HOME/Spoel-Work/KMH-private-review/validated-001"
```

This validates the exact M4 adjudication-form schema, hashes, case binding, label vocabulary, reviewer separation by submitted IDs, reason lengths and chronological ordering. Output is:

- `structural_audit.json`: packet, review, adjudication and draft hashes; cases and disagreements, `expert_gold_cases=0`.
- `m4_candidate_DO_NOT_PUBLISH.json`: **structurally valid candidate** M4 records containing the submitted labels. The underlying M4 `status=ADJUDICATED` is a form state only; it does not constitute a real *gold standard*, verified reviewer independence or an audited legal finding.

M5-D must separately audit source authenticity, reuse and disclosure rights, real reviewer credentials, independence, actual decisions and disagreements; agree on a held-out test design; and seal an approved set. Without these steps, **do not call the corpus adjudicated gold or use it to calculate legal accuracy**.

## 6. Specific threat controls and remaining gaps

- Read-only offline workflow. No model service, legal analysis engine, external URL, CENDOJ or case facts are transmitted to a network service by M5-C.
- Exact case/question, source identifiers, original text/evidence SHA-256 and source-attestation receipts are bound into packet digests; submissions are bound to a packet and case digest. Tampering leads to explicit rejection *unless an attacker replaces all associated hashes*. External signed receipts/independent custody remain M5-D work.
- Reviewer roles are separate files; the program cannot stop reviewers from sharing decisions outside the system or impersonating different identities. Organizational process is required.
- Outputs contain lawyer rationale and potentially identifying reviewer IDs. Files are created mode `0600` in output directories mode `0700`; keep them out of version control and unapproved cloud sync. The candidate material is fictional but some official judgments can include personal data.
- M5-C is evaluation/annotation infrastructure only. `DIRECT_SUPPORT` and other submitted *human* labels are not generated predictions of KeepMeHonest and are not independently verified by the program.
- Current M5-A staging produces case-specific text files while M5-B produces a frozen raw/section bundle. **The operator must manually map and re-check these materials under approved custody; this linkage is not automatic or independently authenticated.** M5-D must inspect that chain.
- The 36 candidates are generated/clustered, not random or an independent holdout; their 13 clusters mean statistical dependence. Do not report a product precision/recall estimate from them without an appropriate evaluation design.

## 7. Engineering acceptance and publication rule

1. Apply patch with `git apply --check` over the **local uncommitted M5-A + M5-B** changes.
2. Run `PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py' -v` on the full fork (expected **229 tests**, 0 skip).
3. Run the original Core suite `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` (expected **205 tests**, all pass).
4. Run plan. Confirm 36 candidates, zero ready-for-review, zero expert gold.
5. Inspect `git status --short`/`git diff --check`; no raw captured files or human identifiers staged.
6. Accept **M5-C software workflow** only. **Do not claim the human review is completed**; do not commit or push M5-A/B/C until M5-D is genuinely accepted and private data is excluded.

**Current delivery verdict is CANDIDATE_EXPERT_WORKFLOW, not ACCEPT_LEGAL_GOLD.**
