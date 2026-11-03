"""Serialization of a ``VerificationReport`` to JSON-ready dicts and Markdown."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

from .models import ClaimResult, PassageAssessment, Verdict, VerificationReport

SCHEMA_VERSION = "2.0"
SCORE_SEMANTICS = (
    "score: heuristic strength of the deciding evidence in [0, 1], for ordering and triage only; "
    "it is NOT a calibrated probability that the claim is true, and it is null for abstentions."
)
_C1_RE = re.compile(r"[\x7f-\x9f\u2028\u2029]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# Interpolated fields never start a line, so only inline metacharacters need escaping.
_MD_META_RE = re.compile(r"([\\`*_\[\]()!|~])")
QUOTE_MAX_CHARS = 280
REVIEW_VERDICTS = frozenset(
    {
        Verdict.CONTRADICTED,
        Verdict.CONFLICTING,
        Verdict.PARTIALLY_SUPPORTED,
        Verdict.INCONCLUSIVE,
        Verdict.NOT_ENOUGH_EVIDENCE,
    }
)
VERDICT_LABELS = {
    Verdict.SUPPORTED: "✅ Supported",
    Verdict.PARTIALLY_SUPPORTED: "🟡 Partially supported",
    Verdict.CONTRADICTED: "❌ Contradicted",
    Verdict.CONFLICTING: "⚠️ Conflicting sources",
    Verdict.INCONCLUSIVE: "⏸️ Inconclusive (abstention)",
    Verdict.NOT_ENOUGH_EVIDENCE: "❔ Not enough evidence",
}
STANCE_LABELS = {
    "supports": "supports",
    "partial": "partially supports",
    "contradicts": "contradicts",
    "ambiguous": "related, does not decide",
}


def summarize(report: VerificationReport) -> dict[str, Any]:
    counts = Counter(r.verdict.value for r in report.results)
    cited = {e.passage.doc_id for r in report.results for e in r.evidence}
    total = len(report.results)
    with_evidence = sum(1 for r in report.results if r.verdict is not Verdict.NOT_ENOUGH_EVIDENCE)
    return {
        "total_claims": total,
        "by_verdict": {v.value: counts.get(v.value, 0) for v in Verdict},
        "needs_review": sum(1 for r in report.results if r.verdict in REVIEW_VERDICTS),
        "skipped_segments": len(report.skipped),
        "unchecked_factual_segments": sum(1 for s in report.skipped if s.factual),
        "claims_with_related_evidence": round(with_evidence / total, 2) if total else 0.0,
        "documents_cited": sorted(cited),
        "documents_not_cited": sorted(d.doc_id for d in report.documents if d.doc_id not in cited),
    }


def _sources(report: VerificationReport) -> dict[str, Any]:
    """Received / examined / excluded sources and completeness against an expected inventory."""
    records = [
        {"path": r.path, "status": r.status.value, "reason": r.reason, "doc_ids": list(r.doc_ids), "sha256": r.sha256}
        for r in report.sources
    ]
    if report.accounting is not None:
        accounting = report.accounting.to_dict()
    else:
        accounting = {"completeness": "unverifiable", "expected": None}
    return {
        "received": len(records) if records else None,
        "examined": sum(1 for r in records if r["status"] == "examined") if records else len(report.documents),
        "excluded": [r for r in records if r["status"] == "excluded"],
        "records": records,
        "accounting": accounting,
        "note": "Completeness can only be verified against an expected inventory (--expected); "
        "documents never supplied to the verifier are unknown to it.",
    }


def _evidence_dict(item: PassageAssessment, report: VerificationReport) -> dict[str, Any]:
    passage = item.passage
    doc = next(d for d in report.documents if d.doc_id == passage.doc_id)
    return {
        "stance": item.stance.value,
        "doc_id": passage.doc_id,
        "document_title": doc.title,
        "document_date": doc.date,
        "source_path": doc.source_path,
        "document_sha256": doc.sha256,
        "document_version": doc.metadata.get("version"),
        "source_in_expected_inventory": report.accounting.is_expected(doc.source_path) if report.accounting else None,
        "passage_sha256": hashlib.sha256(passage.text.encode("utf-8")).hexdigest(),
        "passage_id": passage.passage_id,
        "line": passage.line,
        "char_span": [passage.char_start, passage.char_end],
        "quote": doc.text[passage.char_start:passage.char_end],
        "relevance": item.relevance,
        "retrieval_score": item.retrieval_score,
        "signals": [{"code": s.code, "detail": s.detail} for s in item.signals],
        "matched_terms": list(item.matched_terms),
        "missing_terms": list(item.missing_terms),
    }


def _result_dict(result: ClaimResult, report: VerificationReport) -> dict[str, Any]:
    return {
        "claim_id": result.claim.claim_id,
        "text": result.claim.text,
        "char_span": None if result.claim.char_start is None else [result.claim.char_start, result.claim.char_end],
        "verdict": result.verdict.value,
        "score": result.score,
        "score_kind": "heuristic_uncalibrated",
        "rationale": result.rationale,
        "uncertainty": [{"code": s.code, "detail": s.detail} for s in result.uncertainty],
        "terms_absent_from_corpus": list(result.terms_absent_from_corpus),
        "evidence": [_evidence_dict(e, report) for e in result.evidence],
        "examined": {
            "passages": len(result.examined),
            "documents": sorted(result.examined_documents),
        },
    }


def to_dict(report: VerificationReport) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": dict(report.engine),
        "corpus": {
            "fingerprint": report.corpus_fingerprint,
            "passages": report.passage_count,
            "documents": [
                {"doc_id": d.doc_id, "title": d.title, "date": d.date, "source_path": d.source_path, "sha256": d.sha256}
                for d in report.documents
            ],
        },
        "sources": _sources(report),
        "search": dict(report.search),
        "score_semantics": SCORE_SEMANTICS,
        "summary": summarize(report),
        "claims": [_result_dict(r, report) for r in report.results],
        "skipped": [
            {"text": s.text, "char_span": [s.char_start, s.char_end], "reason": s.reason, "unchecked_factual": s.factual}
            for s in report.skipped
        ],
        "limitations": list(report.limitations),
    }


def to_json(report: VerificationReport) -> str:
    text = json.dumps(to_dict(report), ensure_ascii=False, indent=2) + "\n"
    # json escapes C0 controls but not C1 (U+0080–U+009F) or line separators: escape them too.
    return _C1_RE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", text)


def _md(text: str | None) -> str:
    """Escape untrusted text (quotes, ids, paths, dates) so it renders literally in Markdown.

    Control characters and newlines are flattened, HTML is entity-encoded and every
    Markdown metacharacter is backslash-escaped, so no link, image or heading can be injected.
    """
    flat = " ".join(_CONTROL_RE.sub(" ", text or "").split())
    flat = flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _MD_META_RE.sub(r"\\\1", flat)


def _quote(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= QUOTE_MAX_CHARS else flat[: QUOTE_MAX_CHARS - 1] + "…"


def _markdown_claim(result: dict[str, Any]) -> list[str]:
    verdict = Verdict(result["verdict"])
    score = "" if result["score"] is None else f" (heuristic score {result['score']:.2f}, not a probability)"
    examined = result["examined"]
    lines = [
        f"### {_md(result['claim_id'])} · {VERDICT_LABELS[verdict]}{score}",
        "",
        f"> {_md(result['text'])}",
        "",
        f"{_md(result['rationale'])}",
        "",
    ]
    if result["uncertainty"]:
        lines.append("**Uncertainty and limitations:**")
        lines.extend(f"- `{u['code']}` — {_md(u['detail'])}" for u in result["uncertainty"])
        lines.append("")
    for ev in result["evidence"]:
        signals = ", ".join(f"`{s['code']}` {_md(s['detail'])}" for s in ev["signals"]) or "term match"
        date = f", {_md(ev['document_date'])}" if ev["document_date"] else ""
        lines.append(
            f"- **{STANCE_LABELS.get(ev['stance'], ev['stance'])}** — {_md(ev['source_path'])} "
            f"line {ev['line']} ({_md(ev['passage_id'])}{date}; relevance {ev['relevance']:.2f}): "
            f"“{_md(_quote(ev['quote']))}” — {signals}"
        )
    lines.append(
        f"_Examined: {examined['passages']} passages from "
        f"{', '.join(_md(d) for d in examined['documents']) or 'no documents'}._"
    )
    lines.append("")
    return lines


def _markdown_sources(sources: dict[str, Any], search: dict[str, Any]) -> list[str]:
    accounting = sources["accounting"]
    completeness = {
        "complete": "complete against the expected inventory (paths and versions verified)",
        "complete_unversioned": "paths complete, but versions not verified (some inventory entries have no hash)",
        "unexpected_sources": "NOT complete: sources outside the expected inventory were examined",
        "incomplete": "incomplete against the expected inventory",
        "unverifiable": "unverifiable (no expected inventory was provided)",
    }[accounting["completeness"]]
    received = "in memory" if sources["received"] is None else str(sources["received"])
    lines = [
        "## Corpus provenance and coverage",
        "",
        f"- Received: {received} · examined: {sources['examined']} · excluded: {len(sources['excluded'])}",
        f"- Corpus completeness: **{completeness}**",
    ]
    if accounting.get("expected") is not None:
        lines.append(
            f"- Expected: {accounting['expected']} · missing: {', '.join(map(_md, accounting['missing'])) or 'none'}"
            f" · version mismatch: {', '.join(map(_md, accounting['version_mismatch'])) or 'none'}"
            f" · expected but excluded: {', '.join(map(_md, accounting['excluded_expected'])) or 'none'}"
            f" · received but not expected: {', '.join(map(_md, accounting['unexpected'])) or 'none'}"
        )
    lines.extend(f"- Excluded {_md(x['path'])}: {_md(x['reason'])}" for x in sources["excluded"])
    if search:
        lines.append(
            f"- Search: {_md(str(search.get('method')))}, {search.get('top_k')} passages per claim; "
            "“no evidence” refers to what was examined, not to the whole corpus"
        )
    lines.append("")
    return lines


def to_markdown(report: VerificationReport) -> str:
    data = to_dict(report)
    summary = data["summary"]
    lines = [
        "# Claim verification report",
        "",
        f"Engine `{data['engine']['name']} {data['engine']['version']}` · judge `{data['engine']['judge']}` · "
        f"corpus `{data['corpus']['fingerprint'][:12]}` ({len(data['corpus']['documents'])} documents, "
        f"{data['corpus']['passages']} passages)",
        "",
        "## Summary",
        "",
        "| Verdict | Claims |",
        "|---|---|",
        *(f"| {VERDICT_LABELS[Verdict(v)]} | {n} |" for v, n in summary["by_verdict"].items()),
        f"| **Total** | **{summary['total_claims']}** |",
        "",
        f"- Need review: **{summary['needs_review']}** of {summary['total_claims']}",
        f"- Claims with related evidence: {summary['claims_with_related_evidence']:.0%} "
        "(does not imply that the corpus is complete)",
        f"- Unverifiable segments skipped: {summary['skipped_segments']}"
        f" (with factual content NOT verified: **{summary['unchecked_factual_segments']}**)",
        f"- Documents not cited: {', '.join(_md(d) for d in summary['documents_not_cited']) or 'none'}",
        "",
        "## Claims",
        "",
    ]
    for result in data["claims"]:
        lines.extend(_markdown_claim(result))
    if data["skipped"]:
        lines.extend(["## Skipped segments", ""])
        lines.extend(f"- `{s['reason']}`{' · **UNCHECKED**' if s['unchecked_factual'] else ''} — {_md(s['text'])}"
                     for s in data["skipped"])
        lines.append("")
    lines.extend(_markdown_sources(data["sources"], data["search"]))
    lines.extend(["## Verifier limitations", ""])
    lines.extend(f"- {_md(item)}" for item in data["limitations"])
    return "\n".join(lines) + "\n"
