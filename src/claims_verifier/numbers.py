"""Locale-tolerant numeric mention extraction and comparison (es/en)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .lexicon import APPROX_MARKERS, ATTRIBUTIVE_YEAR_NOUNS, MAX_MARKERS, MIN_MARKERS, MONTHS, STOPWORDS
from .text import fold

YEAR_MIN, YEAR_MAX = 1900, 2100
APPROX_TOLERANCE = 0.05
EXACT_RELATIVE_TOLERANCE = 0.001
QUALIFIER_LOOKBEHIND_CHARS = 24
YEAR_CONTEXT_CHARS = 40

# Spelled-out multipliers also tell the locale: English ones use "," for thousands
# ("1,950 million"), Spanish ones use "." for thousands ("1.950 millones").
_ENGLISH_MULTIPLIERS: dict[str, float] = {
    "billion": 1e9, "billions": 1e9, "million": 1e6, "millions": 1e6, "thousand": 1e3,
}
_SPANISH_MULTIPLIERS: dict[str, float] = {"mil millones": 1e9, "billones": 1e12, "millones": 1e6, "millon": 1e6, "mil": 1e3}
# Abbreviations only count when attached to the digits ("5M", "2.5k"); "10 m" is metres.
_ATTACHED_MULTIPLIERS: dict[str, float] = {"mm": 1e6, "m": 1e6, "k": 1e3}
_MULTIPLIERS = {**_ENGLISH_MULTIPLIERS, **_SPANISH_MULTIPLIERS, **_ATTACHED_MULTIPLIERS}
_WORD_MULT_ALTERNATION = "|".join(
    re.escape(k) for k in sorted({**_ENGLISH_MULTIPLIERS, **_SPANISH_MULTIPLIERS}, key=len, reverse=True)
)
_NUMBER_RE = re.compile(
    r"(?:(?P<currency>s/\.?|us\$|usd|pen|eur|\$|€)\s*+)?"
    r"(?:(?<![\w.,])(?P<sign>[-−–+]))?"
    r"(?P<num>(?<![\w.,])\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|(?<![\w.,])\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<mult>{_WORD_MULT_ALTERNATION})\b|(?P<short>mm|m|k)\b)?"
    r"(?:\s*(?P<pct>%|por ciento|percent|pct)(?!\w))?"
)
_DATE_RE = re.compile(r"(?<![\w/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?![\w/])")
_PREVIOUS_WORD_RE = re.compile(r"([^\W\d_]+|\d+)\W*$")
_NEXT_WORD_RE = re.compile(r"^\W*([^\W\d_]+|\d+)")
# Words that, right before a 4-digit number, mark it as a year ("en 2023", "since 2019").
_YEAR_MARKERS = frozenset(
    """
    en de del desde hasta a al entre y ano anual ejercicio periodo fiscal cierre durante hacia antes despues
    trimestre semestre gestion memoria informe reporte
    in of since until by to from and during between before after year annual fiscal fy report
    q1 q2 q3 q4 t1 t2 t3 t4 h1 h2
    """.split()
) | frozenset(MONTHS)
# English determiners that put a year in attributive position before a period noun ("the 2024 collection").
_ATTRIBUTIVE_YEAR_DETERMINERS = frozenset("the its their this that our".split())


class NumberKind(str, Enum):
    PERCENT = "percent"
    YEAR = "year"
    DATE = "date"
    QUANTITY = "quantity"


class Qualifier(str, Enum):
    EXACT = "exact"
    APPROX = "approx"
    AT_LEAST = "at_least"
    AT_MOST = "at_most"


@dataclass(frozen=True)
class NumberMention:
    """A number found in text, normalized to a float with its precision."""

    raw: str
    value: float
    kind: NumberKind
    unit_precision: float
    qualifier: Qualifier
    start: int
    end: int


def _parse_numeral(raw: str, multiplier: str | None) -> tuple[float, int]:
    """Return (value, decimal_places) for a numeral using es/en separator heuristics."""
    if "." in raw and "," in raw:
        decimal_sep = "." if raw.rfind(".") > raw.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        integer, _, fraction = raw.replace(thousands_sep, "").partition(decimal_sep)
        return float(f"{integer}.{fraction}"), len(fraction)
    sep = "." if "." in raw else ("," if "," in raw else "")
    if not sep:
        return float(raw), 0
    parts = raw.split(sep)
    looks_grouped = all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3
    if multiplier in _ENGLISH_MULTIPLIERS:
        looks_grouped = looks_grouped and sep == ","
    elif multiplier in _SPANISH_MULTIPLIERS:
        looks_grouped = looks_grouped and sep == "."
    elif multiplier:
        looks_grouped = False
    if len(parts) > 2 or looks_grouped:
        return float("".join(parts)), 0
    return float(f"{parts[0]}.{parts[1]}"), len(parts[1])


def _qualifier_before(folded_text: str, start: int) -> Qualifier:
    window = folded_text[max(0, start - QUALIFIER_LOOKBEHIND_CHARS):start]
    for markers, qualifier in (
        (MIN_MARKERS, Qualifier.AT_LEAST),
        (MAX_MARKERS, Qualifier.AT_MOST),
        (APPROX_MARKERS, Qualifier.APPROX),
    ):
        pattern = r"\W*(?:de\s+|del\s+|un\s+|una\s+|el\s+|la\s+|los\s+|las\s+|the\s+)?$"
        if any(re.search(rf"(?<!\w){re.escape(m)}{pattern}", window) for m in markers):
            return qualifier
    return Qualifier.EXACT


def _looks_like_year(folded: str, start: int, end: int) -> bool:
    """A bare 4-digit number is a year after a temporal marker ("in 2023"), between an English
    determiner and a period noun ("the 2024 collection"), or when no noun follows it ("2023
    was..."); "2000 workers" and "the 2000-seat stadium" are quantities."""
    previous = _PREVIOUS_WORD_RE.search(folded[max(0, start - YEAR_CONTEXT_CHARS):start])
    if previous and previous.group(1) in _YEAR_MARKERS:
        return True
    following = _NEXT_WORD_RE.match(folded[end:end + YEAR_CONTEXT_CHARS])
    if (previous and previous.group(1) in _ATTRIBUTIVE_YEAR_DETERMINERS and following is not None
            and following.group(1) in ATTRIBUTIVE_YEAR_NOUNS and folded[end:end + 1] != "-"):
        return True
    return following is None or following.group(1) in STOPWORDS or following.group(1).isdigit()


def _dates(text: str) -> list[NumberMention]:
    """Numeric dates (day-first: dd/mm/yyyy), encoded as yyyymmdd so they compare as one value."""
    mentions = []
    for match in _DATE_RE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        mentions.append(
            NumberMention(match.group(0), year * 10_000 + month * 100 + day, NumberKind.DATE, 1.0,
                          Qualifier.EXACT, match.start(), match.end())
        )
    return mentions


def _mention(text: str, folded: str, match: re.Match[str]) -> NumberMention:
    raw_number = match.group("num")
    mult_key = match.group("mult") or match.group("short")
    value, decimals = _parse_numeral(raw_number, mult_key)
    multiplier = _MULTIPLIERS.get(mult_key or "", 1.0)
    sign = -1.0 if match.group("sign") in {"-", "−", "–"} else 1.0
    if match.group("pct") is not None:
        kind = NumberKind.PERCENT
    elif (
        raw_number.isdigit() and YEAR_MIN <= value <= YEAR_MAX and sign > 0
        and not mult_key and not match.group("currency")
        and _looks_like_year(folded, match.start("num"), match.end())
    ):
        kind = NumberKind.YEAR
    else:
        kind = NumberKind.QUANTITY
    return NumberMention(
        raw=text[match.start():match.end()].strip(),
        value=sign * value * multiplier,
        kind=kind,
        unit_precision=(10 ** -decimals) * multiplier,
        qualifier=_qualifier_before(folded, match.start()),
        start=match.start("sign") if match.group("sign") else match.start("num"),
        end=match.end(),
    )


def extract_numbers(text: str) -> tuple[NumberMention, ...]:
    """Find numeric mentions; offsets refer to ``text`` (``fold`` preserves length)."""
    folded = fold(text)
    dates = _dates(folded)
    masked = list(folded)
    for date in dates:
        masked[date.start:date.end] = " " * (date.end - date.start)
    numbers = [_mention(text, folded, m) for m in _NUMBER_RE.finditer("".join(masked))]
    dated = [NumberMention(text[d.start:d.end], d.value, d.kind, d.unit_precision, d.qualifier, d.start, d.end)
             for d in dates]
    return tuple(sorted(numbers + dated, key=lambda n: n.start))


def values_agree(claim: NumberMention, evidence: NumberMention) -> bool:
    """True when the evidence value is consistent with the claim value.

    Rounding in the claim is tolerated up to half its last significant unit
    (claim "49 million" agrees with evidence "48.6 million"). Approximate
    markers on either side widen tolerance; "more than"/"less than" become bounds.
    Values of opposite sign never agree.
    """
    if (claim.value < 0) != (evidence.value < 0) and claim.value and evidence.value:
        return False
    if claim.qualifier is Qualifier.AT_LEAST:
        return evidence.value > claim.value or _close(claim, evidence)
    if claim.qualifier is Qualifier.AT_MOST:
        return evidence.value < claim.value or _close(claim, evidence)
    return _close(claim, evidence)


def _close(claim: NumberMention, evidence: NumberMention) -> bool:
    if NumberKind.DATE in (claim.kind, evidence.kind):
        return claim.value == evidence.value
    tolerance = max(claim.unit_precision / 2, abs(claim.value) * EXACT_RELATIVE_TOLERANCE)
    if Qualifier.APPROX in (claim.qualifier, evidence.qualifier):
        tolerance = max(tolerance, abs(claim.value) * APPROX_TOLERANCE)
    return abs(claim.value - evidence.value) <= tolerance + 1e-9
