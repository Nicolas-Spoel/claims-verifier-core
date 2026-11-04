"""M5-B: bounded, opt-in public-source capture and offline raw-response replay.

Captures are PRIVATE research inputs, never labels, permission clearance or proof
of legal applicability. M5-A's candidate catalogue and human review gate stay
unchanged. No CENDOJ, LLM, arbitrary URLs or client records.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

from .m5_queue import _read_json, validate_candidates
from .sources.boe import BOEClient
from .sources.tc import TCClient
from .sources.transport import Retrieved, SecureHTTP

CONTRACT = "keepmehonest-legal-es/m5-source-capture/v1"
MAX_TASKS = 3  # Explicitly selected; no unrestricted scraping of 36 candidate cases.
MAX_TOTAL_BYTES = 24_000_000
MAX_SINGLE_BYTES = 4_000_000
_RELATIVE = re.compile(r"(?:raw|sections)/[a-z0-9_-]{1,72}\.(?:xml|json|txt)\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class CaptureError(ValueError):
    """Invalid capture, unsafe storage, integrity failure or unsupported source."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _task_key(case: dict) -> tuple[str, str, str, str | None]:
    s = case["source"]
    # Hypothetical case event dates are only candidate retrieval dates, not
    # determinations of applicable law; TC resolutions are retrieved as one text.
    return (s["kind"], s["identifier"], s["section_id"],
            case["event_date"] if s["kind"] == "BOE" else None)


def capture_plan(corpus: dict) -> dict:
    """Offline inventory; no network and no rights assertion."""
    base = validate_candidates(corpus)
    keys = {_task_key(c) for c in corpus["cases"]}
    boe_dates = {k for k in keys if k[0] == "BOE"}
    return {
        "contract": CONTRACT, "mode": "OFFLINE_PLAN", "candidate_cases": base["total_candidates"],
        "unique_source_section_clusters": base["unique_source_section_clusters"],
        "distinct_capture_tasks": len(keys), "boe_date_scoped_tasks": len(boe_dates),
        "tc_section_tasks": len(keys) - len(boe_dates),
        "max_tasks_per_run": MAX_TASKS,
        "note": "A section cluster can have multiple event-date retrievals; no legal temporal applicability inferred.",
        "expert_gold_cases": 0, "rights_cleared": 0, "legal_accuracy_measured": False,
    }


def _selected_tasks(corpus: dict, ids: list[str]) -> list[tuple[tuple, list[dict]]]:
    validate_candidates(corpus)
    if not ids or len(ids) > MAX_TASKS or len(ids) != len(set(ids)):
        raise CaptureError(f"select 1–{MAX_TASKS} distinct case IDs per capture")
    index = {c["case_id"]: c for c in corpus["cases"]}
    if any(cid not in index for cid in ids):
        raise CaptureError("unknown case ID")
    groups = defaultdict(list)
    for cid in ids:
        c = index[cid]
        if c["source"]["kind"] == "BOE" and c["event_date"] is None:
            raise CaptureError("BOE capture requires explicit candidate as-of date")
        groups[_task_key(c)].append(c)
    return sorted(((key, sorted(group, key=lambda x: x["case_id"]))
                   for key, group in groups.items()), key=lambda item: item[0])


def _task_id(key: tuple) -> str:
    return "t" + sha256(_canonical(key)).hexdigest()[:24]


class _RecordingTransport:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[Retrieved] = []

    def get(self, url: str, *, accept: str) -> Retrieved:
        SecureHTTP.check_url(url)
        item = self.inner.get(url, accept=accept)
        if not isinstance(item, Retrieved) or item.url != url:
            raise CaptureError("transport returned mismatched URL/record")
        if sha256(item.body).hexdigest() != item.sha256 or not item.body:
            raise CaptureError("transport response hash mismatch")
        if len(item.body) > MAX_SINGLE_BYTES or sum(len(x.body) for x in self.calls) + len(item.body) > MAX_TOTAL_BYTES:
            raise CaptureError("capture response size limit exceeded")
        if (accept == "application/xml" and item.content_type not in ("application/xml", "text/xml")
                or accept == "application/json" and item.content_type != "application/json"):
            raise CaptureError("capture MIME mismatch")
        self.calls.append(item)
        return item


