# M5-D — Pilot source spot-check notes (not legal expert annotations)

**Prepared 2026-11-04; source-only comparison.** The underlying original bytes stored on the operator's Mac were **not** available for independent inspection here. No expert reviewer assessed these cases. The observations below are not `DIRECT_SUPPORT`, `CONTRADICTED` or other expert gold labels and do not make claims about clients' legal facts or outcomes.

## PUB-M5-001 — art. 24 CE

- **AI-written proposition:** «El artículo 24 CE obliga a admitir cualquier prueba ofrecida por una parte sin analizar su pertinencia».
- **Hypothetical date:** 2023-09-12; no actual client facts.
- **Public locator:** https://www.boe.es/buscar/doc.php?id=BOE-A-1978-31229 , article 24.2; separately https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229 for informational consolidated view.
- **Public-source observation:** Article 24.2 expressly qualifies the right to evidence with **pertinencia**. Thus the unrestricted expression «cualquier prueba» does not follow from the cited wording alone. This is a documented review concern, **not** an adjudicated legal label. A full legal assessment would consider admissibility rules and constitutional case-law.
- **Not checked:** actual local `boe-001` raw bytes against the publisher's publication; permissions for republishing the captured article; applicability in a particular procedural setting; expert review.

## PUB-M5-032 — STC 1/2024, FJ1

- **AI-written proposition:** «El FJ1 de la STC 1/2024 contiene por sí solo toda la motivación sobre la suficiencia de la investigación penal».
- **Hypothetical date:** 2024-01-15; no actual client facts.
- **Public locator:** https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/30062 ; JSON locator https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/30062 .
- **Public-source observation:** FJ1 delimits the constitutional appeal and discusses its special importance. FJ2 reviews the constitutional jurisprudence, FJ3 extends the doctrine to other circumstances and FJ4 applies the doctrine to the case. Therefore limiting the whole motivation to FJ1 ignores the structure of the decision. This is a documented source-coverage concern, **not** an adjudicated legal label.
- **Not checked:** actual local `tc-032` raw bytes against the official site; the full private capture chain; rights for reuse or publication; subsequent jurisprudence; expert review.

## What the software must report

- These candidates are `AI_DRAFT_HYPOTHETICAL_PUBLIC_LOCATOR`, not expert-authored gold.
- Both are **eligible for a local technical freeze only** if the corresponding M5-B raw/section snapshots replay exactly.
- `expert_gold_cases=0`, `rights_cleared=0`, `legal_accuracy_measured=false` even when both snapshots replay successfully.
- Do not publish private captures or copy official case-law text into the repository solely because the materials are publicly accessible.
