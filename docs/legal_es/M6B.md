# KeepMeHonest Spanish Legal — M6-B: explicit BOE candidate-to-article linkage

**Status:** implementation candidate; requires full-fork unit tests and a live, public-only BOE acceptance test on the user's Mac. **Base:** M6-A applied, regardless of whether M6-A is committed. This incremental patch adds only `m6_linkage.py`, its tests and this document.

## Scope and safety

- Takes a **saved M6-A listing report**, checks the contract, canonical query, candidate inventory and hash fields, then requires the user to select **a BOE-A identifier present in that page**, **an integer article** and **an explicit historical date (`--as-of`)**.
- `plan` runs offline. `resolve` requires `--allow-official-network`. It uses the **existing M2 `BOEClient.get_article`** (official index + block endpoint), not a new parser, general web search, inferred article, generated citations or AI model.
- Article block, version effective-from, version publication and modifying norm are reported as **M2 documentary metadata**. The cited text is hashed locally and omitted from regular JSON/stdout. An optional **separate private JSON** can preserve the text (permissions 0600, new file only, outside the working repository). No source bytes are included in this patch.
- Never makes a legal-support, continuing validity, case applicability, legal accuracy, rights/reuse or exhaustive coverage conclusion. A historical consolidated version is **not necessarily legally applicable** to facts on that date; transitional arrangements, hierarchy, case law and tacit repeal are not analyzed.
- The listing report's `raw_sha256` is a recorded remote-response fingerprint from M6-A; **without the raw response it cannot independently prove that the listing came from the official server**. The original index response used by M2 is **not sealed**; only the article-block raw hash is available. M6-B is not a full replay-capable snapshot of the BOE. The linked BOE-ID is independently used in a new constrained M2 retrieval.
- If discovery returned a false-positive title match, M6-B can fetch the *requested* article but does not upgrade that hit to relevance. Missing/ambiguous/expired articles or source errors must fail closed. The tool does not search for other applicable norms.
- No CENDOJ scraping, ordinary-court search, general TC search, regional/EU sources, sending client text, or access-rights expansion. No model benchmarks.

## Acceptance tests

In the fork root, after M6-A is applied, apply the M6-B incremental patch **once**:

```bash
cd ~/Spoel-Work/claims-verifier-core
git status --short
git apply --check ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M6B.patch
git apply ~/Downloads/KEEP-ME-HONEST-LEGAL-01_M6B.patch
git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py'
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
```

**Expected on your Mac:** `295` legal tests (M6-A baseline 268 + 27 new M6-B) and `205` generic Core tests. The assembled isolated test environment ran `291` legal tests, **266 passing and 25 skipped** for missing Core integration; that environment does not perfectly reproduce every previously modified test in the full fork. The 27 new M6-B tests pass independently. Do not substitute this for the full-fork run.

## Offline selection — no network

Use the existing **machine-readable** M6-A report saved earlier, *not* the Markdown-rendered JSON pasted into chat. Your report path was `/tmp/kmh-m6-boe-discovery-retest.json`; the file must still exist on your machine.

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_linkage plan \
  --discovery-report /tmp/kmh-m6-boe-discovery-retest.json \
  --identifier BOE-A-1978-31229 \
  --article 24 --as-of 2024-01-15
```

Expected `OFFLINE_EXPLICIT_SECTION_SELECTION`, `network_used=false`, `section_retrieved=false`, `legal_support_assessed=false`. For a date earlier than the discovered norm's publication, or a norm absent from that page, the command refuses to proceed.

## Live public BOE article smoke — explicit opt-in

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_linkage resolve \
  --discovery-report /tmp/kmh-m6-boe-discovery-retest.json \
  --identifier BOE-A-1978-31229 \
  --article 24 --as-of 2024-01-15 \
  --allow-official-network \
  --output /tmp/kmh-m6b-boe-art24-metadata.json
```

The command attempts at most the two M2 requests (index and block). It does not automatically retry. The returned report should have `mode=BOE_ARTICLE_VERSION_RETRIEVED_DOCUMENTARY_ONLY`, `section_id`, `selected_version_effective_from`, `selected_version_published_on`, `modifying_norm`, section text SHA-256, response SHA-256 and explicit `temporal_status=CHECK_REQUIRED`. It **must** have `section_text_in_report=false`, `legal_support_assessed=false`, `legal_applicability=NOT_ASSESSED`, `coverage_exhaustive=false`, `rights_cleared=false`, and `index_response_sealed=false`.

The `--output` path must not exist already. If the source is unavailable, the command fails rather than inferring no authority. Check the `section_official_url` manually at the BOE website; note that the retrieved consolidated text itself is informative rather than the legally controlling original official publication.

**Optional private article-text export** (new absolute path outside Git; not for publication):

```bash
PYTHONPATH=src python3 -m keepmehonest_legal_es.m6_linkage resolve \
  --discovery-report /tmp/kmh-m6-boe-discovery-retest.json \
  --identifier BOE-A-1978-31229 \
  --article 24 --as-of 2024-01-15 \
  --allow-official-network \
  --private-evidence-output "$HOME/Spoel-Work/KMH-private-captures/m6b-art24-PRIVATE.json"
```

No raw BOE XML, corpus of source text, private output or personal/client information should be staged or pushed to GitHub. Publication of M6-B code remains conditional on tests and the real BOE smoke test; permission for downstream reuse of source content is **not** implied.

## Out of scope / next

M6-C should assess documented/authorized judicial search capabilities and provenance of results. Until then, M6-B only links a selected discovered **BOE law** to a **specific article/version**. M7 support classification requires a separate legally adjudicated evaluation design and a viable private-data deployment path.
