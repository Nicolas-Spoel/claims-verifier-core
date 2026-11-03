"""Command-line interface: ``claims-verifier verify --corpus DIR --answer FILE``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .claims import AnswerError
from .corpus import CorpusError, load_corpus
from .engine import ClaimsVerifier, VerifierConfig
from .evaluation import CasesError, evaluate, load_cases
from .inventory import InventoryError, load_expected
from .models import Verdict, VerificationReport
from .report import to_json, to_markdown

EXIT_OK = 0
EXIT_FAIL_ON = 1
EXIT_INPUT_ERROR = 2
MAX_INPUT_BYTES = 2_000_000
MAX_TOP_K = 100


class InputError(ValueError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claims-verifier", description="Verify AI claims against documentary evidence.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="verify an answer or a list of claims against a corpus")
    verify.add_argument("--corpus", required=True, help="directory (or file) with .md/.txt/.json/.jsonl documents")
    source = verify.add_mutually_exclusive_group(required=True)
    source.add_argument("--answer", help="AI answer to verify (plain text or Markdown); '-' reads stdin")
    source.add_argument("--claims", help="pre-extracted claims: JSON array of strings or one claim per line")
    verify.add_argument("--format", choices=("markdown", "json"), default="markdown")
    verify.add_argument("--out", help="write the report to this file instead of stdout")
    verify.add_argument(
        "--fail-on",
        default="",
        help="comma-separated verdicts that make the command exit with 1 (e.g. CONTRADICTED,CONFLICTING,UNCHECKED; "
        "UNCHECKED = skipped segments that carry factual content)",
    )
    verify.add_argument(
        "--expected", help="JSON inventory of expected documents ([paths] or {documents: [{path, sha256}]})"
    )
    verify.add_argument("--strict", action="store_true", help="fail on any unusable file instead of excluding it")
    verify.add_argument("--top-k", type=int, default=VerifierConfig.top_k, help="passages retrieved per claim")
    verify.add_argument("--synonyms", help="JSON file with extra synonym groups: [[\"word\", \"synonym\", ...], ...]")
    evaluate_cmd = sub.add_parser("evaluate", help="measure accuracy against labelled claims")
    evaluate_cmd.add_argument("--corpus", required=True, help="directory (or file) with evidence documents")
    evaluate_cmd.add_argument("--cases", required=True, help='JSON array of {"claim": str, "expected": VERDICT}')
    evaluate_cmd.add_argument(
        "--min-accuracy", type=float, default=0.0, help="exit with 1 if accuracy is below this value (0-1)"
    )
    return parser


def _read_input(location: str, stdin: TextIO) -> str:
    if location == "-":
        data = stdin.read(MAX_INPUT_BYTES + 1)
        if len(data.encode("utf-8")) > MAX_INPUT_BYTES:
            raise InputError(f"stdin exceeds {MAX_INPUT_BYTES} bytes")
        return data
    path = Path(location)
    if not path.is_file():
        raise InputError(f"file not found: {location}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise InputError(f"{location} exceeds {MAX_INPUT_BYTES} bytes")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"{location}: not valid UTF-8") from exc


def _parse_claims(raw: str) -> list[str]:
    """A JSON array of strings, or else one claim per line (a line may start with "[1]")."""
    stripped = raw.strip()
    if stripped.startswith("["):
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, list):
            if not all(isinstance(item, str) for item in loaded):
                raise InputError("claims JSON must be an array of strings")
            return loaded
    return [line for line in raw.splitlines() if line.strip()]


def _parse_synonyms(location: str | None, stdin: TextIO) -> tuple[tuple[str, ...], ...]:
    if not location:
        return ()
    try:
        groups = json.loads(_read_input(location, stdin))
    except json.JSONDecodeError as exc:
        raise InputError(f"synonyms JSON is invalid: {exc.msg}") from exc
    valid = isinstance(groups, list) and all(
        isinstance(g, list) and len(g) >= 2 and all(isinstance(w, str) for w in g) for g in groups
    )
    if not valid:
        raise InputError("synonyms must be a JSON array of arrays with at least two strings each")
    return tuple(tuple(g) for g in groups)


UNCHECKED = "UNCHECKED"


def _parse_fail_on(raw: str) -> frozenset[str]:
    names = frozenset(n.strip().upper() for n in raw.split(",") if n.strip())
    allowed = {v.value for v in Verdict} | {UNCHECKED}
    if names - allowed:
        raise InputError(f"unknown verdict in --fail-on (allowed: {', '.join(sorted(allowed))})")
    return names


def _run_verify(args: argparse.Namespace, stdin: TextIO) -> VerificationReport:
    if not 1 <= args.top_k <= MAX_TOP_K:
        raise InputError(f"--top-k must be between 1 and {MAX_TOP_K}")
    config = VerifierConfig(top_k=args.top_k, synonym_groups=_parse_synonyms(args.synonyms, stdin))
    expected = load_expected(args.expected) if args.expected else None
    verifier = ClaimsVerifier(load_corpus(args.corpus, strict=args.strict), config, expected=expected)
    if args.answer:
        return verifier.verify_answer(_read_input(args.answer, stdin))
    return verifier.verify_claims(_parse_claims(_read_input(args.claims, stdin)))


def _run_evaluate(args: argparse.Namespace, stdout: TextIO) -> int:
    result = evaluate(ClaimsVerifier(load_corpus(args.corpus)), load_cases(args.cases))
    stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return EXIT_OK if result.accuracy >= args.min_accuracy else EXIT_FAIL_ON


def _emit(report: VerificationReport, args: argparse.Namespace, stdout: TextIO) -> None:
    rendered = to_json(report) if args.format == "json" else to_markdown(report)
    if not args.out:
        stdout.write(rendered)
        return
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")


def _verify_command(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    fail_on = _parse_fail_on(args.fail_on)
    report = _run_verify(args, stdin)
    _emit(report, args, stdout)
    flagged = [r.claim.claim_id for r in report.results if r.verdict.value in fail_on]
    if UNCHECKED in fail_on:
        flagged += [f"UNCHECKED@{s.char_start}" for s in report.skipped if s.factual]
    if flagged:
        stderr.write(f"claims-verifier: {len(flagged)} claim(s) matched --fail-on: {', '.join(flagged)}\n")
        return EXIT_FAIL_ON
    return EXIT_OK


def _printable(text: str) -> str:
    """Neutralise terminal control sequences coming from file names or input."""
    return "".join(ch if ch.isprintable() else f"\\x{ord(ch):02x}" for ch in text)


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "evaluate":
            return _run_evaluate(args, stdout)
        return _verify_command(args, stdin, stdout, stderr)
    except (InputError, CorpusError, AnswerError, CasesError, InventoryError, OSError, RecursionError, UnicodeError) as exc:
        stderr.write(f"claims-verifier: error: {_printable(str(exc))}\n")
        return EXIT_INPUT_ERROR
