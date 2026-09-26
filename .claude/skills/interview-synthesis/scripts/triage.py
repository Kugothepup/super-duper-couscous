#!/usr/bin/env python3
"""Choose which posts/comments to code when there are too many to read one by one.

Selection, in order, within a --budget (default 200):
  1. every submission (the original posts)
  2. top-scored comments (about 20% of budget)
  3. comments with signal flags: constraint, request, workaround, switching,
     high engagement (about 40%)
  4. the rest spread across topic clusters, nearest-to-centre first, so quieter
     topics still get read
No author gets more than --per-author comments (except their own posts), so one
prolific poster can't dominate.

Separately, it draws a simple RANDOM sample (--sentiment-sample, default 150) for
measuring sentiment. The triage selection over-represents complaints on purpose (it
chases flags), so it must not be used to estimate how negative people are; the random
sample can. Read it with: view_transcript.py --sentiment-batch N Short "same here" replies aren't coded; they are
counted as echoes by signals.py instead. If candidates fit in the budget, all are kept.

Usage:
  python triage.py --work WORKDIR [--budget 200] [--per-author 5] [--min-words 8]
Writes WORKDIR/triage.json. Read with: view_transcript.py --triage --batch N
"""
import argparse
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_manifest, load_signals, load_turns, save_json  # noqa: E402
from signals import ECHO_AGREE, ECHO_DISAGREE  # noqa: E402
from themes import cluster_terms, embed, pick_k  # noqa: E402

SIGNAL_FLAGS = {"constraint_language", "implicit_request", "workaround_language",
                "switching_language", "high_engagement", "hesitation_cluster"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--budget", type=int, default=200)
    ap.add_argument("--per-author", type=int, default=5)
    ap.add_argument("--min-words", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--sentiment-sample", type=int, default=150,
                    help="size of the random sample for sentiment measurement (0 to skip)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    work = Path(args.work)

    cands, n_echo, n_promo = [], 0, 0
    for m in load_manifest(work):
        tid = m["transcript_id"]
        sig = load_signals(work, tid)
        flags = {t["turn_id"]: set(t.get("flags", [])) for t in sig["turns"]} if sig else {}
        for t in load_turns(work, tid)["turns"]:
            if t["role"] != "participant":
                continue
            words = len(t["text"].split())
            if t.get("promotional"):
                n_promo += 1
                continue
            if t.get("kind") != "post" and words <= 15 and (ECHO_AGREE.search(t["text"]) or
                                                            ECHO_DISAGREE.search(t["text"])):
                n_echo += 1
                continue
            if t.get("kind") != "post" and words < args.min_words:
                continue
            cands.append({"ref": f"{tid}#{t['turn_id']}", "tid": tid, "turn_id": t["turn_id"],
                          "author": t.get("author_id") or t["speaker"], "kind": t.get("kind", "turn"),
                          "score": t.get("score", 0) or 0, "text": t["text"],
                          "flags": flags.get(t["turn_id"], set()) & SIGNAL_FLAGS})
    if not cands:
        raise SystemExit("No candidate turns found. Run parse + signals first.")

    reasons = defaultdict(list)
    per_author = Counter()
    budget = args.budget

    def take(c, why):
        if c["ref"] in reasons:
            reasons[c["ref"]].append(why)
            return False
        if c["kind"] != "post" and per_author[c["author"]] >= args.per_author:
            return False
        reasons[c["ref"]].append(why)
        per_author[c["author"]] += 1
        return True

    clusters_out = []
    if len(cands) <= budget:
        for c in cands:
            reasons[c["ref"]].append("all")
    else:
        for c in cands:
            if c["kind"] == "post":
                take(c, "post")
        quota = int(budget * 0.2)
        for c in sorted(cands, key=lambda c: -c["score"]):
            if quota <= 0 or len(reasons) >= budget:
                break
            quota -= take(c, "top_score")
        quota = int(budget * 0.4)
        for c in sorted([c for c in cands if c["flags"]], key=lambda c: (-len(c["flags"]), -c["score"])):
            if quota <= 0 or len(reasons) >= budget:
                break
            quota -= take(c, "flag:" + ",".join(sorted(c["flags"])))
        texts = [c["text"] for c in cands]
        X, method = embed(texts, use_st=False)
        _, k, km = pick_k(X, None)
        terms = cluster_terms(texts, km.labels_, k)
        members = defaultdict(list)
        for i, lab in enumerate(km.labels_):
            members[lab].append(i)
        remaining = budget - len(reasons)
        for lab in sorted(members, key=lambda l: -len(members[l])):
            idx = sorted(members[lab], key=lambda i: -float(np.dot(X[i], km.cluster_centers_[lab])))
            share = max(1, round(remaining * len(idx) / len(cands)))
            got = 0
            for i in idx:
                if got >= share or len(reasons) >= budget:
                    break
                got += take(cands[i], f"cluster:C{lab + 1:02d}")
            sel = sum(1 for i in idx if cands[i]["ref"] in reasons)
            clusters_out.append({"cluster_id": f"C{lab + 1:02d}", "size": len(idx), "selected": sel,
                                 "top_terms": terms[lab][:6]})

    by_thread = defaultdict(list)
    for c in cands:
        if c["ref"] in reasons:
            by_thread[c["tid"]].append(c["turn_id"])
    order = [(tid, t) for tid in sorted(by_thread) for t in sorted(by_thread[tid])]
    batches = [order[i:i + args.batch_size] for i in range(0, len(order), args.batch_size)]
    samp = []
    if args.sentiment_sample:
        pool = list(cands)  # opening posts carry opinions too
        samp = random.Random(args.seed).sample(pool, min(args.sentiment_sample, len(pool)))
        samp = sorted(samp, key=lambda c: (c["tid"], c["turn_id"]))
    s_refs = [c["ref"] for c in samp]
    s_batches = [s_refs[i:i + args.batch_size] for i in range(0, len(s_refs), args.batch_size)]
    save_json({"budget": budget, "sentiment_sample": s_refs, "sentiment_batches": s_batches,
               "sentiment_population": len(cands), "n_candidates": len(cands), "n_selected": len(order),
               "n_echo_replies": n_echo, "per_author_cap": args.per_author,
               "by_thread": {k: sorted(v) for k, v in by_thread.items()},
               "batches": [[f"{tid}#{t}" for tid, t in b] for b in batches],
               "reasons": dict(reasons), "clusters": clusters_out}, work / "triage.json")

    if n_promo:
        print(f"{n_promo} promotional post(s) excluded from coding and sentiment")
    print(f"{len(cands)} candidates ({n_echo} short echo replies set aside) -> {len(order)} selected "
          f"in {len(batches)} batch(es) of up to {args.batch_size}")
    why = Counter(r.split(":")[0] for rs in reasons.values() for r in rs[:1])
    print("First reason for selection: " + ", ".join(f"{k}={v}" for k, v in why.most_common()))
    if clusters_out:
        print("Topic clusters (size -> selected):")
        for c in sorted(clusters_out, key=lambda c: -c["size"]):
            print(f"  {c['cluster_id']} {c['size']:>4} -> {c['selected']:<3} {', '.join(c['top_terms'][:5])}")
    if samp:
        moe = 98 / (len(samp) ** 0.5)
        print(f"Random sentiment sample: {len(samp)} comments in {len(s_batches)} batch(es) "
              f"(roughly +/-{moe:.0f} points margin on a percentage)")
    capped = [a for a, n in per_author.items() if n >= args.per_author]
    if capped:
        print(f"{len(capped)} author(s) hit the per-author cap of {args.per_author}.")


if __name__ == "__main__":
    main()