def _fetch_one(key: tuple, transport) -> tuple[Any, list[Retrieved]]:
    kind, identifier, section, as_of = key
    record = _RecordingTransport(transport)
    if kind == "BOE":
        if not re.fullmatch(r"a([1-9]\d{0,3})", section):
            raise CaptureError("unsupported BOE article ID")
        value = BOEClient(record).get_article(identifier, int(section[1:]), as_of)
        if len(record.calls) != 2 or value.block_id != section:
            raise CaptureError("BOE response not uniquely matched to requested article")
    else:
        raise CaptureError("unsupported source")
    return value, record.calls


def _retrieve(key: tuple, case: dict, transport) -> tuple[Any, list[Retrieved]]:
    kind, identifier, section, as_of = key
    if kind == "BOE":
        return _fetch_one(key, transport)
    if kind == "TC":
        record = _RecordingTransport(transport)
        value = TCClient(record).get_section(identifier, case["source"]["hj_document_id"], section)
        if len(record.calls) != 1 or value.evidence.section_id != section:
            raise CaptureError("TC resolution or section mismatch")
        return value, record.calls
    raise CaptureError("unsupported source")


def _write_exclusive(root: Path, relative: str, content: bytes) -> None:
    if not _RELATIVE.fullmatch(relative) or len(content) > MAX_SINGLE_BYTES:
        raise CaptureError("unsafe capture filename/size")
    target = root / relative
    target.parent.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def _private_parent(dest: Path) -> None:
    if not dest.is_absolute() or dest.name in ("", ".", ".."):
        raise CaptureError("absolute output directory required")
    if dest.exists() or dest.is_symlink():
        raise CaptureError("output must not already exist")
    parent = dest.parent
    if not parent.is_dir() or parent.is_symlink():
        raise CaptureError("existing non-symlink parent directory required")
    if not (parent.stat().st_mode & stat.S_IWUSR):
        raise CaptureError("parent not owner-writable")


