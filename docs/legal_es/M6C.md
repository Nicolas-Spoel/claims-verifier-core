# KeepMeHonest — M6-C1: manual Tribunal Constitucional HJ selection and bounded source linkage

**Status:** implementation candidate. **Base:** M6-A and M6-B present. This patch adds three text files only (`m6_tc_linkage.py`, its tests, and this document). It does not change the generic Claims Verifier Core, M2, M6-A, M6-B, BOE or TC transport.

## Why this is M6-C1 rather than a general TC search

The Tribunal Constitucional publishes an [official human-facing jurisprudence search](https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index), with ECLI, year, resolution type, subject and related filters. **A public web search form is not proof of a documented, stable, permitted API for automated full-text searching.** M6-C1 deliberately does **not** automate that search, scrape HTML results, launch a browser, or claim to have searched all case-law. It records an **explicit ECLI + HJ document ID + FJ/FALLO** supplied by a human after consulting an official public page, and then delegates **one read-only official JSON request** to the existing, allowlisted M2 TC connector. A user could provide wrong identifiers; M2 rejects a mismatch against the official response.

### Scope and privacy

- `plan`: no network. Requires `--ecli`, `--hj-id`, `--section`, `--topic` (`constitucional`, `administrativo`, `laboral`, `proteccion_datos`, `civil`). Topic is solely a bounded public catalog label; **not** a claim of case relevance or a free-text query.
- `resolve`: only with `--allow-official-network`; calls existing `TCClient.get_section` on `https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/{id}` once, checks ID/year/number/type/section through M2, then validates provenance again.
- The normal JSON report has identifiers, FJ/FALLO selection, date, response and section SHA-256, canonical official URLs and **explicit non-exhaustive coverage disclosures**, **not source text**. Optional `--private-evidence-output` stores the section text separately, new file only, permissions `0600`, outside Git; no content should be pushed publicly without rights clearance. Never pass a client's name, facts or file text as arguments.
- No CENDOJ, ordinary courts, browser automation, executable installers, shell commands, model inference, semantic legal classification, hidden TC search API, or unattended network work.
- No accuracy or relevance conclusions (`legal_support_assessed=false`, `legal_applicability=NOT_ASSESSED`, `legal_accuracy_measured=false`, `rights_cleared=false`). Nor does retrieving a single FJ establish ratio, precedent validity or completeness.

## Installation

Apply to the current uncommitted M6-A+B working tree without resetting it:

```bash
cd ~/Spoel-Work/claims-verifier-core

git apply --check ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M6C1.patch
git apply ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M6C1.patch

git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected full-fork suites: **316** legal (295 previous + 21 new), **205** Core. Isolated reconstructed suite: **312 discovered, 287 passed, 25 skipped** because Core integration dependencies absent in this temporary environment. 21/21 new tests PASS. Isolated results are **not** a substitute for execution on the full fork.

## Offline plan, no download

Use the official search interface in a regular browser of your choosing (manually, no automatic open command):
`https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index`

For the pre-existing public STC 1/2024 pilot, *only once you have checked the HJ document ID from the official site*, run:

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_tc_linkage plan \
  --ecli ECLI:ES:TC:2024:1 --hj-id 30062 --section FJ1 --topic constitucional
```

Expected `OFFLINE_MANUAL_TC_SELECTION`, `network_used=false`, `user_supplied_pair_verified=false`, `coverage.exhaustive=false`.

## Real official source read — explicit opt-in

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_tc_linkage resolve \
  --ecli ECLI:ES:TC:2024:1 --hj-id 30062 --section FJ1 --topic constitucional \
  --allow-official-network \
  --output /tmp/kmh-m6c1-tc2024-1-fj1-metadata.json
```

Expected `TC_SECTION_RETRIEVED_DOCUMENTARY_ONLY`, `user_supplied_pair_verified=true`, `section_retrieved=true`, `section_text_sha256` and `raw_response_sha256` both 64-char lowercase hex, `source_text_in_report=false`, `coverage.exhaustive=false`. This performs **exactly one allowed TC JSON request**. No download via a browser, no PDF and no client data transmitted.

Optional private section text (different location from the public metadata; pre-existing directory):

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_tc_linkage resolve \
  --ecli ECLI:ES:TC:2024:1 --hj-id 30062 --section FJ1 --topic constitucional \
  --allow-official-network \
  --private-evidence-output "$HOME/Spoel-Work/KMH-private-captures/m6c1-stc1-2024-fj1-PRIVATE.json"
```

Do not include any downloaded official JSON or private text in Git. If TC is unreachable, unsupported or returns inconsistent metadata, the command fails closed; no authority absence inference follows. The official HJ site might have its own access conditions requiring further review before building a product-wide automated search.

## Acceptance gate and further M6-C

- Full-fork 316 legal + 205 Core tests PASS.
- Explicit offline plan behaves as specified.
- Single real public TC section retrieval succeeds with identity/date/hashes; no source text in normal report.
- Verify that the six previous M6-A/B files and these three new files are exactly those intended for Git. **Do not commit or push before the owner has reviewed the staged paths.**
- **Automated general TC jurisprudence discovery remains BLOCKED** pending an independently verified, documented/authorized request contract, relevant licensing/privacy review, and measurable retrieval coverage. Until a gold corpus exists, retrieval accuracy cannot be claimed.
