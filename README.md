# Claims Verifier Core

Claims Verifier Core checks claims against a fixed corpus of documents. For each claim it reports whether a passage
**supports** it, **contradicts** it or supports it **partially**, whether the **sources conflict**, whether related
evidence **does not allow a decision**, or whether there is **not enough evidence**. Each verdict comes with
uncertainty reasons and, when there is deciding evidence, a traceable quotation and its provenance.

Pipeline: documents → passages with offsets → claims → BM25 retrieval → conservative lexical judgment → verdicts
with provenance → JSON or Markdown report.

- Version 0.1.1, **experimental**. Python standard library only: no dependencies, no network, no models.
- **It can return a wrong `SUPPORTED` or `CONTRADICTED`** in known situations: bounds and negated bounds,
  ranges and approximations, coordinated populations, years read as counts and residual word collisions
  ("Known issues", items 9–11). Treat every verdict as a pointer to evidence for human review.
- Deterministic: same corpus, configuration, input, version and platform → same report, byte for byte (tested on
  macOS).
- Product language: English. Reports, CLI messages and documentation are in English.
- Lexical support: English and Spanish, administrative and business register. Both languages have their own word
  lists and rules; the remaining gaps are listed under "Known issues".

## What it is and what it is not

**It is** a heuristic, lexical verifier. Using lexicons and surface rules, it compares terms, figures, dates,
negation, direction of change, modality, process stage (request vs outcome), entity roles and population scope.
When it sees risk signals it abstains or downgrades support instead of deciding.

**It is not** a system that automatically establishes the truth of any claim:

- `SUPPORTED` means support according to the evidence examined and the system's rules, not universal truth. Do not
  use it as automatic confirmation.
- `NOT_ENOUGH_EVIDENCE` does not mean that the claim is false, only that the passages examined do not contain
  enough evidence.
- Abstention (`CONFLICTING`, `INCONCLUSIVE`, `NOT_ENOUGH_EVIDENCE`: verdicts without a `score`) and partial support
  are expected behaviors, not failures.
- `score` is a heuristic for ordering and triage; **it is not a calibrated probability**.
- It does not understand deep paraphrase or multi-step inference.
- It is not validated for autonomous legal, medical or scientific decisions, nor certified for production use.

## Capabilities: implemented, tested and not validated

| Capability | Status |
|---|---|
| Ingestion of `.md`, `.markdown`, `.txt`, `.json` and `.jsonl`; passages with offsets and line numbers | Implemented and tested |
| Segmentation of an answer into claims (sentences, ";" and contrastive connectors), or pre-extracted claims | Implemented and tested on synthetic texts; not validated on diverse real texts |
| BM25 retrieval over passages | Implemented and tested |
| Lexical judge: support, explicit contradiction (figure, date, negation, direction, stage) and uncertainty signals | Implemented and tested on synthetic English and Spanish cases; overall accuracy not validated |
| Explicit abstention with uncertainty codes | Implemented and tested |
| Provenance: identifier, path, SHA-256 hashes, offsets, line and quotation for each piece of evidence | Implemented and tested against the original files |
| Source inventory and completeness against an expected inventory | Implemented and tested |
| Python API, CLI and reproducible JSON (`schema_version` 2.0) and Markdown reports | Implemented and tested with CPython 3.13 on macOS; Linux and Windows not tested |
| Limits of 5,000 documents, 50 MB per corpus, 200,000 passages and 200,000 characters per answer | Implemented, without a dedicated test |
| Paraphrase, multi-step inference, other languages or specialized domains | Not validated |
| Calibrated probabilities | Not implemented |

## Installation and requirements

Python ≥ 3.11 (declared; the test suite has been run on CPython 3.13). There are no runtime dependencies.

```bash
python -m pip install .          # from the repository root
claims-verifier --version        # claims-verifier 0.1.1
```

Installation uses `setuptools>=77` as the build backend. Offline, if it is already installed:
`python -m pip install --no-build-isolation --no-index .`