def capture_cases(corpus: dict, case_ids: list[str], dest: Path, *, transport=None) -> dict:
    """Fetch a maximum of 3 explicit public candidates and store raw + parsed snapshots.

    A returned archive is *unreviewed* until an authorized human inspects source
    boundaries, original publication, reuse terms and permits its actual use.
    """
    selections = _selected_tasks(corpus, case_ids)
    _private_parent(dest)
    transport = transport if transport is not None else SecureHTTP()
    records: list[dict] = []
    raw_files: list[tuple[str, bytes]] = []
    sec_files: list[tuple[str, bytes]] = []
    total = 0
    for key, cases in selections:
        task_id = _task_id(key)
        result, calls = _retrieve(key, cases[0], transport)
        e = result.evidence
        if (e.identifier, e.section_id) != (key[1], key[2]):
            raise CaptureError("parsed section identity mismatch")
        section_bytes = e.text.encode("utf-8")
        if "\x00" in e.text or e.text.startswith("\ufeff"):
            raise CaptureError("selected section contains disallowed characters")
        if not 64 <= len(section_bytes) <= MAX_SINGLE_BYTES:
            raise CaptureError("section text empty, too short or unbounded")
        sec_path = f"sections/{task_id}.txt"
        sec_files.append((sec_path, section_bytes))
        docs = []
        for i, item in enumerate(calls, 1):
            extension = "json" if item.content_type == "application/json" else "xml"
            filename = f"raw/{task_id}_{i}.{extension}"
            raw_files.append((filename, item.body))
            docs.append({"path": filename, "url": item.url,
                         "content_type": item.content_type, "retrieved_at": item.retrieved_at,
                         "size_bytes": len(item.body), "sha256": item.sha256})
            total += len(item.body)
        total += len(section_bytes)
        record = {
            "task_id": task_id, "case_ids": [c["case_id"] for c in cases],
            "kind": key[0], "identifier": key[1], "section_id": key[2],
            "official_url": cases[0]["source"]["official_url"],
            "hj_document_id": cases[0]["source"]["hj_document_id"],
            "requested_as_of": key[3],
            "retrieval_status": "FETCHED_RAW_UNREVIEWED",
            "section_path": sec_path, "section_sha256": sha256(section_bytes).hexdigest(),
            "section_size_bytes": len(section_bytes), "raw": docs,
            "metadata": ({"effective_from": result.effective_from,
                          "publication_date": result.publication_date,
                          "modifying_norm": result.modifying_norm,
                          "temporal_status": "CHECK_REQUIRED",
                          "consolidated_informational": True}
                         if key[0] == "BOE" else
                         {"decision_date": e.decision_date,
                          "procedural_and_doctrinal_context": "NOT_ASSESSED"}),
            "official_publication_checked": False,
            "rights_reviewed": False,
            "expert_reviewed": False,
        }
        records.append(record)
    if total > MAX_TOTAL_BYTES:
        raise CaptureError("batch exceeds size limit")
    manifest = {
        "contract": CONTRACT, "status": "CAPTURED_UNVERIFIED_NO_RIGHTS_CLEARANCE",
        "corpus_sha256": validate_candidates(corpus)["corpus_sha256"],
        "tasks": records, "source_snapshots_included": len(records),
        "rights_cleared": 0, "expert_gold_cases": 0, "legal_accuracy_measured": False,
        "note": "RAW TRANSPORT HASHES AND PARSED SECTIONS. Not independently authenticated; BOE consolidations informational. No redistribution authorization.",
    }
    stage = Path(tempfile.mkdtemp(prefix=f".{dest.name}.tmp-", dir=dest.parent))
    try:
        stage.chmod(0o700)
        for relative, body in raw_files + sec_files:
            _write_exclusive(stage, relative, body)
        manifest_file = stage / "manifest.json"
        fd = os.open(manifest_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
            f.flush()
            os.fsync(f.fileno())
        verify_capture(corpus, stage)
        _private_parent(dest)
        os.rename(stage, dest)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"capture_dir": str(dest), "task_count": len(records),
            "raw_responses": len(raw_files), "sha256_manifest": sha256((dest / "manifest.json").read_bytes()).hexdigest(),
            "status": manifest["status"], "rights_cleared": 0, "expert_gold_cases": 0}


def _read_frozen(root: Path, filename: str, claimed_hash: str, claimed_size: int) -> bytes:
    if not isinstance(filename, str) or not _RELATIVE.fullmatch(filename):
        raise CaptureError("unsafe manifest-relative path")
    if not isinstance(claimed_hash, str) or not _DIGEST.fullmatch(claimed_hash):
        raise CaptureError("invalid expected SHA-256")
    if type(claimed_size) is not int or not 0 < claimed_size <= MAX_SINGLE_BYTES:
        raise CaptureError("invalid expected file size")
    file = root / filename
    if file.is_symlink() or file.parent.is_symlink() or not file.is_file() or not stat.S_ISREG(file.lstat().st_mode):
        raise CaptureError("capture missing or symlink/non-regular file")
    if file.resolve().parent != file.parent.resolve():
        raise CaptureError("unsafe capture parent")
    if file.stat().st_size != claimed_size:
        raise CaptureError("snapshot size mismatch")
    body = file.read_bytes()
    if sha256(body).hexdigest() != claimed_hash:
        raise CaptureError("snapshot SHA-256 mismatch")
    return body


