"""Claims Verifier: check AI-generated claims against documentary evidence."""

__version__ = "0.1.1"

from .corpus import Corpus, CorpusError, build_corpus, load_corpus, make_document  # noqa: E402
from .engine import ClaimsVerifier, VerifierConfig  # noqa: E402
from .judge import JudgeConfig, LexicalJudge  # noqa: E402
from .models import ClaimResult, Stance, Verdict, VerificationReport  # noqa: E402

__all__ = [
    "ClaimResult",
    "ClaimsVerifier",
    "Corpus",
    "CorpusError",
    "JudgeConfig",
    "LexicalJudge",
    "Stance",
    "Verdict",
    "VerificationReport",
    "VerifierConfig",
    "__version__",
    "build_corpus",
    "load_corpus",
    "make_document",
]
