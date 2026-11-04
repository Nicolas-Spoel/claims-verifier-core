# M5-D — Technical seal of a non-adjudicated Spanish-law candidate corpus

**Scope deliberately revised:** M5-D seals an *unadjudicated research inventory*. There are **zero legal expert gold cases**, **zero rights clearances**, and **no measurement of legal-support accuracy**. Software acceptance does **not** mean completion of the originally proposed expert-adjudicated M5-D. This technical release does not change the legal verifier, its abstention logic or the source clients.

## Why this is useful without legal reviewers

The owner wishes to keep KeepMeHonest free and cannot recruit lawyers at present. Do **not** replace expert judgments with LLM judgments or the software developer's judgments. Instead: freeze the current public-reference candidate catalogue, prove selected M5-B raw-response snapshots still match their digests, and publish only program code, **AI-drafted** hypothetical candidate metadata, tests and methodology, where permitted. The source text and private hashes/receipts remain outside version control. Later expert evaluation remains an independent milestone.

A verified SHA-256 **only** establishes equality with previously stored bytes; neither official provenance, legality of reuse, legal temporal applicability nor legal accuracy has been established.

## Existing scope and prerequisites

- M5-A: 36 cases, five legal areas, 13 source/section clusters, 33 date-scoped fetch tasks; candidates are AI drafts, not an independent sample.
- M5-B: a limited read-only capture and offline raw replay, **not** permission to redistribute original source files.
- M5-C: blank reviewer workflow, 0 reviewers recruited, no labels. Do not fill reviewer fields with invented identities or fictitious judgments.
- Two previously captured **local** directories, outside Git: `boe-001` (`PUB-M5-001`) and `tc-032` (`PUB-M5-032`). The `--seal` workflow verifies each whole directory with M5-B before sealing anything.

## Commands on the Mac

From the repo with **M5-A/B/C already applied locally** and after applying only the M5-D patch:

```bash
cd ~/Spoel-Work/claims-verifier-core
git apply --check ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M5D.patch
git apply ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M5D.patch
git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Plan, no network:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_seal plan \
  --candidates evals/legal_es/m5/pilot_candidates.json
```

Create a **new private output directory**, which must not exist beforehand (do not put it in the repository):

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_seal seal \
  --candidates evals/legal_es/m5/pilot_candidates.json \
  --capture-dir "$HOME/Spoel-Work/KMH-private-captures/boe-001" \
  --capture-dir "$HOME/Spoel-Work/KMH-private-captures/tc-032" \
  --output-dir "$HOME/Spoel-Work/KMH-private-captures/m5d-freeze-01"
```

Verify again offline:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m5_seal verify \
  --candidates evals/legal_es/m5/pilot_candidates.json \
  --capture-dir "$HOME/Spoel-Work/KMH-private-captures/boe-001" \
  --capture-dir "$HOME/Spoel-Work/KMH-private-captures/tc-032" \
  --seal-file "$HOME/Spoel-Work/KMH-private-captures/m5d-freeze-01/technical_seal_PRIVATE.json"
```

Expected for **these two pilot captures**:

- `mode=OFFLINE_M5D_TECHNICAL_SEAL_VERIFIED`; `candidate_cases=36`.
- `technically_replayed_tasks=2`, `captured_cases=2`, `uncaptured_cases=34`.
- `expert_gold_cases=0`, `rights_cleared=0`, `legal_accuracy_measured=false`.
- A `seal_sha256` local hash; do not describe it as a signature or external certificate.

If either capture fails, **stop** and preserve errors; no mass re-fetches or reconstruction of labels. `m5_seal` performs no HTTP requests, cannot mint legal expert labels and cannot elevate M5-B `rights_reviewed` or `official_publication_checked` flags.

## Publication constraint

After all suites and the local private replay pass, the **software/inventory can be published** in a single commit containing only `src/`, `tests/`, `docs/`, `examples/`, and explicitly reviewed `evals/legal_es/m5/pilot_candidates.json`. Do not stage anything from `KMH-private-captures`, completed/blank reviewer identity records, private manifests, local reports, downloaded BOE/TC contents, or source text, without a separate authorization and reuse review. Do **not** claim legal accuracy, official provenance authenticity, source reuse clearance, or a completed legal gold-standard corpus.

The remaining expert-adjudicated benchmark is **pending indefinitely** until authentic independent reviewers are available; no fictional substitute. The user can release an experimental documentary evidence tool with conspicuous limitations and safety/privacy checks, but it is not approved for confidential client matters or production legal opinions.

## Safety and reproducibility

The technical seal is a **local** JSON manifest with content digests and public case/source metadata, no raw document bytes and no absolute local file paths. It is stored under a newly created 0700 directory with a 0600 JSON file. Its self-hash detects accidental tampering, not intentional re-signing by an attacker. To reproduce, an auditor must possess the independently retained raw snapshots and the exact public candidate corpus.

Rights questions cannot be decided by an API reply or by a `rights_cleared=0`/`1` flag. BOE consolidated texts are informational; the BOE API states that reuse is subject to its conditions. The TC source must be checked separately. Further publication of source texts, extensive extracts or derived databases requires the appropriate review.
