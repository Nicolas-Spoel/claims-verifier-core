"""Loading evidence documents and segmenting them into traceable passages."""

from __future__ import annotations

import bisect
import hashlib
import json
import re
import stat
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .inventory import SourceRecord, SourceStatus, walk
from .models import Document, Passage
from .text import split_sentences, strip_markdown

MAX_DOCUMENT_BYTES = 2_000_000
MAX_DOCUMENTS = 5_000
MAX_CORPUS_BYTES = 50_000_000
MAX_PASSAGES = 200_000
MAX_HEADING_CHARS = 500
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
JSON_SUFFIXES = frozenset({".json", ".jsonl"})
_FRONT_MATTER_DELIMITER = "---"
_RULE_RE = re.compile(r"^(?:[-*_]\s*){3,}$")
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s|\|)")
_FIRST_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


class CorpusError(ValueError):
    """Raised when evidence documents are missing, too large or malformed."""


@dataclass(frozen=True)
class Corpus:
    documents: tuple[Document, ...]
    passages: tuple[Passage, ...]
    sources: tuple[SourceRecord, ...] = ()
    """Every received file and whether it was examined or excluded (empty for in-memory corpora)."""

    @property
    def fingerprint(self) -> str:
        """Stable hash over document ids and content hashes, for reproducibility."""
        digest = hashlib.sha256()
        for doc in self.documents:
            identifier = doc.doc_id.encode("utf-8", "surrogatepass")
            digest.update(len(identifier).to_bytes(4, "big") + identifier + bytes.fromhex(doc.sha256))
        return digest.hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_front_matter(raw: str) -> tuple[dict[str, str], int]:
    """Parse a minimal ``key: value`` front-matter block. Returns (metadata, body_offset).

    Anything that is not a well-formed, closed block is treated as ordinary text.
    """
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        return {}, 0
    metadata: dict[str, str] = {}
    offset = len(lines[0])
    for line in lines[1:]:
        offset += len(line)
        if line.strip() == _FRONT_MATTER_DELIMITER:
            return metadata, offset
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or " " in key.strip():
            return {}, 0  # a leading horizontal rule, not front matter: keep the text as body
        metadata[key.strip().lower()] = value.strip().strip("\"'")
    return {}, 0


