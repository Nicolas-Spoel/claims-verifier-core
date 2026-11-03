"""Retrieve one explicitly identified TC resolution section from the official HJ JSON export.

The public HJ page links directly to /HJ/Resolucion/Api/json/{id}. That
structured export numbers FJ sections explicitly; it avoids guessing boundaries
from HTML layout. No generic case-law search, CENDOJ or inferred HJ ID.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re

from ..citations import ReferenceKind, parse_identifier
from ..evidence import LegalEvidence, Origin, SourceKind
from .transport import FetchError, SecureHTTP


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """Refuse ambiguous source metadata instead of last-key-wins parsing."""
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def _text_for_section(payload: dict, section: str) -> str:
    if section == "FALLO":
        rows = payload.get("RESOLUCIONES_DICTAMEN")
        field = "TITULO"
        wanted = "FALLO"
    else:
        rows = payload.get("RESOLUCIONES_FUNDAMENTOS")
        field = "NUMERO"
        wanted = int(section[2:])
    if not isinstance(rows, list) or len(rows) > 200:
        raise FetchError("TC section collection absent or invalid")
    matched = [row for row in rows if isinstance(row, dict)
               and (row.get(field) == wanted if field == "NUMERO"
                    else isinstance(row.get(field), str) and row[field].strip().upper() == wanted)]
    if len(matched) != 1:
        raise FetchError(f"TC section {section} not uniquely located in official JSON")
    raw = matched[0].get("TEXTO")
    if not isinstance(raw, str):
        raise FetchError("TC section text is missing")
    selected = raw.strip()
    if len(selected) < 45:
        raise FetchError("TC section missing or suspiciously short")
    return selected


@dataclass(frozen=True)
class TCResult:
    evidence: LegalEvidence
    hj_document_id: int
    api_url: str
    raw_sha256: str
    limitations: tuple[str, ...] = (
        "Only the explicitly supplied HJ resolution ID was retrieved; the whole TC corpus was not searched.",
        "JSON ID, sentence number and year independently checked against supplied HJ ID / ECLI.",
        "Document identity and literal text are checked; doctrine, context and applicability NOT assessed.",
    )


class TCClient:
    def __init__(self, transport: SecureHTTP | None = None):
        self.transport = transport or SecureHTTP()

    def get_section(self, ecli: str, hj_document_id: int, section_id: str) -> TCResult:
        kind, identifier = parse_identifier(ecli)
        if kind is not ReferenceKind.ECLI or not identifier.startswith("ECLI:ES:TC:"):
            raise ValueError("TC ECLI required")
        # In this M2 slice, certify only numbered SENTENCIA references, not
        # AUTO/DECLARACION or optional ECLI variant suffixes that need other checks.
        match = re.fullmatch(r"ECLI:ES:TC:(\d{4}):([1-9]\d*)", identifier)
        if not match:
            raise ValueError("M2 supports numeric SENTENCIA ECLI only")
        if type(hj_document_id) is not int or not 1 <= hj_document_id <= 999_999_999:
            raise ValueError("explicit positive HJ document ID required")
        if not isinstance(section_id, str):
            raise ValueError("section must be FJ1..FJ99 or FALLO")
        section = section_id.upper()
        if not (re.fullmatch(r"FJ[1-9]\d?", section) or section == "FALLO"):
            raise ValueError("section must be FJ1..FJ99 or FALLO")
        url = f"https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/{hj_document_id}"
        response = self.transport.get(url, accept="application/json")
        try:
            payload = json.loads(response.body.decode("utf-8-sig"), object_pairs_hook=_no_duplicate_keys)
        except (UnicodeDecodeError, ValueError) as exc:
            raise FetchError("TC JSON response invalid or ambiguous") from exc
        if not isinstance(payload, dict):
            raise FetchError("TC JSON response is not an object")
        # HJ structured export does not expose an explicit ECLI field. Confirm
        # its identity from independent structured metadata and restrict type.
        if (type(payload.get("ID")) is not int or payload["ID"] != hj_document_id
                or payload.get("TIPO_RESOLUCION") != "SENTENCIA"
                or type(payload.get("ANNO_RESOLUCION")) is not int
                or type(payload.get("NUMERO_RESOLUCION")) is not int
                or payload["ANNO_RESOLUCION"] != int(match.group(1))
                or payload["NUMERO_RESOLUCION"] != int(match.group(2))):
            raise FetchError("TC official JSON identity does not match supplied ECLI/HJ ID")
        record_date = payload.get("FECHA_REGISTRO")
        if not isinstance(record_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*", record_date):
            raise FetchError("TC decision date missing or invalid")
        try:
            decided = datetime.fromisoformat(record_date).date()
        except ValueError as exc:
            raise FetchError("TC decision date missing or invalid") from exc
        if decided.year != int(match.group(1)):
            raise FetchError("TC decision year does not match ECLI")
        section_text = _text_for_section(payload, section)
        # Public page is a human-readable locator; raw_sha256 refers to the
        # exact JSON response, replayable via TCResult.api_url / source_attempt.
        human_url = f"https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/{hj_document_id}"
        evidence = LegalEvidence(
            source=SourceKind.TC, identifier=identifier, section_id=section,
            text=section_text, official_url=human_url,
            title=f"SENTENCIA {int(match.group(2))}/{int(match.group(1))}", origin=Origin.OFFICIAL_FETCH,
            decision_date=decided.isoformat(), retrieved_at=response.retrieved_at,
        )
        return TCResult(evidence, hj_document_id, url, response.sha256)