It can also be used without installing, from the repository root, with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m claims_verifier --version
```

## Runnable example

`examples/demo/` contains an entirely synthetic corpus (the fictitious company "Nimbus Logística"), a simulated
assistant answer and the expected results.

```bash
claims-verifier verify --corpus examples/demo/corpus --answer examples/demo/answer.md --format markdown
```

| Id | Claim | Verdict |
|---|---|---|
| C1 | Nimbus Logística recorded revenue of S/ 48.6 million in 2023. | `SUPPORTED` |
| C2 | Revenue grew by 15% compared with 2022. | `CONTRADICTED` |
| C3 | The company opened a distribution center in Arequipa in March 2023. | `SUPPORTED` |
| C4 | The company has 1,240 employees. | `PARTIALLY_SUPPORTED` |
| C5 | The current fleet is 340 trucks. | `CONFLICTING` |
| C6 | The new distribution center in Trujillo will open in 2025. | `PARTIALLY_SUPPORTED` |
| C7 | All employees are satisfied with the workplace climate. | `PARTIALLY_SUPPORTED` |
| C8 | The accident rate did not decrease in 2024. | `INCONCLUSIVE` |
| C9 | The net margin increased to 6.8% in 2023. | `CONTRADICTED` |
| C10 | The general manager is Lucía Ramos. | `SUPPORTED` |
| C11 | Nimbus Logística has been listed on the Lima Stock Exchange since 2019. | `NOT_ENOUGH_EVIDENCE` |
| C12 | Nimbus Logística reduced its carbon emissions by 30%. | `PARTIALLY_SUPPORTED` |

The heading, the closing question and the pleasantry in the answer are not verified; they appear as skipped
segments. `examples/demo/expected_verdicts.json` holds the label each claim should get, and the reference reports,
which the engine reproduces byte for byte, are in `examples/demo/expected/report.json` and `report.md`.

## API usage

```python
from pathlib import Path

from claims_verifier import ClaimsVerifier, VerifierConfig, load_corpus
from claims_verifier.inventory import load_expected
from claims_verifier.report import to_json

verifier = ClaimsVerifier(
    load_corpus("examples/demo/corpus"),
    VerifierConfig(top_k=8),
    expected=load_expected("examples/demo/inventory.json"),  # optional: enables the completeness check
)
report = verifier.verify_answer(Path("examples/demo/answer.md").read_text(encoding="utf-8"))
for result in report.results:
    print(result.claim.claim_id, result.verdict.value, result.score)
