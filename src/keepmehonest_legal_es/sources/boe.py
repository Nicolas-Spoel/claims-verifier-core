"""AEBOE consolidated-law XML: explicit BOE ID + article + as-of date only.

Legislation consolidation is *informational*, never a declaration of vigencia.
Historical version selection is conservative: missing/ambiguous effective dates
fail closed, rather than silently using the latest text.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import xml.etree.ElementTree as ET

from ..citations import ReferenceKind, parse_identifier
from ..evidence import LegalEvidence, Origin, SourceKind
from .transport import FetchError, SecureHTTP, Retrieved


BASE = "https://www.boe.es/datosabiertos/api/legislacion-consolidada/id"


def _date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("date required")
    if re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    raise ValueError("date format must be YYYY-MM-DD or YYYYMMDD")


def _parse_xml(response: Retrieved) -> ET.Element:
    body = response.body
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise FetchError("DTD/entities forbidden")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise FetchError("BOE XML malformed") from exc
    if root.tag != "response" or root.findtext("status/code") != "200":
        raise FetchError("BOE application status not 200")
    if root.find("data") is None:
        raise FetchError("BOE XML missing data")
    return root


def _paragraphs(version: ET.Element) -> str:
    # <version> contains XHTML paragraphs, tables and separate explanatory
    # blockquotes. Preserve paragraph boundaries and avoid note-as-legislation.
    chunks: list[str] = []
    for child in version:
        if child.tag in ("p", "table", "ul", "ol"):
            s = " ".join("".join(child.itertext()).split())
            if s:
                chunks.append(s)
    return "\n".join(chunks)


@dataclass(frozen=True)
class BOEResult:
    evidence: LegalEvidence
    requested_as_of: str
    effective_from: str
    publication_date: str
    modifying_norm: str
    block_id: str
    api_url: str
    raw_sha256: str
    temporal_status: str = "CHECK_REQUIRED"
    limitations: tuple[str, ...] = (
        "Consolidated text is informational, not the official publication.",
        "Version selected from published effective-date metadata; tacit changes and legal applicability NOT assessed.",
    )


class BOEClient:
    def __init__(self, transport: SecureHTTP | None = None):
        self.transport = transport or SecureHTTP()

    def get_article(self, boe_id: str, article: int, as_of: str) -> BOEResult:
        kind, identifier = parse_identifier(boe_id)
        if kind is not ReferenceKind.BOE:
            raise ValueError("BOE-A identifier required")
        if type(article) is not int or not 1 <= article <= 9999:
            raise ValueError("article must be a positive integer <= 9999")
        requested = _date(as_of)
        index_url = f"{BASE}/{identifier}/texto/indice"
        index = _parse_xml(self.transport.get(index_url, accept="application/xml"))
        candidates = []
        expected_title = re.compile(rf"^art[ií]culo\s+{article}(?:\.\s*.*)?$", re.I)
        for block in index.findall("data/bloque"):
            title = (block.findtext("titulo") or "").strip()
            bid = (block.findtext("id") or "").strip()
            if expected_title.fullmatch(title) and re.fullmatch(r"[A-Za-z0-9_\-]{1,100}", bid):
                candidates.append((bid, title))
        if len(candidates) != 1:
            raise FetchError(f"article block is not uniquely identified ({len(candidates)} candidates)")
        bid, title = candidates[0]
        url = f"{BASE}/{identifier}/texto/bloque/{bid}"
        response = self.transport.get(url, accept="application/xml")
        root = _parse_xml(response)
        blocks = root.findall("data/bloque")
        if len(blocks) != 1:
            raise FetchError("BOE block response must contain one block")
        block = blocks[0]
        if block.get("id") and block.get("id") != bid:
            raise FetchError("BOE block ID mismatch")
        expiry = block.get("fecha_caducidad")
        if expiry and requested >= _date(expiry):
            raise FetchError("article block expired at requested date; applicability unresolved")
        versions: list[tuple[date, date, str, str]] = []
        for version in block.findall("version"):
            published, effective, modifier = version.get("fecha_publicacion"), version.get("fecha_vigencia"), version.get("id_norma")
            # Publication alone is not a trustworthy proxy for entry into force.
            if not (published and effective and modifier):
                raise FetchError("BOE block version missing temporal or provenance attributes")
            pdate, edate = _date(published), _date(effective)
            if pdate > requested or edate > requested:
                continue
            if pdate > edate:
                # Retroactivity is legally possible; do not automatically reject it,
                # but its real applicability needs human review.
                pass
            content = _paragraphs(version)
            if not content:
                raise FetchError("BOE selected/past version without parseable text")
            versions.append((edate, pdate, modifier, content))
        if not versions:
            raise FetchError("no dated BOE block version available as of requested date")
        versions.sort(key=lambda v: (v[0], v[1]))
        if len(versions) > 1 and versions[-1][:2] == versions[-2][:2]:
            raise FetchError("ambiguous same-date BOE versions")
        edate, pdate, modifier, content = versions[-1]
        official_url = f"https://www.boe.es/buscar/act.php?id={identifier}#{bid}"
        evidence = LegalEvidence(
            source=SourceKind.BOE, identifier=identifier, section_id=bid,
            text=content, official_url=official_url, title=f"{title} · {identifier}",
            origin=Origin.OFFICIAL_FETCH, version_date=edate.isoformat(), retrieved_at=response.retrieved_at,
        )
        return BOEResult(evidence, requested.isoformat(), edate.isoformat(), pdate.isoformat(), modifier, bid, url, response.sha256)
