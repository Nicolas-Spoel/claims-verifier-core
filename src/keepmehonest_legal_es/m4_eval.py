"""M4 offline synthetic regression CLI; separate from public-source retrieval CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from .evaluation import EvaluationError, read_corpus, run_corpus, corpus_fingerprint


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M4 deterministic offline regression, not legal accuracy")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", type=Path, help="Write JSON evaluation locally")
    args = parser.parse_args(argv)
    try:
        payload = read_corpus(args.corpus)
        if args.validate_only:
            result = {"valid": True, "cases": len(payload["cases"]),
                      "corpus_sha256": corpus_fingerprint(payload), "expert_gold_cases": 0}
        else:
            result = run_corpus(payload)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if args.validate_only or result["cases_failed"] == 0 else 1
    except (OSError, ValueError, TypeError, KeyError, EvaluationError) as exc:
        print(f"M4 evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