json_text = to_json(report)
```

| Element | Contract |
|---|---|
| `ClaimsVerifier(corpus, config=VerifierConfig(), judge=None, retriever=None, expected=None)` | Orchestrates search, judgment and aggregation. `expected` (a sequence of `ExpectedSource`) enables the completeness check. |
| `ClaimsVerifier.from_path(path, config)` · `from_documents(documents, config)` | Corpus from disk (non-strict mode) or in memory. In memory there are no file records, completeness is `unverifiable` and only the 200,000-passage limit applies. |
| `verify_answer(text)` · `verify_claims(texts)` | Return a `VerificationReport`. |
| `VerifierConfig(top_k=8, max_evidence=4, judge=JudgeConfig(), synonym_groups=())` | Passages examined per claim, pieces of evidence cited and extra synonyms. The values are not validated (with `top_k=0` no passage is examined). |
| `load_corpus(root, strict=False)` · `make_document(doc_id, text, ...)` | Load with a source inventory · in-memory document. |
| `inventory.load_expected(path)` | A list of paths or `{"documents": [{"path", "sha256"}]}`. Paths are relative to the corpus directory (or just the file name if the corpus is a file); an absolute path never matches. |
| `report.to_dict` · `to_json` · `to_markdown` · `report.SCHEMA_VERSION == "2.0"` | Stable serialization of the report. |
| `evaluation.load_cases(path)` · `evaluation.evaluate(verifier, cases)` | Accuracy, confusion matrix and misses. Rejects cases that are empty or longer than 2,000 characters. |
| `judge.Judge` and `retrieval.Retriever` protocols | `name` and `assess(claim, passage, retrieval_score) → PassageAssessment` (without `name`, the report uses the class name; an optional `signals(text)` method lets the verifier flag hedged claims) · `search(terms, k)`, `idf(term)`, `document_frequency(term)`. The library ships only the lexical judge and the BM25 retriever. |

A custom judge or retriever must respect the implicit contract of the aggregation step:

- Aggregation interprets the lexical judge's signal codes (`NUMBER_MATCH`, `NUMBER_MISMATCH`, `DATE_MISMATCH`,
  `STAGE_CONFLICT`, `SCOPE_MISMATCH`).
- It expects `relevance` in [0, 1] and applies the `JudgeConfig` thresholds.
- A `CONTRADICTS` assessment without signals raises `ValueError`.
- `signals(text)`, if present, must return an object with a `hedged` attribute.
- `search(terms, k)` receives stems that are already normalized and expanded with synonyms.

## CLI usage

`claims-verifier verify --corpus DIR|FILE (--answer FILE|- | --claims FILE|-) [options]`

- `--answer`: free text or Markdown, segmented by sentence, ";" and contrastive connectors. This is not a
  decomposition into atomic claims: "X is the manager and the fleet is 340 trucks" stays a single claim.
  - Each claim carries its `char_span` in the answer as read: CRLF line endings become LF, and the span includes
    the Markdown markers that are removed from `text`.
  - Headings and questions are not verified; if they carry factual content they are flagged `UNCHECKED`.
  - A sentence with a pleasantry from the closed list ("hope this", "let me know", Spanish "espero que"…) is
    skipped only if no factual content remains once the pleasantry is removed.
  - Segments with fewer than two content terms and no figures are skipped as `no_factual_content` (they do not
    count as `UNCHECKED`). Every other sentence is verified as a claim.
  - Any sentence longer than 1,000 characters is cut at spaces into chunks of up to 1,000 characters, which are
    verified separately.
- `--claims`: pre-extracted claims (a JSON array of strings, or one per line; text that starts with "[" but is not
  valid JSON is read as one claim per line). Empty claims are discarded, and the ids `C1`, `C2`… are assigned in
  order to the accepted ones; their `char_span` is `null`. A claim longer than 2,000 characters is not analyzed:
  it goes to `skipped` as `too_long` and `UNCHECKED`, with `char_span` `[0, length]`.
- An answer longer than 200,000 characters is an input error, as is an `--answer`, `--claims` or `--synonyms` file,
  or stdin, larger than 2,000,000 bytes. `--expected` and `--cases` have no such limit.
- `--format markdown|json` (default `markdown`), `--out FILE`, `--top-k N` (1–100), `--synonyms groups.json`.
- `--expected inventory.json`: the only way to verify completeness; without it the report says `unverifiable`.
  Paths are compared with the corpus paths (relative to its directory, with `/` and without `./`).
- `--strict`: exit code 2 in these cases:
  - a file of a supported type cannot be used: invalid UTF-8, invalid JSON or no `text`, larger than 2 MB, or not
    a regular file;
  - a link points outside the corpus, even if its type is not supported;
  - there are duplicate ids.

  Unsupported types, hidden entries, linked directories and files without text are still excluded with a reason,
  even with `--strict`. Without `--strict`, duplicate ids are renamed to `id@path` and the change is noted in the
  file's record.
- `--fail-on VERDICTS`: a comma-separated list (`CONTRADICTED,CONFLICTING,UNCHECKED`…) that produces exit code 1
  and names the affected claims, or `UNCHECKED@offset`, on stderr (with `--claims`, the offset is always 0).

`claims-verifier evaluate --corpus DIR --cases cases.json [--min-accuracy X]`:
- Cases are `[{"claim": str, "expected": VERDICT}]`; each claim must be non-empty and at most 2,000 characters
  long (otherwise exit code 2). Non-string `claim` values are converted with `str()`.
- Writes `{total, correct, accuracy, confusion, misses}` to stdout.
- `--min-accuracy` is compared with the accuracy rounded to 4 decimal places and is not validated against [0, 1].
- `evaluate` does not accept `--top-k`, `--synonyms` or `--strict`.

Exit codes:
- `0`: success.
- `1`: `--fail-on` or `--min-accuracy` not met.
- `2`: anticipated input error.

Some unanticipated malformed inputs end with a traceback and exit code 1 (see "Known issues").

### Corpus

A directory (or file) with `.md`, `.markdown`, `.txt`, `.json` (an object or list with a `text` field) and
`.jsonl`.

- Optional metadata in front matter or as JSON fields: `title`, `date`, `id`, `version`.
- An ISO date (`YYYY-MM-DD`) is used to identify the most recent source when sources conflict.
- A file larger than 2,000,000 bytes is excluded with a reason, or is an error with `--strict`. A `.jsonl` file
  counts as one file.
- Exceeding 5,000 documents, 50 MB per corpus or 200,000 passages is always an input error (exit code 2).
- Hidden files, unsupported types and links that point outside the directory are excluded and listed with their
  reason.
- A JSON/JSONL record whose `text` is empty is discarded without a recorded reason if the file has other records
  with text.

## Evidence provenance

Top-level keys of the JSON report (`schema_version` 2.0): `schema_version`, `engine`, `corpus`, `sources`,
`search`, `score_semantics`, `summary`, `claims`, `skipped`, `limitations`.

Each piece of evidence (`claims[].evidence[]`) has these fields: `stance`, `doc_id`, `document_title`,
`document_date`, `source_path`, `document_sha256`, `document_version`, `source_in_expected_inventory`,
`passage_sha256`, `passage_id`, `line`, `char_span`, `quote`, `relevance`, `retrieval_score`, `signals[]`,
`matched_terms` and `missing_terms`.

Which evidence is cited, up to `max_evidence`:
- `evidence[]` holds only the passages that support or contradict. If there are none, it holds the ambiguous
  ones and, failing those, the partial ones.
- `NOT_ENOUGH_EVIDENCE` carries no quotation.
- In `CONFLICTING`, the partial or ambiguous passage behind the conflict may not be cited and may appear only in
  the `uncertainty` detail.

Field semantics:
- `char_span` is `[start, end)` in character indices of the document text:
  - for `.md`, `.markdown` and `.txt`, the whole file, with front matter and without a BOM;
  - for JSON/JSONL, the record's `text` field, and `source_path` ends in `#index`.

  `quote` is exactly that fragment and `line` is the line (from 1) where it starts.
