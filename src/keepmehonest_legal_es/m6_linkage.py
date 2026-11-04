"""M6-B: explicitly selected BOE discovery hit -> M2 article/version evidence.

No arbitrary case-text searches, automatic article inference, legal merits or
legal applicability assessment. Network access requires a separate CLI opt-in.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys

from .evidence import Origin, SourceKind
from .m6_discovery import (BOE_ID, CONTRACT as DISCOVERY_CONTRACT,
                           DiscoveryError, TOPICS, _write_new, build_url)
from .sources.boe import BOEClient, BOEResult
from .sources.transport import FetchError, SecureHTTP

CONTRACT = "keepmehonest-legal-es/m6-boe-article-linkage/v1"
MAX_REPORT_BYTES = 256_000
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class LinkageError(ValueError):
    """Discovery report / explicit selection / returned provenance invalid."""


def _unique_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise LinkageError("duplicate JSON key in discovery report")
        out[key] = value
    return out


def load_discovery_report(path: Path) -> tuple[dict, str]:
    """Read a bounded ordinary file without following a final-component symlink.

    Hash binds the local report bytes, not the original BOE listing response.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        size = os.fstat(stream.fileno()).st_size
        if not stat.S_ISREG(mode) or not 1 <= size <= MAX_REPORT_BYTES:
            raise LinkageError("discovery report must be a bounded regular file")
        raw = stream.read(MAX_REPORT_BYTES + 1)
    if not 1 <= len(raw) <= MAX_REPORT_BYTES:
        raise LinkageError("discovery report exceeds bound")
    try:
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
    except LinkageError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise LinkageError("discovery report is not valid unique-key UTF-8 JSON") from exc
    return report, sha256(raw).hexdigest()


def _iso(value: str, *, future_allowed: bool = False) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise LinkageError("date must be YYYY-MM-DD")
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise LinkageError("invalid calendar date") from exc
    if not future_allowed and result > date.today():
        raise LinkageError("future as-of or publication date is not supported")
    return result


