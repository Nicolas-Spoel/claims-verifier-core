# KeepMeHonest — Spanish Legal Edition (M1, experimental)

This is a legal-domain add-on to the original Claims Verifier Core v0.1.1, **not** a legal-advice or automated legal-truth engine. Original Core package and public APIs remain untouched. Copyright and notices stay as upstream Apache-2.0.

## Implemented in M1

- A strict, immutable `LegalEvidence` envelope including authority, exact reference, section, version or decision date, official link, text digest and declared origin.
- Explicit recognition of `BOE-A-...`, `ECLI:ES:...` and `Roj: STS .../...`. No claim of resolving generic abbreviations (`art. 24 CE`) or proof that an identifier exists.
- A conservative `review_claim(...)` with literal-quotation and identifier checks. Even when both match, the state is `REVIEW_REQUIRED`, **never `LEGALLY_CORRECT` or automatic legal `SUPPORTED`**. With an exact mismatch the state is `BLOCKED`.
- `to_core_document(...)` and optional `run_core=True`: the Core lexical verdict is explicitly separate from the legal review result.
- Small offline tests using synthetic text. No remote requests are made.

## Not implemented / blocked

- Live BOE/TC retrieval, official-content authentication, and historical validation: **not implemented in M1**.
- Automatic CENDOJ retrieval: **blocked pending documented authorized access**.
- Legal interpretation, precedent hierarchy, obiter vs ratio, jurisdiction, applicability to the client's facts, and multistep semantic entailment: **not assessed**.
- Real client documents: **not authorized** for this experimental module.

A URL or a claimed `OFFICIAL_FETCH` origin never proves that text is authentic. All external data must be independently checked before trust is upgraded. Date metadata is NOT verification that a norm was in force on that date.

## Run in the fork root

```bash
PYTHONPATH=src python -m unittest discover -s tests/legal_es -p 'test_*.py' -v
PYTHONPATH=src python examples/legal_es/demo_offline.py
# existing Core tests remain runnable:
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
```

## API

```python
from keepmehonest_legal_es import LegalEvidence, SourceKind, Origin, review_claim

source = LegalEvidence(
    source=SourceKind.BOE,
    identifier="BOE-A-1978-31229", section_id="art24",
    text="TEXTO SINTÉTICO — no es contenido del BOE",
    title="Fixture de prueba",
    official_url="https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229",
    version_date="2026-01-01", origin=Origin.TEST_FIXTURE,
)
result = review_claim("Referencia BOE-A-1978-31229", source)
assert result.status == "REVIEW_REQUIRED"
assert result.authenticity == "NOT_ASSESSED"
```

## Sources / policy

- BOE open-data API: https://www.boe.es/datosabiertos/api/api.php
- BOE consolidated legislation is informational and should be identified as such: https://www.boe.es/datosabiertos/faq/consolidada.php
- Tribunal Constitucional HJ search: https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index
- September 2026 previous prototype `public_mcp_v08.py` requires `public_mcp_v07.py`, `citations.py`, `jurisprudence/common.py`, `jurisprudence/tc.py` and `jurisprudence/cendoj.py`. Do not copy incomplete code or claim the old system is running.

## Next gate: M2

Import and adapt **only** verified source modules, write fixture-based source-contract tests, check BOE response and TC section locators, and revalidate confidentiality and retrieval conditions. Preserve distinction between `search_case_law` discovery and `get_case_law` grounded sections. CENDOJ remains explicitly unavailable.