- `document_sha256` and `corpus.documents[].sha256` are the SHA-256 of the document text in UTF-8.
- `sources.records[].sha256` is the SHA-256 of the file bytes, and is what `--expected` compares.
- `passage_sha256` is the SHA-256 of the passage text as the engine normalizes it, not of `quote`:
  `text.strip_markdown` is applied to each line of `quote`, the lines are joined with a space and the ends are
  trimmed.
- `corpus.fingerprint` is a SHA-256 over the id and the text hash of each examined document.

  **Limitation:** the fingerprint does not change in these cases:
  - only the metadata of a JSON/JSONL record changes (`title`, `date`, `version`…);
  - the formatting of a JSON file changes (whitespace, key order) or a BOM is added;
  - a file with an explicit `id` is renamed or moved;
  - an excluded file changes.

  To pin a corpus byte for byte, use `--expected` with hashes.

`sources` lists `received`, `examined`, `excluded[]` and `records[]` (`path`, `status`, `reason`, `doc_ids`,
`sha256`), plus `note` and `accounting`. Completeness can only be checked against an expected inventory:

| `sources.accounting.completeness` | Meaning |
|---|---|
| `complete` | Every expected source was received and examined, and its hash matches; no unexpected source was examined. |
| `complete_unversioned` | The same, but some inventory entry has no hash: those versions were not verified. |
| `unexpected_sources` | All expected sources are present, but sources outside the inventory were examined. |
| `incomplete` | An expected source is missing, its hash differs, or it was excluded. |
| `unverifiable` | No expected inventory was provided. |

