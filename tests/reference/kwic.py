#!/usr/bin/env python3
"""Keyword-in-context: see every place a term appears across transcripts.

Useful for checking how participants actually use a product term ("sync", "export",
"dashboard") and whether their meaning matches the system's.

Usage:
  python kwic.py --work WORKDIR --term "export" [--regex] [--all-speakers] [--width 60]
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_manifest, load_turns  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--term", required=True)
    ap.add_argument("--regex", action="store_true", help="treat --term as a regular expression")
    ap.add_argument("--all-speakers", action="store_true", help="include interviewer turns")
    ap.add_argument("--width", type=int, default=60)
    args = ap.parse_args()

    pat = args.term if args.regex else r"\b" + re.escape(args.term) + r"\w*"
    rx = re.compile(pat, re.I)
    per = Counter()
    for m in load_manifest(args.work):
        tid = m["transcript_id"]
        for t in load_turns(args.work, tid)["turns"]:
            if t["role"] != "participant" and not args.all_speakers:
                continue
            for hit in rx.finditer(t["text"]):
                left = t["text"][max(0, hit.start() - args.width):hit.start()]
                right = t["text"][hit.end():hit.end() + args.width]
                role = "P" if t["role"] == "participant" else "I"
                print(f"{tid}#{t['turn_id']:<4}{role} {left:>{args.width}} [{hit.group(0)}] {right}")
                per[tid] += 1
    total = sum(per.values())
    print(f"\n{total} hit(s) in {len(per)} transcript(s): {dict(per)}")


if __name__ == "__main__":
    main()