def select(report: dict, *, identifier: str, article: int, as_of: str) -> dict:
    """Validate M6-A listing and one caller-explicit article/date; no network."""
    if (not isinstance(report, dict) or report.get("contract") != DISCOVERY_CONTRACT
            or report.get("mode") != "BOE_DISCOVERY_LIST_METADATA_ONLY"):
        raise LinkageError("not an M6-A discovery report")
    topic = report.get("topic")
    limit, offset = report.get("limit"), report.get("offset")
    if (topic not in TOPICS or type(limit) is not int or type(offset) is not int
            or report.get("query") != TOPICS[topic]
            or report.get("request_url") != build_url(topic, limit, offset)):
        raise LinkageError("noncanonical discovery request")
    if not isinstance(report.get("raw_sha256"), str) or not _SHA.fullmatch(report["raw_sha256"]):
        raise LinkageError("discovery raw response fingerprint invalid")
    try:
        timestamp = datetime.fromisoformat(report["retrieved_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise LinkageError("invalid listing retrieval timestamp") from exc
    coverage = report.get("coverage")
    if (not isinstance(coverage, dict) or coverage.get("exhaustive") is not False
            or coverage.get("searched_collection") != "BOE_CONSOLIDATED_LIST_ONLY"
            or coverage.get("result_total") != "UNKNOWN"
            or report.get("case_text_transmitted") is not False
            or report.get("legal_support_assessed") is not False
            or report.get("legal_accuracy_measured") is not False
            or report.get("rights_cleared") is not False):
        raise LinkageError("discovery report overclaims coverage, privacy or rights")
    candidates = report.get("candidates")
    if (not isinstance(candidates, list) or not 0 <= len(candidates) <= limit
            or type(report.get("candidate_count")) is not int
            or report["candidate_count"] != len(candidates)):
        raise LinkageError("malformed candidate inventory")
    if not isinstance(identifier, str) or not BOE_ID.fullmatch(identifier):
        raise LinkageError("explicit canonical BOE-A identifier required")
    if type(article) is not int or not 1 <= article <= 9999:
        raise LinkageError("explicit article integer 1..9999 required")
    requested = _iso(as_of)
    seen = set()
    selected = None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise LinkageError("malformed candidate")
        cid = candidate.get("identifier")
        if not isinstance(cid, str) or not BOE_ID.fullmatch(cid) or cid in seen:
            raise LinkageError("invalid or duplicated candidate identifier")
        seen.add(cid)
        if (candidate.get("official_url") != f"https://www.boe.es/buscar/act.php?id={cid}"
                or candidate.get("candidate_status") != "DISCOVERED_METADATA_ONLY"
                or candidate.get("section_retrieved") is not False
                or candidate.get("legal_applicability") != "NOT_ASSESSED"):
            raise LinkageError("invalid candidate provenance/scope")
        title = candidate.get("title")
        if not isinstance(title, str) or not title.strip() or len(title) > 4000:
            raise LinkageError("invalid candidate title")
        if not isinstance(candidate.get("source_last_updated"), str) or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", candidate["source_last_updated"]):
            raise LinkageError("invalid candidate update timestamp")
        published = _iso(candidate.get("published_on"))
        if cid == identifier:
            selected = candidate
            if requested < published:
                raise LinkageError("as-of date predates discovered norm publication")
    if selected is None:
        raise LinkageError("BOE identifier not present on this discovery page")
    return selected


def plan(report: dict, *, identifier: str, article: int, as_of: str,
         discovery_file_sha256: str) -> dict:
    selected = select(report, identifier=identifier, article=article, as_of=as_of)
    if not isinstance(discovery_file_sha256, str) or not _SHA.fullmatch(discovery_file_sha256):
        raise LinkageError("invalid discovery report fingerprint")
    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_EXPLICIT_SECTION_SELECTION",
        "discovery_report_sha256": discovery_file_sha256,
        "listing_raw_sha256_unreplayed": report["raw_sha256"],
        "identifier": identifier,
        "discovered_title": selected["title"],
        "discovered_published_on": selected["published_on"],
        "article_requested": article,
        "as_of_requested": as_of,
        "network_used": False,
        "section_retrieved": False,
        "section_status": "NOT_FETCHED",
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "rights_cleared": False,
        "coverage_exhaustive": False,
        "note": "Article and as-of date provided explicitly; discovery is not substantive legal relevance.",
    }


def resolve(report: dict, *, identifier: str, article: int, as_of: str,
            discovery_file_sha256: str, client: BOEClient | None = None) -> tuple[dict, str]:
    """Request only M2's explicit article endpoints; return safe report and local text.

    The section text is intentionally NOT in the normal JSON report or stdout.
    """
    base = plan(report, identifier=identifier, article=article, as_of=as_of,
                discovery_file_sha256=discovery_file_sha256)
    boe = client if client is not None else BOEClient()
    result = boe.get_article(identifier, article, as_of)
    if not isinstance(result, BOEResult):
        raise LinkageError("BOE retrieval did not return the M2 provenance contract")
    evidence = result.evidence
    if (evidence.source != SourceKind.BOE or evidence.origin != Origin.OFFICIAL_FETCH
            or evidence.identifier != identifier or not evidence.section_id
            or evidence.section_id != result.block_id
            or evidence.official_url != f"https://www.boe.es/buscar/act.php?id={identifier}#{result.block_id}"
            or result.requested_as_of != as_of or evidence.version_date != result.effective_from
            or result.temporal_status != "CHECK_REQUIRED"
            or not isinstance(evidence.text, str) or not evidence.text.strip()
            or not isinstance(result.raw_sha256, str) or not _SHA.fullmatch(result.raw_sha256)):
        raise LinkageError("BOE article result identity, provenance or version mismatched")
    SecureHTTP.check_url(result.api_url)
    if not result.api_url.endswith(f"/{identifier}/texto/bloque/{result.block_id}"):
        raise LinkageError("unexpected article endpoint")
    if not isinstance(result.limitations, tuple) or not result.limitations:
        raise LinkageError("M2 temporal limitations missing")
    effective = _iso(result.effective_from)
    published = _iso(result.publication_date)
    requested = _iso(as_of)
    if effective > requested or published > requested:
        raise LinkageError("future block version returned for historical as-of date")
    base.update({
        "mode": "BOE_ARTICLE_VERSION_RETRIEVED_DOCUMENTARY_ONLY",
        "network_used": True,
        "section_retrieved": True,
        "section_status": "EXPLICIT_ARTICLE_VERSION_RETRIEVED",
        "section_id": result.block_id,
        "section_official_url": evidence.official_url,
        "section_text_sha256": evidence.sha256,
        "section_text_characters": len(evidence.text),
        "section_text_in_report": False,
        "block_raw_response_sha256": result.raw_sha256,
        "block_api_url": result.api_url,
        "retrieved_at": evidence.retrieved_at,
        "selected_version_effective_from": result.effective_from,
        "selected_version_published_on": result.publication_date,
        "modifying_norm": result.modifying_norm,
        "temporal_status": "CHECK_REQUIRED",
        "rights_cleared": False,
        "legal_applicability": "NOT_ASSESSED",
        "legal_support_assessed": False,
        "legal_accuracy_measured": False,
        "source_universe_completeness": "UNVERIFIABLE",
        "index_response_sealed": False,
        "limitations": [
            *result.limitations,
            "M6-A candidate-list report is local input; its hash does not prove official authenticity.",
            "M2 article index response is not sealed by this operation.",
            "No legal relevance, temporal applicability, validity, rights, or exhaustive coverage assessed.",
        ],
    })
    return base, evidence.text


def _private_output(path: Path, content: dict) -> None:
    if path.is_symlink() or not path.is_absolute():
        raise LinkageError("private evidence output must use a new absolute regular path")
    cwd = Path.cwd().resolve()
    target = path.resolve(strict=False)
    repo_root = next((p for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd)
    if target == repo_root or repo_root in target.parents:
        raise LinkageError("private evidence must be stored outside repository working directory")
    _write_new(path, content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M6-B explicit BOE article/date linkage; no legal applicability conclusion")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "resolve"):
        p = subs.add_parser(name)
        p.add_argument("--discovery-report", required=True, type=Path)
        p.add_argument("--identifier", required=True)
        p.add_argument("--article", required=True, type=int)
        p.add_argument("--as-of", required=True)
        if name == "resolve":
            p.add_argument("--allow-official-network", action="store_true")
            p.add_argument("--output", type=Path)
            p.add_argument("--private-evidence-output", type=Path)
    args = parser.parse_args(argv)
    try:
        source, digest = load_discovery_report(args.discovery_report)
        if args.command == "plan":
            result = plan(source, identifier=args.identifier, article=args.article,
                          as_of=args.as_of, discovery_file_sha256=digest)
        else:
            if not args.allow_official_network:
                raise LinkageError("article retrieval requires --allow-official-network")
            result, text = resolve(source, identifier=args.identifier, article=args.article,
                                   as_of=args.as_of, discovery_file_sha256=digest)
            if (args.private_evidence_output is not None and args.output is not None
                    and args.private_evidence_output.resolve(strict=False) == args.output.resolve(strict=False)):
                raise LinkageError("public report and private evidence must use distinct paths")
            if args.private_evidence_output is not None:
                _private_output(args.private_evidence_output, {
                    "contract": CONTRACT,
                    "mode": "PRIVATE_OFFICIAL_ARTICLE_TEXT_NOT_FOR_PUBLIC_GIT",
                    "identifier": result["identifier"],
                    "section_id": result["section_id"],
                    "effective_from": result["selected_version_effective_from"],
                    "text_sha256": result["section_text_sha256"],
                    "text": text,
                    "rights_cleared": False,
                })
            if args.output is not None:
                _write_new(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (LinkageError, DiscoveryError, FetchError, OSError, ValueError, TypeError) as exc:
        print(f"M6 linkage error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