With an inventory, `accounting` also includes `expected`, `missing`, `version_mismatch`, `excluded_expected` and
`unexpected`. Documents that were never supplied and are not in the inventory are unknown to the verifier.

```bash
claims-verifier verify --corpus examples/demo/corpus --answer examples/demo/answer.md --format json \
  --expected examples/demo/inventory_incomplete.json     # completeness: incomplete, missing: financial_statements_2023.md
```

The Markdown report, the default format, is a readable summary of the same decisions. It shows the path, line,
`passage_id` and date of each quotation (truncated to 280 characters), the skipped segments, completeness, an
abbreviated fingerprint and the limitations. All input text is escaped. Full hashes and offsets are only in
`--format json`.

## Verdicts and uncertainty states

| Verdict | Meaning | `score` (default configuration) |
|---|---|---|
| `SUPPORTED` | A passage covers the claim and its figures/dates match. | up to 0.99 |
| `PARTIALLY_SUPPORTED` | Support with reservations: incomplete coverage, overstated quantifier or certainty, a state that is no longer current, a population or period subset, reported speech. | up to 0.70 |
| `CONTRADICTED` | A passage on the same topic with an opposite figure, date, month, negation, direction of change or stage (approved vs rejected), or a proportion stated in words ("the majority") that is incompatible with the evidence's percentage. Its only possible uncertainty code is `CLAIM_HEDGED`, when the claim itself is tentative. | up to 0.95 |
| `CONFLICTING` | Some sources support and others contradict or cast doubt. If ISO dates are available, the most recent document on either side of the conflict is named; when there is an explicit contradiction, ambiguous passages are on neither side. Requires human review. | `null` |
| `INCONCLUSIVE` | There is related evidence, but a safety guard prevents a decision: reversed roles, a request without an outcome, a statement that information is missing, a weak contradiction. | `null` |
| `NOT_ENOUGH_EVIDENCE` | Nothing relevant among the passages examined; terms absent from the corpus and evidence about another period are reported separately. | `null` |

Scores are not comparable across verdicts. Each result has `uncertainty[]` with codes and details, for example
`SINGLE_SOURCE`, `CONFLICTING_SOURCES`, `STATE_NOT_CURRENT`, `QUANTIFIER_OVERSTATED`, `CERTAINTY_OVERSTATED`,
`NEGATION_MISMATCH`, `PERIOD_SUBSET` or `NO_EVIDENCE`. `score_kind` is always `heuristic_uncalibrated`. The
report's `limitations` text groups `INCONCLUSIVE` and `PARTIALLY_SUPPORTED` as ways of not deciding in the
presence of risk signals.

## Limitations

- Lexical verification: a true paraphrase ("forty-two battery-powered cargo vehicles" vs "42 electric trucks")
  usually ends up as `NOT_ENOUGH_EVIDENCE` or `INCONCLUSIVE`.
- Only the `top_k` passages retrieved per claim are examined: "not enough evidence" means neither "false" nor that
  the corpus lacks the fact.
- Synonyms are limited to the built-in dictionary and the groups supplied.
- Evidence is assessed sentence by sentence, with the title, heading and previous sentence as context.
- Numeric dates are read as day/month/year.
- An isolated initial ("Vitamin C. The…") can merge two sentences.
- Pleasantries outside the closed list are verified as claims and end up without evidence (they are never hidden).
- Completeness exists only against an expected inventory.
- The corpus fingerprint has the limits described under "Evidence provenance".
- The lexicons cover the administrative and business register in English and Spanish; other languages and domains
  have not been evaluated. English-language performance has not been independently validated.