class _ReplayTransport:
    """No network; only URLs and responses pinned in a previously sealed batch."""
    def __init__(self, docs: list[dict], contents: list[bytes]):
        self.data = {}
        self.called = set()
        for record, body in zip(docs, contents):
            SecureHTTP.check_url(record["url"])
            if record["url"] in self.data:
                raise CaptureError("duplicate replay URL")
            self.data[record["url"]] = (record, body)

    def get(self, url, *, accept):
        SecureHTTP.check_url(url)
        if url not in self.data or url in self.called:
            raise CaptureError("unexpected replay URL or duplicate read")
        record, body = self.data[url]
        if not (accept == "application/xml" and record["content_type"] in ("text/xml", "application/xml")
                or accept == "application/json" and record["content_type"] == "application/json"):
            raise CaptureError("replay MIME mismatch")
        self.called.add(url)
        return Retrieved(url, body, record["content_type"], record["sha256"], record["retrieved_at"])


def verify_capture(corpus: dict, root: Path) -> dict:
    """Reparse the *frozen raw bytes* with the existing M2 BOE/TC parsers."""
    validate_candidates(corpus)
    if root.is_symlink() or not root.is_dir():
        raise CaptureError("invalid capture root")
    mf = root / "manifest.json"
    if mf.is_symlink() or not mf.is_file() or mf.stat().st_size > 250_000:
        raise CaptureError("manifest absent, symlinked or oversized")
    manifest = _read_json(mf, 250_000)
    if (not isinstance(manifest, dict) or set(manifest) != {
        "contract", "status", "corpus_sha256", "tasks", "source_snapshots_included",
        "rights_cleared", "expert_gold_cases", "legal_accuracy_measured", "note"}
            or manifest["contract"] != CONTRACT
            or manifest["status"] != "CAPTURED_UNVERIFIED_NO_RIGHTS_CLEARANCE"
            or manifest["corpus_sha256"] != validate_candidates(corpus)["corpus_sha256"]
            or manifest["rights_cleared"] != 0 or manifest["expert_gold_cases"] != 0
            or manifest["legal_accuracy_measured"] is not False):
        raise CaptureError("capture manifest does not match M5 pilot or safety contract")
    tasks = manifest["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS or manifest["source_snapshots_included"] != len(tasks):
        raise CaptureError("invalid capture task inventory")
    all_ids: list[str] = []
    seen_tasks = set()
    for record in tasks:
        if not isinstance(record, dict) or set(record) != {
            "task_id", "case_ids", "kind", "identifier", "section_id", "official_url",
            "hj_document_id", "requested_as_of", "retrieval_status", "section_path",
            "section_sha256", "section_size_bytes", "raw", "metadata",
            "official_publication_checked", "rights_reviewed", "expert_reviewed"}:
            raise CaptureError("invalid record schema")
        if (record["retrieval_status"] != "FETCHED_RAW_UNREVIEWED" or
                record["official_publication_checked"] is not False or
                record["rights_reviewed"] is not False or record["expert_reviewed"] is not False):
            raise CaptureError("record promotes unreviewed material")
        all_ids.extend(record["case_ids"])
    if len(all_ids) != len(set(all_ids)):
        raise CaptureError("duplicate case in capture batch")
    expected = {_task_id(k): (k, cs) for k, cs in _selected_tasks(corpus, all_ids)}
    if set(expected) != {t["task_id"] for t in tasks}:
        raise CaptureError("task identities do not match selected candidates")
    expected_paths = {"manifest.json"}
    for task in tasks:
        expected_paths.add(task["section_path"])
        for raw_doc in task["raw"]:
            if not isinstance(raw_doc, dict):
                raise CaptureError("invalid raw document entry")
            expected_paths.add(raw_doc["path"])
    for child_dir in (root / "raw", root / "sections"):
        if child_dir.is_symlink() or not child_dir.is_dir():
            raise CaptureError("snapshot subdirectory missing or symlinked")
    actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*")
                    if p.is_file() or p.is_symlink()}
    if actual_paths != expected_paths:
        raise CaptureError("snapshot inventory differs from manifest")
    for record in tasks:
        ident = record["task_id"]
        if ident in seen_tasks:
            raise CaptureError("duplicate task")
        seen_tasks.add(ident)
        key, cases = expected[ident]
        if (record["case_ids"] != [c["case_id"] for c in cases] or
                (record["kind"], record["identifier"], record["section_id"], record["requested_as_of"]) != key or
                record["official_url"] != cases[0]["source"]["official_url"] or
                record["hj_document_id"] != cases[0]["source"]["hj_document_id"]):
            raise CaptureError("source/task locator changed since inventory")
        docs = record["raw"]
        if not isinstance(docs, list) or len(docs) != (2 if key[0] == "BOE" else 1):
            raise CaptureError("wrong raw response count")
        bodies = []
        if len({doc.get("path") for doc in docs if isinstance(doc, dict)}) != len(docs):
            raise CaptureError("duplicate raw snapshot path")
        for doc in docs:
            if not isinstance(doc, dict) or set(doc) != {"path", "url", "content_type", "retrieved_at", "size_bytes", "sha256"}:
                raise CaptureError("invalid frozen raw entry")
            if not re.fullmatch(r"raw/" + re.escape(ident) + r"_[12]\.(?:xml|json)", doc["path"]):
                raise CaptureError("unexpected raw artifact filename")
            try:
                stamp = datetime.fromisoformat(doc["retrieved_at"])
                if stamp.tzinfo is None:
                    raise ValueError("missing timezone")
            except (TypeError, ValueError) as e:
                raise CaptureError("invalid retrieval timestamp") from e
            bodies.append(_read_frozen(root, doc["path"], doc["sha256"], doc["size_bytes"]))
        replay = _ReplayTransport(docs, bodies)
        result, _ = _retrieve(key, cases[0], replay)
        if len(replay.called) != len(docs):
            raise CaptureError("unused/unexpected replay document")
        section_bytes = _read_frozen(root, record["section_path"], record["section_sha256"], record["section_size_bytes"])
        if record["section_path"] != f"sections/{ident}.txt" or section_bytes != result.evidence.text.encode("utf-8"):
            raise CaptureError("extracted section mismatches frozen source responses")
        metadata = ({"effective_from": result.effective_from, "publication_date": result.publication_date,
                     "modifying_norm": result.modifying_norm, "temporal_status": "CHECK_REQUIRED",
                     "consolidated_informational": True}
                    if key[0] == "BOE" else
                    {"decision_date": result.evidence.decision_date,
                     "procedural_and_doctrinal_context": "NOT_ASSESSED"})
        if record["metadata"] != metadata:
            raise CaptureError("recorded historical/provenance metadata does not replay")
    return {"contract": CONTRACT, "mode": "OFFLINE_VERIFIED_REPLAY",
            "tasks_verified": len(tasks), "raw_responses_verified": sum(len(t["raw"]) for t in tasks),
            "sections_verified": len(tasks), "sha256_manifest": sha256(mf.read_bytes()).hexdigest(),
            "rights_cleared": 0, "expert_gold_cases": 0, "legal_accuracy_measured": False,
            "note": "SHA-256 and deterministic parsing verified against frozen raw. Neither provenance authenticity nor legal applicability nor reuse cleared."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M5-B public-only, bounded source snapshots and offline replay")
    parser.add_argument("--candidates", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--capture", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--allow-official-network", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--capture-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        corpus = _read_json(args.candidates)
        if args.capture:
            if not args.allow_official_network or args.output_dir is None or args.capture_dir is not None:
                raise CaptureError("capture requires explicit network opt-in and new --output-dir")
            report = capture_cases(corpus, args.case_id, args.output_dir)
        elif args.verify:
            if args.allow_official_network or args.case_id or args.output_dir or args.capture_dir is None:
                raise CaptureError("offline verify requires only --capture-dir")
            report = verify_capture(corpus, args.capture_dir)
        else:
            if args.allow_official_network or args.case_id or args.output_dir or args.capture_dir:
                raise CaptureError("plan is offline; use --capture or --verify for requested action")
            report = capture_plan(corpus)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RuntimeError) as exc:
        print(f"M5-B capture error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
