"""M6-C1: manual official-HJ identification -> bounded M2 TC section retrieval.

NOT a TC search client. No browser, external binaries, hidden search endpoints,
client data upload, general jurisprudence coverage or legal merits assessment.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys

from .evidence import Origin, SourceKind
from .m6_discovery import _write_new
from .m6_linkage import _private_output
from .sources.tc import TCClient, TCResult
from .sources.transport import FetchError, SecureHTTP

CONTRACT = "keepmehonest-legal-es/m6-tc-manual-linkage/v1"
SEARCH_PAGE = "https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index"
ECLI_SENTENCE = re.compile(r"ECLI:ES:TC:(\d{4}):([1-9]\d*)\Z")
SECTION = re.compile(r"FJ[1-9]\d?\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TOPICS = ("constitucional", "administrativo", "laboral", "proteccion_datos", "civil")


class TCLinkageError(ValueError):
    """Manual selection invalid or official identity/provenance inconsistent."""


def _selected(ecli: str, hj_id: int, section: str, topic: str) -> tuple[int, int, str]:
    if not isinstance(ecli, str) or len(ecli) > 50:
        raise TCLinkageError("explicit canonical TC ECLI required")
    match = ECLI_SENTENCE.fullmatch(ecli)
    if match is None or int(match.group(1)) > date.today().year:
        raise TCLinkageError("only explicit numeric TC sentence ECLI supported")
    if type(hj_id) is not int or not 1 <= hj_id <= 999_999_999:
        raise TCLinkageError("explicit positive HJ document ID required")
    if not isinstance(section, str) or not (SECTION.fullmatch(section) or section == "FALLO"):
        raise TCLinkageError("explicit section FJ1..FJ99 or FALLO required")
    if topic not in TOPICS:
        raise TCLinkageError("topic must be a fixed, public legal category")
    return int(match.group(1)), int(match.group(2)), section


def plan(*, ecli: str, hj_id: int, section: str, topic: str) -> dict:
    """Prepare one user-supplied identifier without network or search assertions."""
    _selected(ecli, hj_id, section, topic)
    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_MANUAL_TC_SELECTION",
        "discovery_method": "MANUAL_OFFICIAL_HJ_SEARCH_USER_SUPPLIED_ID",
        "search_page": SEARCH_PAGE,
        "topic": topic,
        "ecli": ecli,
        "hj_document_id": hj_id,
        "section_id": section,
        "official_resolution_url": f"https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/{hj_id}",
        "requested_json_url": f"https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/{hj_id}",
        "user_supplied_pair_verified": False,
        "network_used": False,
        "section_retrieved": False,
        "source_text_in_report": False,
        "case_text_transmitted": False,
        "coverage": {
            "tc_general_search_automated": False,
            "search_executed_by_tool": False,
            "manual_search_results_total": "UNVERIFIABLE",
            "searched_corpus_completeness": "UNVERIFIABLE",
            "exhaustive": False,
            "ordinary_courts": "NOT_SEARCHED_CENDOJ_DISABLED",
            "eu_regional_other_sources": "NOT_SEARCHED",
            "not_found_is_not_no_authority": True,
        },
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "rights_cleared": False,
        "legal_accuracy_measured": False,
        "note": "User-selected HJ resolution ID and ECLI are not an automatically discovered result or an exhaustive search.",
    }


def resolve(*, ecli: str, hj_id: int, section: str, topic: str,
            client: TCClient | None = None) -> tuple[dict, str]:
    """Retrieve exactly one M2 TC section by user-supplied ECLI/HJ ID."""
    year, number, _ = _selected(ecli, hj_id, section, topic)
    base = plan(ecli=ecli, hj_id=hj_id, section=section, topic=topic)
    result = (client if client is not None else TCClient()).get_section(ecli, hj_id, section)
    if not isinstance(result, TCResult):
        raise TCLinkageError("official TC client did not return M2 provenance contract")
    evidence = result.evidence
    expected_url = base["requested_json_url"]
    SecureHTTP.check_url(result.api_url)
    if (result.hj_document_id != hj_id or result.api_url != expected_url
            or evidence.source != SourceKind.TC or evidence.origin != Origin.OFFICIAL_FETCH
            or evidence.identifier != ecli or evidence.section_id != section
            or evidence.official_url != base["official_resolution_url"]
            or not isinstance(evidence.text, str) or not evidence.text.strip()
            or not isinstance(result.raw_sha256, str) or not HEX_SHA256.fullmatch(result.raw_sha256)
            or not isinstance(evidence.sha256, str) or not HEX_SHA256.fullmatch(evidence.sha256)
            or not isinstance(result.limitations, tuple) or not result.limitations):
        raise TCLinkageError("TC source identity or response provenance inconsistent")
    if not isinstance(evidence.decision_date, str):
        raise TCLinkageError("TC decision date absent")
    try:
        decided = date.fromisoformat(evidence.decision_date)
    except ValueError as exc:
        raise TCLinkageError("TC decision date invalid") from exc
    if decided.year != year or decided > date.today():
        raise TCLinkageError("TC decision date inconsistent with ECLI")
    if evidence.title != f"SENTENCIA {number}/{year}":
        raise TCLinkageError("TC sentence title inconsistent with ECLI")
    if not evidence.retrieved_at:
        raise TCLinkageError("TC retrieval timestamp absent")
    base.update({
        "mode": "TC_SECTION_RETRIEVED_DOCUMENTARY_ONLY",
        "network_used": True,
        "section_retrieved": True,
        "user_supplied_pair_verified": True,
        "decision_date": evidence.decision_date,
        "retrieved_at": evidence.retrieved_at,
        "raw_response_sha256": result.raw_sha256,
        "section_text_sha256": evidence.sha256,
        "section_text_characters": len(evidence.text),
        "source_text_in_report": False,
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "legal_accuracy_measured": False,
        "rights_cleared": False,
        "limitations": [
            *result.limitations,
            "Manual identifier selection is not a measured or automated jurisprudence search.",
            "One extracted FJ or fallo is not the full resolution, doctrine, ratio or later case-law context.",
            "No external reuse rights, legal support, relevance or corpus completeness evaluated.",
        ],
    })
    return base, evidence.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M6-C1 manual official TC discovery -> verified section; no automated search")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "resolve"):
        cmd = subs.add_parser(name)
        cmd.add_argument("--ecli", required=True)
        cmd.add_argument("--hj-id", type=int, required=True)
        cmd.add_argument("--section", required=True)
        cmd.add_argument("--topic", required=True, choices=TOPICS)
        if name == "resolve":
            cmd.add_argument("--allow-official-network", action="store_true")
            cmd.add_argument("--output", type=Path)
            cmd.add_argument("--private-evidence-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            report = plan(ecli=args.ecli, hj_id=args.hj_id, section=args.section, topic=args.topic)
        else:
            if not args.allow_official_network:
                raise TCLinkageError("TC source retrieval requires --allow-official-network")
            if (args.private_evidence_output is not None and args.output is not None
                    and args.private_evidence_output.resolve(strict=False) == args.output.resolve(strict=False)):
                raise TCLinkageError("public report and private evidence must use distinct paths")
            report, text = resolve(ecli=args.ecli, hj_id=args.hj_id,
                                   section=args.section, topic=args.topic)
            if args.private_evidence_output is not None:
                _private_output(args.private_evidence_output, {
                    "contract": CONTRACT,
                    "mode": "PRIVATE_OFFICIAL_TC_SECTION_TEXT_NOT_FOR_PUBLIC_GIT",
                    "ecli": report["ecli"],
                    "hj_document_id": report["hj_document_id"],
                    "section_id": report["section_id"],
                    "text_sha256": report["section_text_sha256"],
                    "text": text,
                    "rights_cleared": False,
                })
            if args.output is not None:
                _write_new(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (TCLinkageError, FetchError, OSError, ValueError, TypeError) as exc:
        print(f"M6 TC linkage error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