- The only figures in this document are those that can be reproduced with the included data. The labeled sets in
  `examples/benchmark/` are small and synthetic and served as regression thresholds during development: they do
  not estimate accuracy on real texts.

## Known issues (v0.1.1)

1. Some unanticipated malformed inputs end with a traceback and exit code 1 (the same code as `--fail-on`)
   instead of an input error with exit code 2. For example:
   - a non-string `sha256` in `--expected`;
   - a JSON integer of more than 4,300 digits in `--claims`, `--expected`, `--cases` or `--synonyms`.
2. `--expected` and `--cases` are read without a size limit.
3. The BOM is not removed from `--answer`, `--claims` or `--synonyms`:
   - a heading at the start of an answer with a BOM is verified as a claim;
   - a JSON array with a BOM in `--claims` is not recognized as one.
4. If a `.jsonl` or `.json` file has records with text and others with a blank `text`, the blank records are
   discarded without a recorded reason. The file stays `examined`, even with `--strict`.
5. An upper-case `.JSONL` extension is read as plain JSON and the file is excluded as invalid JSON.
6. When a sentence longer than 1,000 characters has no space in the cutting window, one character is lost at each
   cut.
7. On Windows, `--out` writes CRLF line endings, so byte-for-byte reproduction and some tests do not apply. Not
   tested.
8. On Linux, a file name that is not valid UTF-8 might prevent the report from being serialized. Not tested.
9. Stems are cut to five letters before synonyms are applied, so a word can fall into an unrelated synonym group.
   The collisions found are excluded explicitly, among them "plant" and Spanish "planta" (not "plantilla", the
   workforce), "direction", "utility", "decree", "customs", "benefits" and Spanish "decreto", "utilizar". Others
   remain: "customized" counts as "clients", "proficiency" as "profit", Spanish "dirección" as "gerente" and
   "beneficiarios" as "utilidad".

### Known ways to get a false SUPPORTED or CONTRADICTED

These come from the original engine and are present in this version. Treat every verdict as a pointer to evidence
for human review.

10. False `SUPPORTED`:
    - **Bounds read with rounding slack.** "Exports exceeded 5 million tonnes." is supported by "Exports reached
      4.8 million tonnes."; "under 10%" by 10.4%; "Fewer than 600 members voted in the assembly." by "600 members
      voted in the assembly, fewer than in the previous year."
    - **"over" read as a bound.** "Acme took over 600 stores in 2023." is supported by "Acme took over 640 stores
      in 2023."
    - **A bound read as a direction of change.** "Sales grew in 2024." is supported by "Sales in 2024 were more
      than 5 million."
    - **"almost", "nearly" and Spanish "casi" accept a higher figure.** "Nearly 5,000 members attended the
      assembly." is supported by "5,200 members attended the assembly."
    - **A year read as a count matches the adjacent year.** "The 2024 dividend was $0.40 per share." is supported
      by "The 2023 dividend was $0.40 per share.", and Spanish "La campaña 2024 produjo 3.000 toneladas de café."
      by "La campaña 2023 …".
    - **Coordinated populations.** "Revenue from coffee reached $12 million in 2024." is supported by "Revenue
      from coffee and cocoa reached $12 million in 2024.", even when the evidence adds "two thirds of which came
      from cocoa".
    - **Verbs whose past form equals the base form** ("cut", "put", "set") escape the non-finite check. "The
      company cut 200 jobs." is supported by "The company refused to cut 200 jobs."
    - **Spanish "más" is a stopword.** "La planta produjo más cobre." is supported by "La planta produjo cobre."
    - The remaining stem collisions of item 9.
