#!/usr/bin/env python3
"""List coded nuggets compactly across all transcripts, for synthesis.

Usage:
  python list_nuggets.py --work WORKDIR [--force push] [--tag export] [--friction] [--min-severity 2]
                                        [--evidence observed,specific_incident] [--quotes]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import all_nuggets  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--force")
    ap.add_argument("--tag")
    ap.add_argument("--evidence", help="comma-separated evidence types")
    ap.add_argument("--friction", action="store_true")
    ap.add_argument("--min-severity", type=int, default=0)
    ap.add_argument("--quotes", action="store_true", help="also print the quote")
    args = ap.parse_args()

    ns = all_nuggets(args.work)
    if args.force:
        ns = [n for n in ns if n.get("jtbd_force") == args.force]
    if args.tag:
        ns = [n for n in ns if args.tag in n.get("tags", [])]
    if args.evidence:
        ok = set(args.evidence.split(","))
        ns = [n for n in ns if n.get("evidence_type") in ok]
    if args.friction or args.min_severity:
        ns = [n for n in ns if n.get("friction") and (n.get("severity") or 0) >= args.min_severity]

    for n in ns:
        sev = f" S{n['severity']}" if n.get("friction") else ""
        print(f"{n['id']:<9} {n['jtbd_force']:<7} {n['evidence_type'][:10]:<10}{sev:<4} "
              f"[{','.join(n.get('tags', []))}] {n['observation']}")
        if args.quotes:
            print(f"          \"{n['quote']}\"")
    tags = Counter(t for n in ns for t in n.get("tags", []))
    print(f"\n{len(ns)} nuggets from {len({n['transcript_id'] for n in ns})} transcripts. "
          f"Top tags: {', '.join(f'{t}({c})' for t, c in tags.most_common(15))}")


if __name__ == "__main__":
    main()
