"""M6-C2: bounded TC publication *metadata* discovery via the documented BOE daily-sumario API.

This is NOT the TC HJ search API: it finds only records published in explicitly
requested BOE editions/dates, not all TC resolutions or legal doctrine. No
search terms, client data, document downloads, browser or automatic HJ-ID guesses.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import ssl
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, Request, build_opener

from .sources.transport import Retrieved, SourceUnavailable, _NoRedirect

CONTRACT = "keepmehonest-legal-es/m6-tc-boe-daily-index/v1"
BASE = "https://www.boe.es/datosabiertos/api/boe/sumario/"
MAX_DAYS = 3
MAX_BYTES = 6_000_000
MAX_RECORDS = 1500
BOE_ID = re.compile(r"BOE-A-[0-9]{4}-[1-9][0-9]{0,7}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DECISION = re.compile(r"\b(Sentencia|Auto|Declaraci[oó]n)\s+([1-9][0-9]{0,3})/([0-9]{4})\b", re.IGNORECASE)
ECLI = re.compile(r"ECLI:ES:TC:([0-9]{4}):([1-9][0-9]*)\Z")


class TCBOEIndexError(ValueError):
    """Invalid source payload, unsafe operation or unsupported publication inference."""


def _date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise TCBOEIndexError("date must use YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise TCBOEIndexError("invalid calendar date") from exc
    if day > date.today():
        raise TCBOEIndexError("future BOE publication date is not searchable")
    return day


def _days(start: str, end: str) -> list[date]:
    first, last = _date(start), _date(end)
    span = (last - first).days
    if not 0 <= span < MAX_DAYS:
        raise TCBOEIndexError("date window must contain 1 to 3 consecutive calendar days")
    return [first + timedelta(days=n) for n in range(span + 1)]


def build_url(day: date) -> str:
    if type(day) is not date or day > date.today():
        raise TCBOEIndexError("invalid publication date")
    return BASE + day.strftime("%Y%m%d")


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise TCBOEIndexError("duplicate official JSON key")
        result[key] = value
    return result


def _rows(value: object, name: str, *, required: bool = False) -> list[dict]:
    if value is None and not required:
        return []
    rows = [value] if isinstance(value, dict) else value
    if not isinstance(rows, list) or (required and not rows) or len(rows) > MAX_RECORDS:
        raise TCBOEIndexError(f"BOE {name} missing or malformed")
    if any(not isinstance(record, dict) for record in rows):
        raise TCBOEIndexError(f"BOE {name} includes non-object")
    return rows


def _normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(c))


class BOESummaryTransport:
    """Exact-date official JSON GET only; no redirects, proxies, or arbitrary hosts."""

    def __init__(self, timeout: float = 12.0):
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("timeout outside permitted range")
        self.timeout = timeout
        self._opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), _NoRedirect())

    @staticmethod
    def check_url(url: str) -> None:
        if not isinstance(url, str) or len(url) > 100:
            raise TCBOEIndexError("invalid BOE summary URL")
        p = urlsplit(url)
        if (p.scheme != "https" or p.netloc != "www.boe.es" or p.query or p.fragment
                or not re.fullmatch(r"/datosabiertos/api/boe/sumario/[0-9]{8}", p.path)):
            raise TCBOEIndexError("only exact official BOE summary dates permitted")
        raw_day = p.path.rsplit("/", 1)[-1]
        try:
            day = date(int(raw_day[:4]), int(raw_day[4:6]), int(raw_day[6:]))
        except ValueError as exc:
            raise TCBOEIndexError("invalid summary calendar date") from exc
        if url != build_url(day):
            raise TCBOEIndexError("noncanonical official summary URL")

    def get(self, url: str, *, accept: str = "application/json") -> Retrieved:
        self.check_url(url)
        if accept != "application/json":
            raise TCBOEIndexError("BOE daily summary requires JSON")
        req = Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "KeepMeHonest-Research/0.3 (read-only; contact: nicholasspoel@gmail.com)",
        }, method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise SourceUnavailable("BOE daily summary response/redirect refused")
                ctype = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
                if ctype != "application/json":
                    raise SourceUnavailable("BOE daily summary is not JSON")
                body = response.read(MAX_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SourceUnavailable(f"BOE daily summary unavailable ({type(exc).__name__}); not evidence of no TC decisions") from exc
        if not body or len(body) > MAX_BYTES:
            raise SourceUnavailable("BOE daily summary empty or exceeds size cap")
        return Retrieved(url, body, "application/json", sha256(body).hexdigest(),
                         datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _tc_publication_rows(dept: dict) -> list[dict]:
    """Parse only explicit, bounded TC document containers observed in BOE JSON.

    BOE's 2024-02-20 JSON nests records at
    ``departamento.texto.epigrafe[].item[]``. The intermediate heading is
    structural metadata, not itself a TC document. Do not silently interpret
    unknown structures as an empty publication list.
    """
    present = [field for field in ("texto", "item", "epigrafe")
               if field in dept and dept[field] is not None]
    if len(present) != 1:
        raise TCBOEIndexError("TC department must have one recognised document container")
    field = present[0]
    if field == "epigrafe":
        raise TCBOEIndexError("unexpected TC subheading shape; inspect official schema")
    raw = dept[field]
    if field == "texto" and isinstance(raw, dict):
        if set(raw) == {"item"}:
            raw = raw["item"]
        elif set(raw) == {"epigrafe"}:
            # Observed official JSON route. Permit one or more explicit
            # headings, but not arbitrary nested keys or missing item arrays.
            headings = _rows(raw["epigrafe"], "TC texto epigrafe", required=True)
            collected: list[dict] = []
            for heading in headings:
                if set(heading) != {"nombre", "item"}:
                    raise TCBOEIndexError("ambiguous TC epigrafe structure")
                name = heading["nombre"]
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
                    raise TCBOEIndexError("TC epigrafe heading invalid")
                items = _rows(heading["item"], "TC epigrafe item", required=True)
                collected.extend(items)
                if len(collected) > MAX_RECORDS:
                    raise TCBOEIndexError("TC publication list exceeds safety cap")
            raw = collected
        elif {"identificador", "titulo"} <= set(raw) and not ({"item", "epigrafe"} & set(raw)):
            # Preserve the pre-existing direct-record shape, with ordinary
            # per-document metadata handled by the record validator below.
            pass
        else:
            raise TCBOEIndexError("ambiguous TC texto wrapper")
    rows = _rows(raw, f"TC {field}", required=True)
    if any("identificador" not in record or "titulo" not in record for record in rows):
        raise TCBOEIndexError("unrecognised TC document structure; no coverage inferred")
    return rows


def parse_day(response: Retrieved, *, day: date) -> tuple[dict, list[dict]]:
    """Parse only the dedicated TC publication section; omit potentially personal titles."""
    expected = build_url(day)
    if (not isinstance(response, Retrieved) or response.url != expected
            or response.content_type != "application/json" or type(response.body) is not bytes
            or not response.body or len(response.body) > MAX_BYTES
            or not isinstance(response.sha256, str) or not SHA256.fullmatch(response.sha256)
            or sha256(response.body).hexdigest() != response.sha256):
        raise TCBOEIndexError("BOE summary transport/hash does not match requested date")
    try:
        payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except TCBOEIndexError:
        raise
    except (UnicodeError, ValueError) as exc:
        raise TCBOEIndexError("BOE summary malformed JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict):
        raise TCBOEIndexError("BOE summary status unavailable")
    code = payload["status"].get("code")
    if type(code) not in (int, str) or str(code) != "200":
        raise SourceUnavailable("BOE summary status unsuccessful; no negative inference")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("sumario"), dict):
        raise TCBOEIndexError("BOE summary data missing")
    summary = data["sumario"]
    metadata = summary.get("metadatos")
    if (not isinstance(metadata, dict) or metadata.get("publicacion") != "BOE"
            or metadata.get("fecha_publicacion") != day.strftime("%Y%m%d")):
        raise TCBOEIndexError("BOE summary publication/date identity mismatch")
    candidates: list[dict] = []
    tc_seen = False
    all_ids: set[str] = set()
    for diario in _rows(summary.get("diario"), "diario", required=True):
        for section in _rows(diario.get("seccion"), "seccion", required=True):
            code, name = section.get("codigo"), section.get("nombre")
            if not isinstance(code, str) or not isinstance(name, str):
                raise TCBOEIndexError("BOE section identification missing")
            section_tc = "tribunal constitucional" in _normalized(name)
            if code != "T":
                if section_tc:
                    raise TCBOEIndexError("TC section label/code inconsistent")
                continue
            if not section_tc:
                raise TCBOEIndexError("TC section code/name inconsistent")
            tc_seen = True
            for dept in _rows(section.get("departamento"), "TC departamento", required=True):
                dept_name = dept.get("nombre")
                if not isinstance(dept_name, str) or "tribunal constitucional" not in _normalized(dept_name):
                    raise TCBOEIndexError("TC section department identity inconsistent")
                for record in _tc_publication_rows(dept):
                    if len(candidates) >= MAX_RECORDS:
                        raise TCBOEIndexError("TC publication list exceeds safety cap")
                    identifier, title = record.get("identificador"), record.get("titulo")
                    if (not isinstance(identifier, str) or not BOE_ID.fullmatch(identifier)
                            or not isinstance(title, str) or not title.strip() or len(title) > 4000):
                        raise TCBOEIndexError("TC item identifier/title malformed")
                    if identifier in all_ids:
                        raise TCBOEIndexError("duplicate TC publication identifier")
                    all_ids.add(identifier)
                    # Never transmit or store potentially identifying claimant names from titles.
                    match = DECISION.search(title)
                    label = (f"{match.group(1).lower().capitalize()} {int(match.group(2))}/{match.group(3)}"
                             if match else None)
                    kind = ("SENTENCIA" if match and _normalized(match.group(1)) == "sentencia"
                            else "AUTO" if match and _normalized(match.group(1)) == "auto"
                            else "DECLARACION" if match else "TC_PUBLICATION_UNCLASSIFIED")
                    candidates.append({
                        "identifier": identifier,
                        "publication_date": day.isoformat(),
                        "kind": kind,
                        "resolution_label": label,
                        "official_url": f"https://www.boe.es/diario_boe/txt.php?id={identifier}",
                        "title_omitted_potential_personal_data": True,
                        "ecli": None,
                        "hj_document_id": None,
                        "section_retrieved": False,
                        "legal_applicability": "NOT_ASSESSED",
                    })
    return ({
        "publication_date": day.isoformat(),
        "request_url": expected,
        "raw_sha256": response.sha256,
        "retrieved_at": response.retrieved_at,
        "tc_section_present": tc_seen,
        "tc_publication_items": len(candidates),
        "entire_boe_edition_index_parsed": True,
    }, candidates)


def plan(*, start: str, end: str) -> dict:
    days = _days(start, end)
    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_BOUNDED_TC_BOE_PUBLICATION_PLAN",
        "publication_dates_requested": [d.isoformat() for d in days],
        "official_request_urls": [build_url(d) for d in days],
        "network_used": False,
        "requests_authorized": False,
        "max_requests_per_run": MAX_DAYS,
        "scope": "TC_SECTION_OF_BOE_DAILY_SUMMARIES_ONLY",
        "official_hj_search_automated": False,
        "cendoj": "DISABLED",
        "case_text_transmitted": False,
        "coverage_exhaustive": False,
        "not_found_is_not_no_authority": True,
    }


def search(*, start: str, end: str, transport: BOESummaryTransport | None = None) -> dict:
    days = _days(start, end)
    client = transport if transport is not None else BOESummaryTransport()
    editions: list[dict] = []
    candidates: list[dict] = []
    ids: set[str] = set()
    for day in days:
        edition, discovered = parse_day(client.get(build_url(day), accept="application/json"), day=day)
        for item in discovered:
            if item["identifier"] in ids:
                raise TCBOEIndexError("TC BOE identifier duplicated across requested editions")
            ids.add(item["identifier"])
        editions.append(edition)
        candidates.extend(discovered)
    return {
        "contract": CONTRACT,
        "mode": "BOE_TC_PUBLICATION_INDEX_DISCOVERY_METADATA_ONLY",
        "source_attribution": "Basado en datos de la Agencia Estatal Boletín Oficial del Estado",
        "source_attribution_url": "https://www.boe.es",
        "publication_dates_requested": [d.isoformat() for d in days],
        "editions_parsed": editions,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "network_used": True,
        "case_text_transmitted": False,
        "title_text_transmitted_or_stored": False,
        "coverage": {
            "searched_collection": "BOE_DAILY_SUMMARY_TC_SECTIONS_ONLY",
            "requested_daily_editions_all_processed": True,
            "dates_processed": len(days),
            "coverage_exhaustive": False,
            "hj_general_search_automated": False,
            "decision_dates_not_searched": True,
            "boe_publication_date_is_not_tc_decision_date": True,
            "publication_dates_outside_window": "NOT_SEARCHED",
            "ordinary_courts": "NOT_SEARCHED_CENDOJ_DISABLED",
            "not_found_is_not_no_authority": True,
            "note": "Daily BOE edition index ≠ full TC corpus or substantive jurisprudence search.",
        },
        "legal_accuracy_measured": False,
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "rights_cleared": False,
    }


def handoff(report: dict, *, boe_id: str, ecli: str, hj_id: int,
            section: str, topic: str) -> dict:
    """Offline human-selected publication -> M6-C1 plan, without claiming ID mapping."""
    if not isinstance(report, dict) or report.get("contract") != CONTRACT or report.get("mode") != "BOE_TC_PUBLICATION_INDEX_DISCOVERY_METADATA_ONLY":
        raise TCBOEIndexError("M6-C2 index report contract invalid")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 3 * MAX_RECORDS:
        raise TCBOEIndexError("M6-C2 index candidate list malformed")
    matches = [c for c in candidates if isinstance(c, dict) and c.get("identifier") == boe_id]
    if len(matches) != 1 or not isinstance(boe_id, str) or not BOE_ID.fullmatch(boe_id):
        raise TCBOEIndexError("explicit BOE publication ID not uniquely found in report")
    selected = matches[0]
    if selected.get("kind") != "SENTENCIA" or not isinstance(selected.get("resolution_label"), str):
        raise TCBOEIndexError("only titled TC Sentencia candidates can be handed to M6-C1")
    label = DECISION.fullmatch(selected["resolution_label"])
    ecli_match = ECLI.fullmatch(ecli) if isinstance(ecli, str) else None
    if not label or not ecli_match or (int(label.group(2)), int(label.group(3))) != (int(ecli_match.group(2)), int(ecli_match.group(1))):
        raise TCBOEIndexError("BOE title label and user-supplied ECLI mismatch")
    from .m6_tc_linkage import plan as tc_plan
    manual = tc_plan(ecli=ecli, hj_id=hj_id, section=section, topic=topic)
    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_BOE_TO_HJ_MANUAL_SELECTION_UNVERIFIED",
        "boe_identifier": boe_id,
        "boe_publication_date": selected["publication_date"],
        "ecli": ecli,
        "hj_document_id": hj_id,
        "m6c1_plan": manual,
        "boe_to_hj_pair_verified": False,
        "requires_next": "M6-C1 resolve verifies ECLI/HJ only; the BOE publication-to-HJ mapping still needs independent checking",
        "network_used": False,
        "legal_applicability": "NOT_ASSESSED",
        "coverage_exhaustive": False,
    }


def _check_output_path(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise TCBOEIndexError("output must be a new absolute file in existing directory")
    cwd = Path.cwd().resolve()
    code_root = Path(__file__).resolve().parents[2]
    roots = set()
    for origin in (cwd, code_root):
        root = next((p for p in (origin, *origin.parents) if (p / ".git").exists()), origin)
        roots.add(root)
    target = path.resolve(strict=False)
    if any(target == root or root in target.parents for root in roots):
        raise TCBOEIndexError("M6-C2 report output must remain outside repository")


def _write_outside_repo(path: Path, value: dict) -> None:
    _check_output_path(path)
    raw = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_report(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
        raise TCBOEIndexError("report must be a regular bounded JSON file")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (UnicodeError, ValueError) as exc:
        raise TCBOEIndexError("report JSON invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M6-C2 bounded official BOE TC publication discovery, not HJ general search")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "search"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--from-date", required=True)
        cmd.add_argument("--to-date", required=True)
        if name == "search":
            cmd.add_argument("--allow-official-network", action="store_true")
            cmd.add_argument("--output", type=Path)
    transfer = commands.add_parser("handoff")
    transfer.add_argument("--report", type=Path, required=True)
    transfer.add_argument("--boe-id", required=True)
    transfer.add_argument("--ecli", required=True)
    transfer.add_argument("--hj-id", type=int, required=True)
    transfer.add_argument("--section", required=True)
    transfer.add_argument("--topic", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(start=args.from_date, end=args.to_date)
        elif args.command == "search":
            if not args.allow_official_network:
                raise TCBOEIndexError("official BOE daily summary search requires --allow-official-network")
            if args.output is not None:
                _check_output_path(args.output)
            result = search(start=args.from_date, end=args.to_date)
            if args.output is not None:
                _write_outside_repo(args.output, result)
        else:
            result = handoff(_read_report(args.report), boe_id=args.boe_id, ecli=args.ecli,
                             hj_id=args.hj_id, section=args.section, topic=args.topic)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (TCBOEIndexError, SourceUnavailable, OSError, TypeError, ValueError) as exc:
        print(f"M6-C2 BOE TC discovery error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
