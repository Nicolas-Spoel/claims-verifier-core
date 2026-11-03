"""Corpus provenance: which sources were received, examined or excluded, and against
which expected inventory (if any) completeness can be verified.

Without an expected inventory the verifier only knows what it was given, so the
completeness of the corpus is reported as ``unverifiable`` rather than assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator


class SourceStatus(str, Enum):
    EXAMINED = "examined"
    EXCLUDED = "excluded"


class Completeness(str, Enum):
    COMPLETE = "complete"
    COMPLETE_UNVERSIONED = "complete_unversioned"
    UNEXPECTED_SOURCES = "unexpected_sources"
    """Every expected source is present, but sources outside the inventory were examined too."""
    """Every expected path was received and examined, but some versions (hashes) were not checked."""
    INCOMPLETE = "incomplete"
    UNVERIFIABLE = "unverifiable"


class InventoryError(ValueError):
    """Raised when an expected-inventory file is malformed."""


@dataclass(frozen=True)
class SourceRecord:
    """One received file (or in-memory source) and what happened to it."""

    path: str
    status: SourceStatus
    reason: str | None = None
    doc_ids: tuple[str, ...] = ()
    sha256: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class ExpectedSource:
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class Accounting:
    completeness: Completeness
    expected: int | None
    missing: tuple[str, ...] = ()
    version_mismatch: tuple[str, ...] = ()
    excluded_expected: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    expected_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "completeness": self.completeness.value,
            "expected": self.expected,
            "missing": list(self.missing),
            "version_mismatch": list(self.version_mismatch),
            "excluded_expected": list(self.excluded_expected),
            "unexpected": list(self.unexpected),
        }

    def is_expected(self, source_path: str) -> bool | None:
        """Whether a document's source file is in the expected inventory (None without one)."""
        if self.expected is None:
            return None
        return normalize_path(source_path.split("#")[0]) in self.expected_paths


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk(root: Path) -> Iterator[tuple[Path, str | None]]:
    """Yield (path, exclusion_reason) for every entry under ``root``; hidden entries are
    reported once and not descended into."""
    for directory, subdirs, files in os.walk(root):
        base = Path(directory)
        for name in sorted(subdirs):
            if name.startswith("."):
                yield base / name, "hidden"
            elif (base / name).is_symlink():
                yield base / name, "symlinked_directory"
        subdirs[:] = sorted(d for d in subdirs if not d.startswith(".") and not (base / d).is_symlink())
        for name in sorted(files):
            yield base / name, "hidden" if name.startswith(".") else None


def load_expected(path: str | Path) -> tuple[ExpectedSource, ...]:
    """Read ``{"documents": [{"path": ..., "sha256": ...}]}`` or a plain list of paths."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read expected inventory {path}: {exc}") from exc
    entries = raw.get("documents") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or not entries:
        raise InventoryError("expected inventory must list at least one document")
    expected = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            expected.append(ExpectedSource(entry))
        elif isinstance(entry, dict) and isinstance(entry.get("path"), str):
            expected.append(ExpectedSource(entry["path"], entry.get("sha256")))
        else:
            raise InventoryError(f"expected inventory entry {index} needs a 'path'")
    return tuple(expected)


def normalize_path(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix().removeprefix("./")


def account(records: Iterable[SourceRecord], expected: Iterable[ExpectedSource] | None) -> Accounting:
    """Compare what was received against an expected inventory (the only verifiable denominator)."""
    received = {normalize_path(r.path): r for r in records}
    if expected is None:
        return Accounting(Completeness.UNVERIFIABLE, None)
    wanted = {normalize_path(e.path): e for e in expected}
    missing = tuple(p for p in wanted if p not in received)
    mismatch = tuple(
        p for p, e in wanted.items()
        if p in received and e.sha256 and e.sha256.lower() != (received[p].sha256 or "").lower()
    )
    excluded = tuple(p for p in wanted if p in received and received[p].status is SourceStatus.EXCLUDED)
    unexpected = tuple(p for p, r in received.items() if p not in wanted and r.reason != "hidden")
    unexpected_examined = [p for p in unexpected if received[p].status is SourceStatus.EXAMINED]
    complete = not (missing or mismatch or excluded)
    versioned = all(e.sha256 for e in wanted.values())
    if not complete:
        status = Completeness.INCOMPLETE
    elif unexpected_examined:
        status = Completeness.UNEXPECTED_SOURCES
    else:
        status = Completeness.COMPLETE if versioned else Completeness.COMPLETE_UNVERSIONED
    return Accounting(
        status,
        len(wanted),
        missing,
        mismatch,
        excluded,
        unexpected,
        tuple(wanted),
    )
