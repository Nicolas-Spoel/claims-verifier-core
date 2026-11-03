"""Independent local CLI. Network disabled unless explicitly opted in."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .evidence import LegalEvidence, Origin, SourceKind
from .independent import verify_argument
from .sources import BOEClient, TCClient, FetchError


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="KeepMeHonest legal-es: conservative independent documentary triage")
    p.add_argument("--text-file", type=Path, required=True, help="Argument text remains local")
    p.add_argument("--evidence-json", type=Path, help="Optional array of user-supplied LegalEvidence dicts")
    p.add_argument("--boe", action="append", default=[], metavar="BOE-ID,ARTICLE,YYYY-MM-DD")
    p.add_argument("--tc", action="append", default=[], metavar="TC-ECLI,HJ-ID,FJ1")
    p.add_argument("--allow-official-network", action="store_true", help="Only sends explicit identifiers to BOE/HJ")
    p.add_argument("--output", type=Path, help="Write JSON report locally")
    args = p.parse_args(argv)
    try:
        if args.text_file.stat().st_size > 800_000:
            raise ValueError("argument file too large")
        text = args.text_file.read_text(encoding="utf-8")
        evidence = []
        attempts = []
        if args.evidence_json:
            if args.evidence_json.stat().st_size > 2_000_000:
                raise ValueError("evidence file too large")
            items = json.loads(args.evidence_json.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                raise ValueError("evidence JSON must be a list")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("each evidence must be an object")
                # Caller cannot assert OFFICIAL_FETCH merely by writing a JSON field.
                data = dict(item)
                data["origin"] = Origin.USER_SUPPLIED
                data["source"] = SourceKind(data["source"])
                evidence.append(LegalEvidence(**data))
        if (args.boe or args.tc) and not args.allow_official_network:
            raise ValueError("explicit --allow-official-network required")
        if len(args.boe) + len(args.tc) > 20:
            raise ValueError("maximum 20 external fetch attempts")
        for item in args.boe:
            fields = item.split(",")
            if len(fields) != 3:
                raise ValueError("--boe syntax BOE-ID,ARTICLE,YYYY-MM-DD")
            identifier, article, as_of = fields
            try:
                fetched = BOEClient().get_article(identifier, int(article), as_of)
                evidence.append(fetched.evidence)
                attempts.append({"source": "BOE", "identifier": identifier, "status": "FETCHED", "raw_sha256": fetched.raw_sha256,
                                 "temporal_status": fetched.temporal_status, "requested_as_of": fetched.requested_as_of})
            except (FetchError, ValueError) as exc:
                attempts.append({"source": "BOE", "identifier": identifier, "status": "UNAVAILABLE", "reason": str(exc)})
        for item in args.tc:
            fields = item.split(",")
            if len(fields) != 3:
                raise ValueError("--tc syntax TC-ECLI,HJ-ID,FJ1")
            identifier, hj_id, section = fields
            try:
                fetched = TCClient().get_section(identifier, int(hj_id), section)
                evidence.append(fetched.evidence)
                attempts.append({"source": "TC", "identifier": identifier, "status": "FETCHED", "raw_sha256": fetched.raw_sha256, "retrieval_url": fetched.api_url})
            except (FetchError, ValueError) as exc:
                attempts.append({"source": "TC", "identifier": identifier, "status": "UNAVAILABLE", "reason": str(exc)})
        report = verify_argument(text, evidence, attempted_sources=attempts)
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"KeepMeHonest input error: {exc}", file=sys.stderr)
        return 2
    # A successful process exit must not hide a failed requested retrieval.
    return 3 if any(a["status"] != "FETCHED" for a in attempts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
