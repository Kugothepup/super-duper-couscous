#!/usr/bin/env python3
"""Print a transcript or Reddit thread compactly, with signal flags inline, for coding.

Usage:
  python view_transcript.py --work WORKDIR --id T01 [--range 1-80]
  python view_transcript.py --work WORKDIR --triage --batch 1      (Reddit: triaged batches)
  python view_transcript.py --work WORKDIR --sentiment-batch 1     (Reddit: random sentiment sample)

Interview lines:  [12] P  03:12  {flags}  text
Reddit lines:     [12] A007 OP ^34 d2 re[9] (+3 agree/-1)  {flags}  text
When a comment's parent isn't shown, a context line gives the start of the parent.
I = interviewer, P = participant. Flags come from signals.py if it has been run.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_json, load_signals, load_turns  # noqa: E402


def fmt_ts(s):
    if s is None:
        return "     "
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def show(work, tid, keep=None, lo=1, hi=10 ** 9):
    doc = load_turns(work, tid)
    sig = load_signals(work, tid)
    sturn = {t["turn_id"]: t for t in sig["turns"]} if sig else {}
    turns = {t["turn_id"]: t for t in doc["turns"]}
    reddit = doc.get("source_type") in ("reddit", "forum")
    if reddit:
        print(f"# {tid}  {doc.get('site') or 'r/' + str(doc.get('subreddit'))}  \"{doc.get('title', '')}\"")
    else:
        print(f"# {tid}  ({doc['source_file']})  speakers: "
              + ", ".join(f"{s}={r}" for s, r in doc["speakers"].items()))
    if sig:
        for w in sig["summary"]["warnings"]:
            print(f"# ! {w}")
    shown, ctx = set(), set()
    for t in doc["turns"]:
        if not lo <= t["turn_id"] <= hi or (keep is not None and t["turn_id"] not in keep):
            continue
        st = sturn.get(t["turn_id"], {})
        f = st.get("flags")
        ftxt = "{" + ",".join(f) + "}  " if f else ""
        if reddit:
            pt = t.get("parent_turn")
            if pt and pt not in shown and pt not in ctx and pt in turns and t.get("kind") != "post":
                ctx.add(pt)
                p = turns[pt]
                print(f"    (replying to [{pt}] {p['speaker']}: \"{p['text'][:110]}"
                      f"{'...' if len(p['text']) > 110 else ''}\")")
            echo = ""
            if st.get("echo_agree") or st.get("echo_disagree"):
                echo = f" (+{st.get('echo_agree', 0)} agree/-{st.get('echo_disagree', 0)})"
            op = " OP" if t.get("is_op") else ""
            kind = " POST" if t.get("kind") == "post" else ""
            par = f" re[{pt}]" if pt else ""
            print(f"[{t['turn_id']}]{kind} {t['speaker']}{op} ^{t.get('score', 0)} d{t.get('depth', 0)}"
                  f"{par}{echo}  {ftxt}{t['text']}")
        else:
            role = {"interviewer": "I", "participant": "P"}.get(t["role"], "?")
            print(f"[{t['turn_id']}] {role}  {fmt_ts(t['start'])}  {ftxt}{t['text']}")
        shown.add(t["turn_id"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--id", help="transcript/thread id")
    ap.add_argument("--range", help="turn range, e.g. 1-80")
    ap.add_argument("--triage", action="store_true", help="only show turns selected by triage.py")
    ap.add_argument("--batch", type=int, help="with --triage: show batch N (1-based)")
    ap.add_argument("--sentiment-batch", type=int, help="show batch N of the random sentiment sample")
    args = ap.parse_args()

    lo, hi = 1, 10 ** 9
    if args.range:
        a, _, b = args.range.partition("-")
        lo, hi = int(a), int(b or a)

    if args.triage or args.sentiment_batch:
        tri = load_json(Path(args.work) / "triage.json")
        if args.sentiment_batch:
            sb = tri.get("sentiment_batches", [])
            if not 1 <= args.sentiment_batch <= len(sb):
                raise SystemExit(f"sentiment batch must be 1..{len(sb)}")
            refs = sb[args.sentiment_batch - 1]
            print(f"## Sentiment sample batch {args.sentiment_batch}/{len(sb)} ({len(refs)} items)")
        elif args.batch:
            if not 1 <= args.batch <= len(tri["batches"]):
                raise SystemExit(f"batch must be 1..{len(tri['batches'])}")
            refs = tri["batches"][args.batch - 1]
            print(f"## Batch {args.batch}/{len(tri['batches'])} ({len(refs)} items)")
        else:
            refs = [f"{tid}#{t}" for tid, ts in tri["by_thread"].items() for t in ts]
        want = {}
        for r in refs:
            tid, t = r.split("#")
            want.setdefault(tid, set()).add(int(t))
        for tid in sorted(want):
            if args.id and tid != args.id:
                continue
            show(args.work, tid, want[tid], lo, hi)
            print()
    else:
        if not args.id:
            raise SystemExit("--id is required unless --triage is used")
        show(args.work, args.id, None, lo, hi)


if __name__ == "__main__":
    main()
