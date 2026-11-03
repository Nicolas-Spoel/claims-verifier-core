"""Evaluate a verifier against labelled claims (accuracy and confusion matrix)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .claims import MAX_CLAIM_CHARS
from .engine import ClaimsVerifier
from .models import Verdict


class CasesError(ValueError):
    """Raised when the labelled cases file is malformed."""


@dataclass(frozen=True)
class LabelledClaim:
    claim: str
    expected: Verdict


@dataclass(frozen=True)
class Miss:
    claim: str
    expected: Verdict
    actual: Verdict


@dataclass(frozen=True)
class EvaluationResult:
    total: int
    correct: int
    confusion: dict[str, dict[str, int]]
    misses: tuple[Miss, ...]

    @property
    def accuracy(self) -> float:
        return round(self.correct / self.total, 4) if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "confusion": self.confusion,
            "misses": [
                {"claim": m.claim, "expected": m.expected.value, "actual": m.actual.value} for m in self.misses
            ],
        }


def load_cases(path: str | Path) -> tuple[LabelledClaim, ...]:
    """Load ``[{"claim": str, "expected": VERDICT}, ...]`` from a JSON file."""
    try:
        records = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CasesError(f"cannot read cases from {path}: {exc}") from exc
    if not isinstance(records, list) or not records:
        raise CasesError("cases must be a non-empty JSON array")
    cases = []
    for index, record in enumerate(records):
        try:
            cases.append(LabelledClaim(str(record["claim"]), Verdict(record["expected"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise CasesError(f"case {index}: needs 'claim' and a valid 'expected' verdict") from exc
    return tuple(cases)


def evaluate(verifier: ClaimsVerifier, cases: Sequence[LabelledClaim]) -> EvaluationResult:
    # verify_claims drops empty and over-long claims, which would pair later results with the wrong case.
    for index, case in enumerate(cases):
        if not case.claim.strip() or len(case.claim.strip()) > MAX_CLAIM_CHARS:
            raise CasesError(f"case {index}: claim is empty or exceeds {MAX_CLAIM_CHARS} characters")
    report = verifier.verify_claims([c.claim for c in cases])
    pairs = [(case.expected, result.verdict) for case, result in zip(cases, report.results)]
    counts = Counter((e.value, a.value) for e, a in pairs)
    confusion = {
        expected.value: {actual.value: counts[(expected.value, actual.value)] for actual in Verdict}
        for expected in Verdict
    }
    misses = tuple(Miss(c.claim, e, a) for c, (e, a) in zip(cases, pairs) if e is not a)
    return EvaluationResult(len(pairs), len(pairs) - len(misses), confusion, misses)
