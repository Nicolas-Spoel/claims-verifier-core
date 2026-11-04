# KeepMeHonest Spanish Legal Edition — M7-B / Documentary gaps and competing source snapshots

**Status:** implementation candidate pending full-fork testing. **Required base:** published `Nicolas-Spoel/claims-verifier-core` at `855eecfa26b695286279107d208dd58095dde420` (M7-A + M8-A). This patch adds **three text files**. It does not modify M7-A, M8-A, the generic Claims Verifier Core, existing source connectors, or the M5 corpus.

## Purpose and precise boundary

M7-A validates the internal consistency of a fresh M3 report and emits a **text-free human-review queue**. M7-B builds on that gate to emit **documentary review gaps** and **competing snapshot indicators**. This is **not** an automated assessment of legal sufficiency, semantic entailment, normative contradiction, legal falsity, citation relevance, or the current validity of a rule.

M7-B performs the following bounded operations:

1. Reuses `m7_review_gate.assess_report()` **before** producing any review result. It preserves claim-number lineage, claim hashes, section hashes, non-exhaustive coverage and human review requirement.
2. Distinguishes four documentary workflow categories: `QUOTE_LOCATED_DOCUMENTARY_ONLY`, `QUOTATION_NOT_LOCATED_REVIEW`, `SECTION_IDENTIFIED_QUOTE_UNVERIFIED`, `CITATION_OR_SECTION_MISSING_OR_AMBIGUOUS`. A quotation found in a section **does not prove** the proposition that cites it.
3. Reports explicit, fixed review reason codes for BOE temporal applicability, TC doctrinal context, M3-B scope signals, unsupported sibling-clause citations and missing source date metadata. It **does not** determine effective dates for legal facts, ratio decidendi, exceptions, or precedent.
4. Groups **input evidence inventory** by exact source kind, canonical identifier and normalized section. If supplied snapshots for the same section have **different text hashes**, it flags a potentially relevant **documentary divergence**. It distinguishes `SAME_DATE_DIFFERENT_SECTION_BYTES` from `MULTIPLE_OR_UNDATED_SECTION_SNAPSHOTS`; neither label means contradictory law. Even a same-date mismatch can simply reflect incomplete user excerpts, reformatting or unreliable dates. These dates are merely supplied metadata and are not authenticated here.
5. Links a competing-snapshot group back to a claim **only when the claim explicitly identifies that source and section** (or already has an M3-verified evidence link). It does not infer a source for clauses lacking a citation or inherit a neighboring clause's citation.

## Privacy and security

- **Fully local / offline:** no browser, HTTP, subprocess, installs, LLM, CENDOJ, or network opt-in; input is `--text-file` and optionally `--evidence-json` only.
- `--evidence-json` uses the same allowlisted fields, bounded file reads and duplicate-key rejection as M7-A. Every locally supplied JSON source is forced to `origin=USER_SUPPLIED`, even if a caller sends `OFFICIAL_FETCH`.
- Normal output omits original claim text, source text, source URLs, full legal identifiers, names, titles and dates. It contains claim/evidence hashes, numeric group references, fixed signals and counts. **Hashes and counts are still sensitive case metadata**; do not publish outputs for real cases.
- The output must be a **new absolute private file outside Git**, created with `0600`; existing files and final-component symlinks are rejected by M7-A's shared helpers. Existing filesystem hardening limitations are tracked separately in M8-B.
- Validating an M3 report's internal consistency does **not** authenticate external sources. If the input report is forged and its hashes recomputed, this offline workflow does not prove authenticity. Explicit `source_authenticity_independently_verified=false`.
- `legal_support_assessed=false`, `documentary_sufficiency_measured=false`, `legal_accuracy_measured=false`, `expert_gold_cases=0`, `rights_cleared=false`, `coverage_exhaustive=false`, and `legal_truth_verdict=NOT_PRODUCED` for every claim.

## Installation and tests

```bash
cd ~/Spoel-Work/claims-verifier-core
git status --short
git log -1 --oneline

git apply --check ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M7B.patch
git apply ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M7B.patch
git diff --check

PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_m7_documentary_gaps.py' -v
PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected on the complete published fork with no other local changes: **39 M7-B tests**, **459 legal tests** (= 420 previous + 39), **205 generic Core tests**. Synthetic tests must not contact the network. Isolated environment test results are not a substitute for running the complete fork on the Mac.

## Synthetic demonstration — no real legal source text

M7-B accepts the **same synthetic text and evidence JSON** used in `docs/legal_es/M7.md`. If you already created the two synthetic `/tmp/kmh-m7-synthetic-*` input files from that document, execute:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m7_documentary_gaps \
  --text-file /tmp/kmh-m7-synthetic-argument.txt \
  --evidence-json /tmp/kmh-m7-synthetic-evidence.json \
  --output /tmp/kmh-m7b-synthetic-gaps.json
```

Expected mode: `OFFLINE_DOCUMENTARY_GAPS_AND_SNAPSHOT_DIVERGENCE_NOT_LEGAL_VERDICT`, `claims_queued >= 1`, `legal_support_assessed=false`. The generated report must include only metadata/review codes, not the original texts. Do **not** reuse that example as genuine constitutional evidence. The output is a local synthetic file with mode `0600`; never stage real-case output files in Git.

The second fixture tested programmatically supplies two different synthetic texts for the same `BOE-A-1978-31229` article `a24`, with different input version dates. Its outcome is **`MULTIPLE_OR_UNDATED_SECTION_SNAPSHOTS`**, not a legal contradiction or a statement about the actual Constitution.

## Acceptance, publication, and limits

- Require **459/459 legal and 205/205 Core** on the full Mac fork, and a successful synthetic demonstration.
- Check that all reported legal-support flags remain negative; competing snapshots must not be presented as proven contradiction or temporal applicability.
- Review the staged diff and all file names: exactly `docs/legal_es/M7B.md`, `src/keepmehonest_legal_es/m7_documentary_gaps.py`, and `tests/legal_es/test_m7_documentary_gaps.py`.
- Do not include downloaded BOE/TC content, confidential source text, private reports, expert records, or executable apps. Do not `git add .`.
- **Do not commit or push** until local acceptance and the staged content review.

M7-C remains blocked for **juridically adjudicated correctness/accuracy**: qualified independent expert review of a permitted, appropriately sourced dataset is still required. M8-B is a separate hardening track for network/proxy/filesystem trust boundaries. No general CENDOJ search is authorized.
