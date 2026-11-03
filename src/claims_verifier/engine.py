"""Public entry point: ``ClaimsVerifier`` orchestrates retrieval, judgement and aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from . import __version__
from .aggregate import aggregate
from .claims import Extraction, claims_from_texts, extract_claims
from .corpus import Corpus, build_corpus, load_corpus
from .inventory import ExpectedSource, account
from .judge import Judge, JudgeConfig, LexicalJudge
from .models import Claim, ClaimResult, Document, VerificationReport
from .retrieval import Bm25Index, Retriever
from .text import content_stems, synonym_map

LIMITATIONS: tuple[str, ...] = (
    "Lexical verification with safety guards: it compares terms, figures, dates, negation, direction, "
    "modality, stage (request vs outcome), entity roles and population scope using lexicons and surface "
    "rules; it does not understand meaning. When it sees risk signals it abstains (INCONCLUSIVE, "
    "PARTIALLY_SUPPORTED) instead of deciding.",
    "Only the documents received are considered, and the search examines the most relevant passages for "
    "each claim: 'not enough evidence' does not mean that the claim is false. Corpus completeness can "
    "only be verified against an expected inventory.",
    "The score is heuristic and uncalibrated: it is not the probability that the claim is true.",
    "Evidence is assessed sentence by sentence (with the title, heading and previous sentence as "
    "context); facts spread over several sentences or expressed through deep paraphrase are usually "
    "left undecided.",
    "The lexicons (synonyms, stages, modality, populations) cover administrative and business English "
    "and Spanish; outside that register, abstention increases.",
)


@dataclass(frozen=True)
class VerifierConfig:
    top_k: int = 8
    max_evidence: int = 4
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    synonym_groups: tuple[tuple[str, ...], ...] = ()


class ClaimsVerifier:
    """Verify AI-generated claims against a fixed corpus of evidence documents.

    >>> verifier = ClaimsVerifier.from_path("examples/demo/corpus")  # doctest: +SKIP
    >>> report = verifier.verify_answer("Revenue was ...")  # doctest: +SKIP
    """

    def __init__(
        self,
        corpus: Corpus,
        config: VerifierConfig = VerifierConfig(),
        judge: Judge | None = None,
        retriever: Retriever | None = None,
        expected: Sequence[ExpectedSource] | None = None,
    ) -> None:
        """``expected``: the inventory the corpus should match; enables a verifiable completeness check."""
        self._corpus = corpus
        self._expected = tuple(expected) if expected is not None else None
        self._config = config
        self._synonyms = synonym_map(config.synonym_groups)
        self._retriever = retriever or Bm25Index(corpus.passages, self._synonyms)
        self._judge = judge or LexicalJudge(corpus, self._retriever.idf, self._synonyms, config.judge)
        self._dates = {doc.doc_id: doc.date for doc in corpus.documents}
        self._title_vocabulary = frozenset(
            stem for doc in corpus.documents for stem in content_stems(doc.title, self._synonyms)
        )

    @classmethod
    def from_path(cls, path: str | Path, config: VerifierConfig = VerifierConfig()) -> "ClaimsVerifier":
        return cls(load_corpus(path), config)

    @classmethod
    def from_documents(cls, documents: Iterable[Document], config: VerifierConfig = VerifierConfig()) -> "ClaimsVerifier":
        return cls(build_corpus(documents), config)

    @property
    def corpus(self) -> Corpus:
        return self._corpus

    def verify_answer(self, answer: str) -> VerificationReport:
        """Extract claims from free text (plain or Markdown) and verify each one."""
        return self._report(extract_claims(answer))

    def verify_claims(self, claims: Iterable[str]) -> VerificationReport:
        """Verify already-atomic claim strings."""
        return self._report(claims_from_texts(claims))

    def verify_claim(self, claim: Claim) -> ClaimResult:
        stems = content_stems(claim.text, self._synonyms)
        hits = self._retriever.search(stems, self._config.top_k) if stems else ()
        assessments = [self._judge.assess(claim, passage, score) for passage, score in hits]
        absent = tuple(
            s for s in stems if self._retriever.document_frequency(s) == 0 and s not in self._title_vocabulary
        )
        claim_hedged = self._claim_hedged(claim)
        return aggregate(
            claim,
            assessments,
            self._dates,
            absent_terms=absent,
            claim_hedged=claim_hedged,
            support_min=self._config.judge.support_min,
            topic_min=self._config.judge.topic_min,
            max_evidence=self._config.max_evidence,
        )

    def _claim_hedged(self, claim: Claim) -> bool:
        signals = getattr(self._judge, "signals", None)
        return bool(signals and signals(claim.text).hedged)

    def _report(self, extraction: Extraction) -> VerificationReport:
        results = tuple(self.verify_claim(claim) for claim in extraction.claims)
        return VerificationReport(
            results=results,
            skipped=extraction.skipped,
            documents=self._corpus.documents,
            corpus_fingerprint=self._corpus.fingerprint,
            passage_count=len(self._corpus.passages),
            limitations=LIMITATIONS,
            engine={
                "name": "claims-verifier",
                "version": __version__,
                "judge": getattr(self._judge, "name", type(self._judge).__name__),
                "retriever": type(self._retriever).__name__,
            },
            sources=self._corpus.sources,
            accounting=account(self._corpus.sources, self._expected) if self._expected is not None else None,
            search={"method": type(self._retriever).__name__, "top_k": self._config.top_k},
        )
