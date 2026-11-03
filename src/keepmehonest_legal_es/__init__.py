"""KeepMeHonest — Spanish Legal Edition (experimental, offline M1)."""
from .citations import Reference, ReferenceKind, find_references, parse_identifier
from .evidence import LegalEvidence, Origin, SourceKind
from .verification import CitationCheck, LegalReview, QuoteCheck, review_claim, to_core_document, verify_quote

__all__ = [
    "CitationCheck", "LegalEvidence", "LegalReview", "Origin", "QuoteCheck",
    "Reference", "ReferenceKind", "SourceKind", "find_references",
    "parse_identifier", "review_claim", "to_core_document", "verify_quote",
]

# M2: independent argument input and conservatively scoped official-source clients.
from .independent import verify_argument
from .sources import BOEClient, TCClient, SecureHTTP, FetchError, SourceUnavailable
__all__ += ["verify_argument", "BOEClient", "TCClient", "SecureHTTP", "FetchError", "SourceUnavailable"]
