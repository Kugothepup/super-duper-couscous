#!/usr/bin/env python3
"""Describe the language people use about the subject.

1. Keyness: which words and two-word phrases are distinctively over-used in negative
   versus positive comments (from the random sentiment sample). Uses log-likelihood
   (G2; Dunning 1993, Rayson & Garside 2000) for significance and Log Ratio (Hardie 2014)
   for effect size. A term must be used by at least --min-reach different people, so
   one person's pet phrase can't top the list.
2. Common phrases: two- and three-word phrases ranked by how many different people
   (authors for Reddit, transcripts for interviews) used them.
3. Signal language: % of comments/turns containing constraint, request, workaround
   and switching language (from signals.py).

Usage:
  python language.py --work WORKDIR [--min-reach 2] [--top 15]
Writes WORKDIR/language.json.
"""
import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (load_json, load_manifest, load_signals, load_turns, save_json,  # noqa: E402
                     study_mode, turn_index)

try:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS as SK_STOP
except ImportError:  # pragma: no cover
    SK_STOP = set()
STOP = set(SK_STOP) | {
    "yeah", "okay", "ok", "like", "just", "really", "um", "uh", "gonna", "wanna", "lot", "pretty",
    "actually", "honestly", "thing", "things", "stuff", "don't", "didn't", "doesn't", "i'm", "it's",
    "i've", "that's", "there's", "can't", "won't", "isn't", "wasn't", "i'd", "you're", "they're",
    "we're", "i'll", "let's", "user", "u", "got", "get", "going", "know", "think", "say", "said",
    "want", "way", "use", "used", "using", "make", "does", "did", "doing", "also", "still", "even",
}
TOKEN = re.compile(r"[a-z][a-z'\-]*[a-z]|[a-z]")


def tokens(text):
    text = re.sub(r"u/\[user\]", " ", text.lower().replace("\u2019", "'"))
    return TOKEN.findall(text)


def terms(text):
    toks = tokens(text)
    out = [t for t in toks if t not in STOP and len(t) > 2]
    out += [f"{a} {b}" for a, b in zip(toks, toks[1:]) if a not in STOP and b not in STOP
            and len(a) > 2 and len(b) > 2]
    return out


def phrases(text):
    toks = tokens(text)
    out = []
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in STOP or g[-1] in STOP or sum(w not in STOP for w in g) < 2:
                continue
            out.append(" ".join(g))
    return out


def g2(a, b, c, d):
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    s = 0.0
    if a:
        s += a * math.log(a / e1)
    if b:
        s += b * math.log(b / e2)
    return 2 * s


def log_ratio(a, b, c, d):
    return math.log2(((a or 0.5) / c) / ((b or 0.5) / d))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--min-reach", type=int, default=2)
    ap.add_argument("--min-freq", type=int, default=3)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    work = Path(args.work)
    manifest = load_manifest(work)
    mode = study_mode(manifest)
    tindex = turn_index(work)

    def unit(tid, turn):
        return turn.get("author_id") if mode == "reddit" else tid

    out = {"mode": mode}

    # 1. keyness from the sentiment sample
    recs = []
    sdir = work / "sentiment"
    for p in sorted(sdir.glob("*.json")) if sdir.exists() else []:
        d = load_json(p)
        recs += d.get("records", d) if isinstance(d, dict) else d
    if recs:
        groups = {"negative": Counter(), "positive": Counter()}
        reach = {"negative": defaultdict(set), "positive": defaultdict(set)}
        ndocs = Counter()
        for r in {r["ref"]: r for r in recs}.values():
            side = "negative" if r["overall"] < 0 else "positive" if r["overall"] > 0 else None
            if not side:
                continue
            tid, t = r["ref"].split("#")
            turn = tindex.get((tid, int(t)))
            if not turn:
                continue
            ts = terms(turn["text"])
            groups[side].update(ts)
            ndocs[side] += 1
            for x in set(ts):
                reach[side][x].add(unit(tid, turn))
        c = sum(v for k, v in groups["negative"].items() if " " not in k) or 1
        d = sum(v for k, v in groups["positive"].items() if " " not in k) or 1
        key = {"negative": [], "positive": []}
        for side, other, cs, ds in (("negative", "positive", c, d), ("positive", "negative", d, c)):
            for term, a in groups[side].items():
                b = groups[other].get(term, 0)
                if a < args.min_freq or len(reach[side][term]) < args.min_reach:
                    continue
                lr = log_ratio(a, b, cs, ds)
                score = g2(a, b, cs, ds)
                if lr > 0 and score >= 3.84:
                    key[side].append({"term": term, "freq": a, "other_freq": b, "reach": len(reach[side][term]),
                                      "g2": round(score, 1), "log_ratio": round(lr, 2)})
            key[side].sort(key=lambda x: (-x["g2"], -x["reach"]))
            key[side] = key[side][:args.top]
        out["keyness"] = {**key, "basis": {"negative_docs": ndocs["negative"], "positive_docs": ndocs["positive"],
                                           "negative_words": c, "positive_words": d,
                                           "method": "log-likelihood G2 >= 3.84 (p < .05), ranked by G2; "
                                                     "effect size = Log Ratio (log2 of relative frequency)"}}

    # 2. common phrases by reach, 3. signal rates
    ph_reach, ph_freq = defaultdict(set), Counter()
    rates = Counter()
    n_turns = 0
    for m in manifest:
        tid = m["transcript_id"]
        for t in load_turns(work, tid)["turns"]:
            if t["role"] != "participant":
                continue
            for p in phrases(t["text"]):
                ph_reach[p].add(unit(tid, t))
                ph_freq[p] += 1
        s = load_signals(work, tid)
        if s:
            for st in s["turns"]:
                if st.get("words", 0) >= 5:
                    n_turns += 1
                    rates.update(set(st.get("flags", [])))
    common = sorted(((p, len(u)) for p, u in ph_reach.items() if len(u) >= max(3, args.min_reach)),
                    key=lambda x: (-x[1], -len(x[0].split()), -ph_freq[x[0]]))

    def bigrams(p):
        w = p.split()
        return {" ".join(w[i:i + 2]) for i in range(len(w) - 1)}

    # keep the longest version of overlapping phrases that reach about the same people
    kept = []
    for p, r in common:
        if any(r >= 0.8 * rq and (p in q or bigrams(p) & bigrams(q)) for q, rq in kept):
            continue
        kept.append((p, r))
    out["phrases"] = [{"phrase": p, "reach": r, "freq": ph_freq[p]} for p, r in kept[:args.top * 2]]
    out["signal_rates"] = {k: round(100 * rates[k] / n_turns, 1) if n_turns else 0 for k in
                           ("constraint_language", "implicit_request", "workaround_language",
                            "switching_language", "hesitation_cluster")}
    out["signal_basis"] = n_turns
    save_json(out, work / "language.json")

    if "keyness" in out:
        k = out["keyness"]
        print(f"Keyness: {k['basis']['negative_docs']} negative vs {k['basis']['positive_docs']} positive comments")
        print("  Negative:", ", ".join(x["term"] for x in k["negative"][:10]) or "—")
        print("  Positive:", ", ".join(x["term"] for x in k["positive"][:10]) or "—")
    else:
        print("No sentiment records, so no negative/positive keyness.")
    print("Common phrases:", ", ".join(f"{p['phrase']} ({p['reach']})" for p in out["phrases"][:10]))
    print("Signal language (% of comments):", out["signal_rates"])


if __name__ == "__main__":
    main()
