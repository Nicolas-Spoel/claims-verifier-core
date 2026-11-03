"""Legal evidence provenance contract v0.1: a URL or ECLI is not authenticity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
from urllib.parse import urlsplit

from .citations import ReferenceKind, parse_identifier


class SourceKind(str, Enum):
    BOE = "BOE"
    TC = "TC"
    ORDINARY_COURTS = "ORDINARY_COURTS"


class Origin(str, Enum):
    USER_SUPPLIED = "USER_SUPPLIED"
    HISTORICAL_IMPORT = "HISTORICAL_IMPORT"
    TEST_FIXTURE = "TEST_FIXTURE"
    # Reserved until a source connector is independently validated.
    OFFICIAL_FETCH = "OFFICIAL_FETCH"


_ALLOWED_OFFICIAL_HOSTS = {
    SourceKind.BOE: frozenset({"boe.es", "www.boe.es"}),
    SourceKind.TC: frozenset({"hj.tribunalconstitucional.es", "www.tribunalconstitucional.es"}),
    SourceKind.ORDINARY_COURTS: frozenset({"www.poderjudicial.es", "poderjudicial.es"}),
}


def _iso_date(value: str | None, name: str) -> None:
    if value is not None:
        try:
            if len(value) != 10:
                raise ValueError
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be ISO date YYYY-MM-DD") from exc


@dataclass(frozen=True)
class LegalEvidence:
    source: SourceKind
    identifier: str
    section_id: str
    text: str
    official_url: str
    title: str
    origin: Origin = Origin.USER_SUPPLIED
    decision_date: str | None = None
    version_date: str | None = None
    retrieved_at: str | None = None
    # Never inferred from a URL; official-authenticity verification is M2+.

    def __post_init__(self) -> None:
        kind, canonical = parse_identifier(self.identifier)
        if self.source == SourceKind.BOE and kind is not ReferenceKind.BOE:
            raise ValueError("BOE evidence must have an explicit BOE-A identifier")
        if self.source == SourceKind.TC and not (kind is ReferenceKind.ECLI and canonical.startswith("ECLI:ES:TC:")):
            raise ValueError("TC evidence must have a TC ECLI")
        if self.source == SourceKind.ORDINARY_COURTS and kind is ReferenceKind.BOE:
            raise ValueError("ordinary-court evidence cannot use a BOE identifier")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("evidence text is required")
        if not isinstance(self.section_id, str) or not self.section_id.strip():
            raise ValueError("a specific section_id is required (e.g. FJ3, art24)")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("title is required")
        _iso_date(self.decision_date, "decision_date")
        _iso_date(self.version_date, "version_date")
        if self.source == SourceKind.BOE and self.version_date is None:
            raise ValueError("BOE evidence requires version_date; temporal status still unassessed")
        if self.source == SourceKind.TC and self.decision_date is None:
            raise ValueError("TC evidence requires decision_date")
        parsed = urlsplit(self.official_url)
        if (parsed.scheme != "https" or parsed.hostname not in _ALLOWED_OFFICIAL_HOSTS[self.source]
                or parsed.username or parsed.password or parsed.port is not None):
            raise ValueError("official_url must be https on an explicitly allowed official host")
        if self.origin is Origin.OFFICIAL_FETCH and self.source is SourceKind.ORDINARY_COURTS:
            raise ValueError("automatic ordinary-court retrieval not authorized in M1")
        if self.origin is Origin.OFFICIAL_FETCH:
            if self.retrieved_at is None:
                raise ValueError("official fetch requires retrieved_at")
            try:
                value = datetime.fromisoformat(self.retrieved_at)
            except ValueError as exc:
                raise ValueError("retrieved_at must be ISO 8601") from exc
            if value.tzinfo is None:
                raise ValueError("retrieved_at must include timezone")
        object.__setattr__(self, "identifier", canonical)

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def evidence_key(self) -> str:
        # Stable, content-sensitive key; scope independent of claimed authenticity.
        raw = f"{self.source.value}\0{self.identifier}\0{self.section_id}\0{self.sha256}".encode("utf-8")
        return sha256(raw).hexdigest()

    @property
    def date(self) -> str | None:
        return self.version_date or self.decision_date
