"""Immutable domain models shared across the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    CONFLICTING = "CONFLICTING"
    INCONCLUSIVE = "INCONCLUSIVE"
    """Related evidence exists but cannot safely decide the claim (abstention)."""
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"


class Stance(str, Enum):
    SUPPORTS = "supports"
    PARTIAL = "partial"
    CONTRADICTS = "contradicts"
    AMBIGUOUS = "ambiguous"
    """Related to the claim, but a safety guard prevents deciding from it."""
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    text: str
    source_path: str
    sha256: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    @property
    def date(self) -> str | None:
        return self.metadata.get("date")


@dataclass(frozen=True)
class Passage:
    """A sentence-level evidence unit with exact provenance in its source document."""

    passage_id: str
    doc_id: str
    text: str
    char_start: int
    char_end: int
    line: int
    heading: str
    previous_text: str


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    char_start: int | None
    char_end: int | None
    """Span in the verified answer; ``None`` for claims supplied pre-extracted."""


@dataclass(frozen=True)
class SkippedSegment:
    text: str
    char_start: int
    char_end: int
    reason: str
    factual: bool = False
    """True when the segment carries factual content that was NOT verified (reported as UNCHECKED)."""


@dataclass(frozen=True)
class Signal:
    """A machine-readable reason (``code``) with a human-readable ``detail``."""

    code: str
    detail: str


@dataclass(frozen=True)
class PassageAssessment:
    passage: Passage
    stance: Stance
    relevance: float
    retrieval_score: float
    signals: tuple[Signal, ...]
    matched_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]


@dataclass(frozen=True)
class ClaimResult:
    claim: Claim
    verdict: Verdict
    score: float | None
    """Heuristic strength of the deciding evidence in [0, 1]. NOT a calibrated probability;
    ``None`` when the verdict is an abstention (conflict, no evidence, inconclusive)."""
    rationale: str
    evidence: tuple[PassageAssessment, ...]
    uncertainty: tuple[Signal, ...]
    terms_absent_from_corpus: tuple[str, ...]
    examined: tuple[str, ...] = ()
    """Passage ids retrieved and judged for this claim (the search actually performed)."""
    examined_documents: tuple[str, ...] = ()
    """Document ids of the examined passages."""


@dataclass(frozen=True)
class VerificationReport:
    results: tuple[ClaimResult, ...]
    skipped: tuple[SkippedSegment, ...]
    documents: tuple[Document, ...]
    corpus_fingerprint: str
    passage_count: int
    limitations: tuple[str, ...]
    engine: Mapping[str, str]
    sources: tuple[Any, ...] = ()
    """``inventory.SourceRecord`` per received file (empty for in-memory corpora)."""
    accounting: Any = None
    """``inventory.Accounting`` against an expected inventory, or ``None``."""
    search: Mapping[str, Any] = field(default_factory=dict)