def make_document(
    doc_id: str,
    text: str,
    source_path: str = "",
    title: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> Document:
    """Build a document from in-memory text (front matter in ``text`` is honoured)."""
    front, _ = parse_front_matter(text)
    merged = {**front, **(metadata or {})}
    heading = _FIRST_HEADING_RE.search(text)
    resolved_title = title or merged.get("title") or (heading.group(1).strip() if heading else doc_id)
    return Document(
        doc_id=merged.get("id", doc_id),
        title=resolved_title,
        text=text,
        source_path=source_path,
        sha256=_sha256(text),
        metadata=merged,
    )


def _read_bytes(path: Path) -> bytes:
    """Read a regular file once (no FIFOs or devices), within the per-document limit."""
    try:
        info = path.stat()
    except OSError as exc:
        raise CorpusError(f"{path.name!r}: cannot be read ({exc.strerror})") from exc
    if not stat.S_ISREG(info.st_mode):
        raise CorpusError(f"{path.name!r}: not a regular file")
    if info.st_size > MAX_DOCUMENT_BYTES:
        raise CorpusError(f"{path.name!r}: {info.st_size} bytes exceeds limit of {MAX_DOCUMENT_BYTES}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CorpusError(f"{path.name!r}: cannot be read ({exc.strerror})") from exc


def _decode(data: bytes, name: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CorpusError(f"{name!r}: not valid UTF-8 ({exc.reason})") from exc


def _read_text(path: Path) -> str:
    return _decode(_read_bytes(path), path.name)


def _documents_from_json(path: Path, relative: str, raw: str | None = None) -> Iterator[Document]:
    raw = _read_text(path) if raw is None else raw
    try:
        if path.suffix == ".jsonl":
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        else:
            loaded = json.loads(raw)
            records = loaded if isinstance(loaded, list) else [loaded]
    except json.JSONDecodeError as exc:
        raise CorpusError(f"{path.name!r}: invalid JSON ({exc.msg} at line {exc.lineno})") from exc
    except RecursionError as exc:
        raise CorpusError(f"{path.name!r}: JSON nested too deeply") from exc
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("text"), str):
            raise CorpusError(f"{path.name!r}: record {index} must be an object with a string 'text'")
        try:
            record["text"].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise CorpusError(f"{path.name!r}: record {index} contains invalid Unicode") from exc
        doc_id = str(record.get("id") or f"{Path(relative).with_suffix('')}#{index}")
        metadata = {k: str(v) for k, v in record.items() if k not in {"text", "id"} and v is not None}
        yield make_document(doc_id, record["text"], f"{relative}#{index}", metadata.get("title"), metadata)


def _load_file(path: Path, relative: str) -> tuple[list[Document], str, int]:
    """Parse a file from a single read; returns (documents, sha256 of the parsed bytes, size)."""
    data = _read_bytes(path)
    text = _decode(data, path.name)
    if path.suffix.lower() in JSON_SUFFIXES:
        documents = list(_documents_from_json(path, relative, text))
    else:
        documents = [make_document(Path(relative).with_suffix("").as_posix(), text, relative)]
    return documents, hashlib.sha256(data).hexdigest(), len(data)


def _scan(root_path: Path, strict: bool) -> tuple[list[Document], list[SourceRecord]]:
    """Load every supported file; anything unusable is recorded as excluded (or raised if strict)."""
    base = root_path if root_path.is_dir() else root_path.parent
    resolved_root = root_path.resolve() if root_path.is_dir() else base.resolve()
    entries = walk(root_path) if root_path.is_dir() else iter([(root_path, None)])
    documents: list[Document] = []
    records: list[SourceRecord] = []
    total_bytes = 0
    for path, skip_reason in entries:
        relative = path.relative_to(base).as_posix()
        if skip_reason is None and not path.resolve().is_relative_to(resolved_root):
            if strict:
                raise CorpusError(f"{path.name}: resolves outside the corpus directory")
            skip_reason = "outside_corpus"
        if skip_reason is None and path.suffix.lower() not in TEXT_SUFFIXES | JSON_SUFFIXES:
            skip_reason = "unsupported_type"
        if skip_reason:
            records.append(SourceRecord(relative, SourceStatus.EXCLUDED, skip_reason))
            continue
        try:
            loaded, digest, size = _load_file(path, relative)
        except (CorpusError, OSError, UnicodeError, RecursionError, ValueError) as exc:
            if strict:
                raise exc if isinstance(exc, CorpusError) else CorpusError(f"{path.name!r}: {exc}") from exc
            records.append(SourceRecord(relative, SourceStatus.EXCLUDED, _clean_reason(exc)))
            continue
        total_bytes += size
        if total_bytes > MAX_CORPUS_BYTES:
            raise CorpusError(f"corpus exceeds {MAX_CORPUS_BYTES} bytes")
        documents.extend(loaded)
        records.append(SourceRecord(relative, SourceStatus.EXAMINED, None, tuple(d.doc_id for d in loaded), digest, size))
        if len(documents) > MAX_DOCUMENTS:
            raise CorpusError(f"corpus exceeds {MAX_DOCUMENTS} documents")
    return documents, records


def _clean_reason(exc: BaseException) -> str:
    """Exclusion reason safe to print (no control characters from hostile file names)."""
    return "".join(ch if ch.isprintable() else f"\\x{ord(ch):02x}" for ch in str(exc))[:300]


def load_documents(root: str | Path, strict: bool = True) -> tuple[Document, ...]:
    """Load .md/.txt/.json/.jsonl documents from a directory (or a single file)."""
    root_path = Path(root)
    if not root_path.exists():
        raise CorpusError(f"corpus path not found: {root_path}")
    documents, _ = _scan(root_path, strict)
    if not documents:
        raise CorpusError(f"no supported documents (.md, .txt, .json, .jsonl) in {root_path}")
    _ensure_unique_ids(documents)
    return tuple(documents)


def _ensure_unique_ids(documents: Iterable[Document]) -> None:
    seen: set[str] = set()
    for doc in documents:
        if doc.doc_id in seen:
            raise CorpusError(f"duplicate document id: {doc.doc_id}")
        seen.add(doc.doc_id)


def _blocks(text: str, start: int) -> Iterator[tuple[int, int, bool]]:
    """Yield (start, end, is_heading) for paragraphs, list items, table rows and headings."""
    position = start
    paragraph_start: int | None = None
    for line in text[start:].splitlines(keepends=True):
        stripped = "" if _RULE_RE.match(line.strip()) else line.strip()
        line_start, line_end = position, position + len(line.rstrip("\r\n"))
        position += len(line)
        is_heading = stripped.startswith("#")
        is_item = bool(_LIST_ITEM_RE.match(stripped))
        if not stripped or is_heading or is_item:
            if paragraph_start is not None:
                yield paragraph_start, line_start, False
                paragraph_start = None
            if stripped:
                yield line_start, line_end, is_heading
        elif paragraph_start is None:
            paragraph_start = line_start
    if paragraph_start is not None:
        yield paragraph_start, len(text), False


def segment_document(doc: Document) -> tuple[Passage, ...]:
    """Split a document into sentence passages, each carrying offsets, line and heading context."""
    _, body_start = parse_front_matter(doc.text)
    passages: list[Passage] = []
    heading = ""
    newlines = [i for i, ch in enumerate(doc.text) if ch == "\n"]
    for block_start, block_end, is_heading in _blocks(doc.text, body_start):
        block_text = doc.text[block_start:block_end]
        if is_heading:
            heading = strip_markdown(block_text[:MAX_HEADING_CHARS]).strip()
            continue
        previous = ""
        for start, end in split_sentences(block_text, block_start):
            cleaned = " ".join(strip_markdown(line) for line in doc.text[start:end].splitlines()).strip()
            if not cleaned:
                continue
            passages.append(
                Passage(
                    passage_id=f"{doc.doc_id}:p{len(passages) + 1}",
                    doc_id=doc.doc_id,
                    text=cleaned,
                    char_start=start,
                    char_end=end,
                    line=bisect.bisect_left(newlines, start) + 1,
                    heading=heading,
                    previous_text=previous,
                )
            )
            previous = cleaned
    return tuple(passages)


def build_corpus(documents: Iterable[Document]) -> Corpus:
    docs = tuple(documents)
    if not docs:
        raise CorpusError("corpus is empty")
    _ensure_unique_ids(docs)
    passages = tuple(p for doc in docs for p in segment_document(doc))
    if len(passages) > MAX_PASSAGES:
        raise CorpusError(f"corpus exceeds {MAX_PASSAGES} passages")
    return Corpus(documents=docs, passages=passages)


def _unique_ids(documents: list[Document]) -> tuple[list[Document], dict[str, str]]:
    """Never drop a document whose id collides: rename it to ``id@source`` and report it."""
    seen: set[str] = set()
    unique: list[Document] = []
    renamed: dict[str, str] = {}
    for doc in documents:
        if doc.doc_id in seen:
            new_id = f"{doc.doc_id}@{doc.source_path}"
            renamed[doc.source_path] = new_id
            doc = replace(doc, doc_id=new_id)
        seen.add(doc.doc_id)
        unique.append(doc)
    return unique, renamed


def _reconcile(
    records: list[SourceRecord], renamed: dict[str, str], with_text: set[str]
) -> tuple[SourceRecord, ...]:
    """Update file records with renamed ids and mark files whose documents had no text."""
    reconciled = []
    for record in records:
        if record.status is SourceStatus.EXAMINED:
            ids = [renamed.get(f"{record.path}#{i}") or renamed.get(record.path) or d
                   for i, d in enumerate(record.doc_ids)]
            kept_ids = tuple(d for d in ids if d in with_text)
            notes = [f"duplicate id renamed to {renamed[p]}" for p in renamed if p.split("#")[0] == record.path]
            reason = "; ".join(notes) or None
            if kept_ids:
                record = replace(record, doc_ids=kept_ids, reason=reason)
            else:
                record = replace(record, status=SourceStatus.EXCLUDED, reason=reason or "no_text", doc_ids=())
        reconciled.append(record)
    return tuple(reconciled)


def load_corpus(root: str | Path, strict: bool = False) -> Corpus:
    """Load a corpus with a full inventory of received, examined and excluded sources.

    Unusable files are excluded with a reason instead of aborting, unless ``strict``.
    """
    root_path = Path(root)
    if not root_path.exists():
        raise CorpusError(f"corpus path not found: {root_path}")
    documents, records = _scan(root_path, strict)
    if strict:
        _ensure_unique_ids(documents)
    unique, renamed = _unique_ids(documents)
    if not unique:
        raise CorpusError(f"no usable documents (.md, .txt, .json, .jsonl) in {root_path}")
    corpus = build_corpus(unique)
    with_text = {p.doc_id for p in corpus.passages}
    examined_docs = tuple(d for d in corpus.documents if d.doc_id in with_text)
    if not examined_docs:
        raise CorpusError(f"no document in {root_path} contains text")
    return Corpus(
        documents=examined_docs,
        passages=corpus.passages,
        sources=_reconcile(records, renamed, with_text),
    )