11. False `CONTRADICTED`:
    - **Negated bounds are read as plain bounds plus a negation.** "The cooperative trained over 400 farmers in
      2024." is contradicted by "The cooperative trained no fewer than 450 farmers in 2024." Spanish "La
      municipalidad no gastó más de S/ 2 millones en obras en 2024." is contradicted by "La municipalidad gastó
      S/ 1,6 millones en obras en 2024."
    - **Ranges are not understood.** Spanish "La obra costó entre 3 y 4 millones de soles." is contradicted by
      "La obra costó 3,5 millones de soles."
    - **Approximations allow only 5%.** "About 30% of the budget went to health." is contradicted by "28% of the
      budget went to health." Spanish "cerca del" (with the article) is not recognized as an approximation:
      "Cerca del 30% del presupuesto …" is contradicted by 28%.
    - **Restricting phrases are not always detected.** Spanish "Las ventas bajaron en 2024." is contradicted by
      "Las ventas bajo el nuevo esquema crecieron en 2024.": "bajo" ("under") is read as "fell".

### Remaining misses on the labeled examples

The example corpora and labeled benchmarks are English translations of the project's original Spanish
development data, with the expected labels unchanged. Nine cases still miss their label, none of them with a false
`SUPPORTED` or `CONTRADICTED`:

12. Benchmark case 13 ("The company has more than 600 workers.") gets `NOT_ENOUGH_EVIDENCE`, and extra case 2
    ("Coffee collection increased in 2024 compared with 2023.") gets `PARTIALLY_SUPPORTED`: "more than" and
    "compared" are terms the evidence must contain (item 19).
13. Benchmark case 18 ("The desalination plant will operate in 2027."; the same happens in Spanish) gets
    `INCONCLUSIVE` instead of `PARTIALLY_SUPPORTED`. A passage about another plant, which came into operation in
    2023, reaches a coverage of 0.61 against a topic threshold of 0.60. Its date mismatch makes it undecided, and
    an undecided related passage takes precedence over the passage that fully covers the claim but is hedged.
14. Extra case 3 ("The 2024 collection fell by 6% because of the rains.") gets `PARTIALLY_SUPPORTED`: "because" is
    a term the evidence must contain, and the evidence says "as a result of".
