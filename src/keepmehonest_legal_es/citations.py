"""Conservative recognition of explicit identifiers in Spanish legal citations.

This module does not resolve abbreviations such as 'art. 24 CE', validate the
existence of a cited authority, or judge its applicability.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


class ReferenceKind(str, Enum):
    BOE = "BOE"
    ECLI = "ECLI"
    ROJ = "ROJ"


@dataclass(frozen=True)
class Reference:
    kind: ReferenceKind
    value: str
    start: int
    end: int


_BOE = re.compile(r"(?<![\w-])BOE-A-\d{4}-\d{1,8}(?![\w-])", re.I)
# ECLI year and court ID are intentionally syntactic, not proof of existence.
_ECLI = re.compile(r"(?<![\w:])ECLI:ES:[A-Z0-9]{2,12}:\d{4}:[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?(?![\w:-])", re.I)
_ROJ = re.compile(r"(?<!\w)ROJ\s*:\s*([A-Z]{2,8})\s+(\d{1,8})\s*/\s*(\d{4})(?![\w/])", re.I)


def find_references(text: str) -> tuple[Reference, ...]:
    """Return explicit BOE IDs, ECLIs and 'Roj: STS 1234/2024' with offsets."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    matches: list[Reference] = []
    for m in _BOE.finditer(text):
        matches.append(Reference(ReferenceKind.BOE, m.group(0).upper(), m.start(), m.end()))
    for m in _ECLI.finditer(text):
        matches.append(Reference(ReferenceKind.ECLI, m.group(0).upper(), m.start(), m.end()))
    for m in _ROJ.finditer(text):
        matches.append(Reference(ReferenceKind.ROJ, f"ROJ: {m.group(1).upper()} {m.group(2)}/{m.group(3)}", m.start(), m.end()))
    return tuple(sorted(matches, key=lambda r: (r.start, r.end)))


def parse_identifier(value: str) -> tuple[ReferenceKind, str]:
    """Parse exactly one full legal identifier, rejecting suffixes and ambiguity."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("identifier is required")
    value = value.strip()
    refs = find_references(value)
    if len(refs) != 1 or refs[0].start != 0 or refs[0].end != len(value):
        raise ValueError("expected one exact BOE-A, ECLI:ES or Roj identifier")
    return refs[0].kind, refs[0].value
