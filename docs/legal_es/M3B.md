# KeepMeHonest legal-es / M3-B — Context and scope review indicators

**Research prototype only.** Depends on the M3-A changes applied to the local fork. No confidential cases, autonomous legal opinions, legal truth judgments or production authorization.

## Goal

M3-A matched a claim to an **explicit** source identifier, exact section, and optionally one exact quotation. M3-B conservatively records the *parent sentence* of each extracted claim, other sibling clause numbers, and references appearing only elsewhere in the sentence. **A reference in a sibling clause is never an evidentiary link for the present claim.** This repairs the auditability problem in the M3-A example without pretending to solve reference resolution.

M3-B additionally flags limited review cues: absolute assertions (`siempre`, `nunca`, `sin excepción` etc.) in non-quoted claim text; claims about normative temporal status; potential conditions/exceptions inside a **matched evidence section**; BOE version dates versus requested retrieval dates; and TC ratio/procedural/later-judgment gaps. These are *lexical review indicators*, not semantic verification, not a score, not proof of contradictions, and not a judgment on legal correctness. A missed cue never means a claim is safe or legally supported.

## Contract (report v0.3.1)

The existing keys remain intact. Every `claims[i]` gains:

- `sentence_context`: original sentence text, exact character span, SHA-256, 1-based sibling claim indices, direct identifiers, sentence-wide identifiers, sentence-only identifiers, and explicit `inherit_documentary_anchor=false`. `context_status=SPAN_UNRESOLVED` if the Core extraction offsets cannot be mapped without guessing.
- `legal_scope_screen`: deterministic `issues` (each with code and provenance basis); linked BOE `version_date` plus distinct `request_date_candidates` *if provided in successful fetch attempt records*, or TC `decision_date`; and `legal_support`, `legal_applicability`, `argument_quality` all `NOT_ASSESSED`.

`coverage.m3b_legal_scope_screen` provides auditable counts, **not** confidence or legal-quality scoring; `legal_support_assessed` must be zero. Existing M3-A `documentary_grounding` and Core `lexical_verdict` remain unchanged. `READY_FOR_HUMAN_REVIEW` stays a workflow state, not approval.

## Explicit limits

1. M3-B does not resolve anaphora, complex cross-sentence citations, implied articles, subsections, conflicting case law, ratio decidendi, legislative interpretation or substantive entailment. `sentence_only_identifiers` is a context hint and must **never** change M3-A `anchor_status` or the `legal_support` field.
2. A cue such as `CITED_SECTION_CONTAINS_SCOPE_QUALIFIER` means a word pattern appears somewhere in the section, not that an exception defeats the specific proposition. Conversely, absence of such cues does not rule out exceptions.
3. A BOE `version_date` is selected from consolidated text metadata and is not proof of legal validity on a claimed date. `request_date_candidates` are user-requested retrieval parameters, not the date of the underlying event, and no temporal applicability conclusion is made. BOE consolidated law is informational, see <https://www.boe.es/datosabiertos/faq/consolidada.php>.
4. TC FJ matching does not determine procedural fit, precedential scope, later constitutional decisions or ratio/obiter.
5. No model or network call in `verify_argument` or M3-B. Network remains optional in the M2 CLI and only receives explicitly supplied source identifiers. CENDOJ remains disabled. User-supplied sources are not independently authenticated.
6. Context excerpts may contain the user's argument text. The local JSON report therefore requires the same confidentiality controls as the original input. Do not share real-client report files publicly.
7. Reliable legal-support classification would require a curated, permission-cleared, expert-annotated evaluation set and viable deployment path. Not in M3-B.

## Gates before publication

1. Run `git apply --check` with the incremental patch on the local working tree with M3-A already applied. Never apply it twice.
2. Execute `PYTHONPATH=src python3 -m unittest discover -s tests/legal_es -p 'test_*.py' -v` and `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` inside the actual fork. Both must pass.
3. Run public, nonconfidential BOE M3-B CLI smoke; check the context split in the third sentence and the warning in the absolute legal assertion. Confirm no claim is upgraded to legal support. Compare the documentary quote against official BOE text.
4. Inspect changed paths and diff; publish **M3-A and M3-B together** to the `Nicolas-Spoel` fork only after gates pass. Do not modify the original SpoelTechnologies Core.

**Temporal provenance detail:** `request_date_candidates` are matched at BOE identifier level only, not at individual block/version level, and are labelled `request_date_scope=IDENTIFIER_LEVEL_NOT_VERIFIED_FOR_SECTION`. They must not be interpreted as a legal effective date or case event date.