15. Extra cases 6 ("The cooperative has 2,300 members.") and 7 ("The majority of the members are women.") get
    `PARTIALLY_SUPPORTED` and `INCONCLUSIVE`. A fraction written as a partitive restricts the scope of the whole
    sentence, also inside a relative clause ("2,300 producer members, 41% of whom are women"). An exemption for
    relative clauses was tried and withdrawn, because it let coordinated populations through ("coffee and cocoa
    sales …, 70% of which came from cocoa").
16. Extra case 9 ("Germany was the main export destination.") gets `PARTIALLY_SUPPORTED`. "with 35% of the
    exported volume" is read as restricting the claim's scope. Exempting such shares would also let "half of the
    workforce" support a claim about the whole workforce, so the conservative reading is kept.
17. Extra case 10 ("The cooperative sold coffee to the United States in 2024.") gets `INCONCLUSIVE` against "The
    cooperative did not sell coffee to the United States in 2024.": "sold" and "sell" do not share a stem. A
    mapping of irregular past forms to their base was tried and withdrawn, because it also matched nouns
    ("sell-off", "write-off", "teachers", "know-how").
18. Extra case 24 gets `PARTIALLY_SUPPORTED`, as it did before translation: the figure's attribute is worded
    differently ("accounted for 35% of the volume") and the same scope reading applies.

### Other limits of the English and Spanish coverage

These are deliberate, conservative behaviours. They avoid false verdicts but can cost a correct one.

19. In English, bound markers ("more than", "fewer than", "at least"), comparatives ("more … than"), causes
    ("because") and "compared" are terms the evidence must contain, so a bound, a comparison, a cause or a
    comparison baseline is never assumed from the rest of the wording. In Spanish, "menos de" and "al menos"
    behave the same way, while Spanish "más", "por" and "porque" are stopwords (item 10).
20. Approximation markers ("close to", "about", Spanish "cerca de") are part of the figure that follows. An
    approximate or bounded figure in the evidence confirms only a figure of the same kind: "over 600 tonnes" is
    only partially supported by "about 700 tonnes". A consistent figure of another kind ("about 600" vs "fewer
    than 590") decides nothing.
21. Irregular English past forms ("sold", "taught", "wrote") are not matched with their base form (item 17). Only
    "mainly" and "partly" are reduced to their base among six-letter "-ly" adverbs; "part" itself is not a
    content term, so "partly" matches nothing.
22. A year is recognized in attributive position after an English determiner and before a singular period noun
    from a fixed list ("the 2024 collection", "its 2023 report"). The rule can misread a count: "the 2000 survey
    kits" is read as a year. Other counts ("the 2000 people", "its 2000 accounts", "the 2000-seat stadium") stay
    counts.
23. A stated proportion ("the majority", Spanish "la mayoría") is compared with a percentage in the evidence, but a
    percentage written as a partitive ("41% of the members", "41% of whom") leaves the comparison undecided. The
    Spanish relative form ("de los cuales el 41%") is not read as a partitive, so it is compared, as before.
    - The same proportion stated for another year is another period, not a contradiction. This holds even for a
      single dated event: "The majority of shareholders approved the merger in 2024." is not contradicted by
      "… in 2022".
    - "first half" is a period, not a proportion, so "the first half of the loan" is also read as part of a period.
24. "declared" and "pointed" are reporting verbs, so "For 2024, the cooperative declared a dividend of $0.40 per
    share." only partially supports "the dividend was $0.40 per share". The token "states" in "United States" is
    also read as a reporting verb.
25. An infinitive after "to" or a modal ("refused to expand", "could expand") is detected as a non-finite predicate
    only for claim verbs of five or more letters; see item 10 for verbs whose past form equals the base form.
26. The stem-collision exclusions can cost a match: "directed" no longer matches "director".

`tests/test_report_cli_demo.py` checks that every labeled case gets its expected verdict except cases 12–18 above,
and that no case gets a false `SUPPORTED` or `CONTRADICTED`. `tests/test_english_coverage.py` covers each English
construction with counterexamples, including 96 independently written pairs and the 12 cases of item 15 and
item 17's withdrawn mechanisms, none of which may receive a forbidden verdict.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests       # 205 tests, no network, standard library only
```

They cover, among other things:
- evidence that supports a claim, and explicit contradiction;
- abstention when evidence is insufficient;
- provenance: offsets, hashes and `passage_sha256` recomputed against the original files;
- incomplete corpora and unverifiable completeness;
- invalid inputs and rejection of evaluation cases that cannot be evaluated;
- byte-for-byte reproduction of the example reports.

Tests that exercise the Spanish lexicon keep Spanish inputs on purpose, and the test modules label them as
Spanish-language support data.

## Reproducing the results

```bash
claims-verifier verify --corpus examples/demo/corpus --answer examples/demo/answer.md --format json --out report.json
cmp report.json examples/demo/expected/report.json && echo identical

claims-verifier evaluate --corpus examples/benchmark/corpus --cases examples/benchmark/cases.json
claims-verifier evaluate --corpus examples/benchmark/extra/corpus --cases examples/benchmark/extra/cases.json
```

Expected results:
- the report is identical byte for byte, and `--format markdown` reproduces `report.md`;
- `evaluate` scores 24/26 on `examples/benchmark/` (misses: cases 13 and 18);
- `evaluate` scores 17/24 on `examples/benchmark/extra/` (misses: cases 2, 3, 6, 7, 9, 10 and 24).

The causes of these misses are listed under "Known issues", items 12–18.

## Copyright and license

Copyright 2026 Nícolas Spoel.

Claims Verifier Core is presented under the Spoel Technologies project identity; the rights holder is the author.

Distributed under the Apache License, Version 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE). The software is
provided "as is", without warranties of any kind.
