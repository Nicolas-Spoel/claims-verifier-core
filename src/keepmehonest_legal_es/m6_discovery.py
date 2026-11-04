"""M6-A: bounded, explicitly requested BOE norm discovery and honest source coverage.

This does NOT search an attorney's argument, infer legal support, retrieve a
particular section, or certify an exhaustive search. CENDOJ/TC search is closed.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from .m5_queue import _read_json, validate_candidates
from .sources.transport import FetchError, Retrieved, SourceUnavailable, _NoRedirect

CONTRACT = "keepmehonest-legal-es/m6-boe-discovery/v1"
BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
# Fixed public legal topics only. No free-text claims, names, DNI or client facts
# enter an outbound request. This taxonomy is intentionally small at M6-A.
TOPICS = {
    "constitucional": "titulo:Constitución",
    "administrativo": "titulo:procedimiento",
    "laboral": "titulo:trabajadores",
    "proteccion_datos": "titulo:protección",
    "civil": "titulo:civil",
}
BOE_ID = re.compile(r"BOE-A-[0-9]{4}-[0-9]{1,8}\Z")
BOE_DATE = re.compile(r"[0-9]{8}\Z")
BOE_UPDATE = re.compile(r"[0-9]{8}T[0-9]{6}Z\Z")
MAX_BYTES = 2_000_000
MAX_LIMIT = 20
MAX_OFFSET = 100


class DiscoveryError(ValueError):
    """Invalid query, official response or incomplete inventory."""


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise DiscoveryError("duplicate JSON key")
        out[key] = value
    return out


def _query(topic: str) -> dict:
    if type(topic) is not str or topic not in TOPICS:
        raise DiscoveryError("topic not in public-law allowlist")
    return {"query": {"query_string": {"query": TOPICS[topic]}, "range": {}}, "sort": []}


def build_url(topic: str, limit: int = 5, offset: int = 0) -> str:
    query = _query(topic)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise DiscoveryError("limit must be 1..20")
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET or offset % limit:
        raise DiscoveryError("offset must be an aligned integer in 0..100")
    params = urlencode({
        "query": json.dumps(query, ensure_ascii=False, separators=(",", ":")),
        "offset": offset,
        "limit": limit,
    })
    return f"{BASE}?{params}"


class BOESearchTransport:
    """Single purpose HTTPS transport; existing SecureHTTP rules remain unchanged."""

    def __init__(self, timeout: float = 12.0):
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
            raise ValueError("invalid timeout")
        self.timeout = timeout
        self._opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

    @staticmethod
    def check_url(url: str) -> None:
        if not isinstance(url, str) or len(url) > 1200:
            raise DiscoveryError("invalid BOE discovery URL")
        p = urlsplit(url)
        if (p.scheme != "https" or p.netloc != "www.boe.es" or p.path !=
                "/datosabiertos/api/legislacion-consolidada" or p.fragment):
            raise DiscoveryError("only exact BOE listing endpoint is permitted")
        try:
            fields = parse_qs(p.query, strict_parsing=True, max_num_fields=3)
        except ValueError as exc:
            raise DiscoveryError("invalid search parameters") from exc
        if set(fields) != {"query", "offset", "limit"} or any(len(v) != 1 for v in fields.values()):
            raise DiscoveryError("invalid or repeated search parameters")
        try:
            obj = json.loads(fields["query"][0], object_pairs_hook=_no_duplicate_keys)
            topic = next(t for t in TOPICS if obj == _query(t))
            limit_text, offset_text = fields["limit"][0], fields["offset"][0]
            if not re.fullmatch(r"[0-9]{1,3}", limit_text) or not re.fullmatch(r"[0-9]{1,3}", offset_text):
                raise ValueError("invalid pagination")
            limit, offset = int(limit_text), int(offset_text)
        except (ValueError, TypeError, StopIteration, KeyError) as exc:
            raise DiscoveryError("noncanonical or unapproved discovery query") from exc
        if url != build_url(topic, limit=limit, offset=offset):
            raise DiscoveryError("noncanonical discovery URL rejected")

    def get(self, url: str, *, accept: str = "application/json") -> Retrieved:
        self.check_url(url)
        if accept != "application/json":
            raise DiscoveryError("BOE discovery supports JSON only")
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "KeepMeHonest-Research/0.3 (read-only; contact: nicholasspoel@gmail.com)",
        }, method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise SourceUnavailable("BOE discovery response/redirect refused")
                ctype = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
                if ctype != "application/json":
                    raise SourceUnavailable("BOE discovery content type invalid")
                body = response.read(MAX_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SourceUnavailable(f"BOE discovery unavailable ({type(exc).__name__}); no negative legal inference") from exc
        if not body or len(body) > MAX_BYTES:
            raise SourceUnavailable("BOE discovery response empty or too large")
        from datetime import datetime, timezone
        return Retrieved(url, body, "application/json", sha256(body).hexdigest(),
                         datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _valid_date(value: object) -> str:
    if not isinstance(value, str) or not BOE_DATE.fullmatch(value):
        raise DiscoveryError("BOE response missing canonical publication date")
    try:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8])).isoformat()
    except ValueError as exc:
        raise DiscoveryError("BOE response date invalid") from exc


def _candidate(record: object) -> dict:
    if not isinstance(record, dict):
        raise DiscoveryError("BOE result is not an object")
    identifier = record.get("identificador")
    if not isinstance(identifier, str) or not BOE_ID.fullmatch(identifier):
        raise DiscoveryError("BOE result identifier invalid")
    title = record.get("titulo")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 4000:
        raise DiscoveryError("BOE result title missing or too long")
    updated = record.get("fecha_actualizacion")
    if not isinstance(updated, str) or not BOE_UPDATE.fullmatch(updated):
        raise DiscoveryError("BOE result update timestamp invalid")
    official_url = f"https://www.boe.es/buscar/act.php?id={identifier}"
    if "url_html_consolidada" in record and record["url_html_consolidada"] != official_url:
        raise DiscoveryError("BOE result locator mismatches identifier")
    return {
        "identifier": identifier,
        "title": title.strip(),
        "published_on": _valid_date(record.get("fecha_publicacion")),
        "source_last_updated": updated,
        "official_url": official_url,
        "candidate_status": "DISCOVERED_METADATA_ONLY",
        "section_retrieved": False,
        "legal_applicability": "NOT_ASSESSED",
    }


def parse_listing(response: Retrieved, *, topic: str, limit: int, offset: int) -> dict:
    url = build_url(topic, limit, offset)
    if response.url != url or not isinstance(response.body, bytes) or len(response.body) > MAX_BYTES:
        raise DiscoveryError("BOE discovery response does not match request")
    if sha256(response.body).hexdigest() != response.sha256:
        raise DiscoveryError("BOE discovery body hash mismatch")
    if response.content_type != "application/json":
        raise DiscoveryError("BOE discovery response is not JSON")
    try:
        payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise DiscoveryError("BOE discovery JSON malformed") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict):
        raise DiscoveryError("BOE discovery status missing")
    code = payload["status"].get("code")
    if type(code) not in (str, int) or str(code) != "200":
        raise SourceUnavailable("BOE discovery status not successful; no conclusion about legal sources")
    data = payload.get("data")
    if data == {}:  # Documented empty JSON payload from AEBOE.
        data = []
    if not isinstance(data, list) or len(data) > limit:
        raise DiscoveryError("BOE response malformed or exceeds requested page size")
    items = [_candidate(r) for r in data]
    identifiers = [r["identifier"] for r in items]
    if len(set(identifiers)) != len(identifiers):
        raise DiscoveryError("duplicate BOE result identifier")
    return {
        "contract": CONTRACT,
        "mode": "BOE_DISCOVERY_LIST_METADATA_ONLY",
        "topic": topic,
        "query": TOPICS[topic],
        "limit": limit,
        "offset": offset,
        "request_url": url,
        "raw_sha256": response.sha256,
        "retrieved_at": response.retrieved_at,
        "candidate_count": len(items),
        "candidates": items,
        "coverage": {
            "searched_collection": "BOE_CONSOLIDATED_LIST_ONLY",
            "result_total": "UNKNOWN",
            "exhaustive": False,
            "more_pages_possible": len(items) == limit,
            "tc_general_discovery": "NOT_PERFORMED_NO_APPROVED_SEARCH_CONTRACT",
            "ordinary_courts": "NOT_SEARCHED_ACCESS_UNAUTHORIZED",
            "regional_eu_and_nonconsolidated": "NOT_SEARCHED",
            "not_found_is_not_no_authority": True,
            "source_recency_and_vigencia": "NOT_ASSESSED",
            "note": "Listing is a bounded discovery page; each candidate requires section retrieval, contextual review and date assessment.",
        },
        "case_text_transmitted": False,
        "legal_support_assessed": False,
        "rights_cleared": False,
        "legal_accuracy_measured": False,
    }


def search(topic: str, *, limit: int = 5, offset: int = 0,
           transport: BOESearchTransport | None = None) -> dict:
    url = build_url(topic, limit=limit, offset=offset)
    client = transport if transport is not None else BOESearchTransport()
    return parse_listing(client.get(url, accept="application/json"),
                         topic=topic, limit=limit, offset=offset)


def inventory(corpus: object) -> dict:
    stats = validate_candidates(corpus)
    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_SOURCE_COVERAGE_PLAN",
        "pilot_cases": stats["total_candidates"],
        "known_document_identifiers": stats["source_identifiers"],
        "known_section_clusters": stats["unique_source_section_clusters"],
        "candidate_corpus_sha256": stats["corpus_sha256"],
        "not_sourced_from_this_plan": True,
        "source_universe_completeness": "UNVERIFIABLE",
        "boe_discovery": "AVAILABLE_ONLY_ON_EXPLICIT_OPT_IN",
        "tc_general_discovery": "NOT_IMPLEMENTED",
        "cendoj": "DISABLED",
        "regional_eu_and_nonconsolidated": "OUT_OF_SCOPE",
        "legal_accuracy_measured": False,
        "expert_gold_cases": 0,
        "note": "Known cited authorities are not an exhaustive inventory of potentially applicable law.",
    }


def _write_new(path: Path, report: dict) -> None:
    if not path.is_absolute() or path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise DiscoveryError("output must be a new file under an existing directory")
    data = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M6-A scoped BOE discovery and explicit coverage accounting")
    subs = parser.add_subparsers(dest="command", required=True)
    p_plan = subs.add_parser("plan", help="offline known-authority inventory")
    p_plan.add_argument("--candidates", type=Path, required=True)
    p_search = subs.add_parser("search", help="metadata-only official BOE search")
    p_search.add_argument("--topic", required=True, choices=sorted(TOPICS))
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--offset", type=int, default=0)
    p_search.add_argument("--allow-official-network", action="store_true")
    p_search.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            report = inventory(_read_json(args.candidates))
        else:
            if not args.allow_official_network:
                raise DiscoveryError("network search requires --allow-official-network")
            report = search(args.topic, limit=args.limit, offset=args.offset)
            if args.output is not None:
                _write_new(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DiscoveryError, FetchError, OSError, TypeError, ValueError) as exc:
        print(f"M6 discovery error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
