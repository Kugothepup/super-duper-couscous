"""Keyness: words and two-word phrases over-used in negative against positive comments, ported from
language.py (tokens, terms, log-likelihood G2 after Dunning 1993, and Log Ratio after Hardie 2014).

D6 changes which terms are kept: frequency 5 or more, used by 3 or more people, and a Benjamini-Hochberg
correction at q = 0.05 across every term tested (the skill kept frequency 3+, 2+ people and G2 >= 3.84 with
no correction). The whole section is hidden below the early-signal threshold. rule="skill" gives the
skill's filter, for the comparison test and the D6 log.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from scipy.stats import chi2
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

STOP = set(ENGLISH_STOP_WORDS) | {
    "yeah", "okay", "ok", "like", "just", "really", "um", "uh", "gonna", "wanna", "lot", "pretty",
    "actually", "honestly", "thing", "things", "stuff", "don't", "didn't", "doesn't", "i'm", "it's",
    "i've", "that's", "there's", "can't", "won't", "isn't", "wasn't", "i'd", "you're", "they're",
    "we're", "i'll", "let's", "user", "u", "got", "get", "going", "know", "think", "say", "said",
    "want", "way", "use", "used", "using", "make", "does", "did", "doing", "also", "still", "even",
}
TOKEN = re.compile(r"[a-z][a-z'\-]*[a-z]|[a-z]")
RULES = {"d6": {"min_freq": 5, "min_reach": 3}, "skill": {"min_freq": 3, "min_reach": 2}}
Q = 0.05
G2_SKILL = 3.84
TOP = 15


def tokens(text: str) -> list[str]:
    text = re.sub(r"u/\[user\]", " ", text.lower().replace("’", "'"))
    return TOKEN.findall(text)


def terms(text: str) -> list[str]:
    toks = tokens(text)
    out = [t for t in toks if t not in STOP and len(t) > 2]
    out += [f"{a} {b}" for a, b in zip(toks, toks[1:]) if a not in STOP and b not in STOP
            and len(a) > 2 and len(b) > 2]
    return out


def g2(a: int, b: int, c: int, d: int) -> float:
    """Log-likelihood for a term seen a times in c words on one side and b times in d words on the other."""
    e1, e2 = c * (a + b) / (c + d), d * (a + b) / (c + d)
    s = 0.0
    if a:
        s += a * math.log(a / e1)
    if b:
        s += b * math.log(b / e2)
    return 2 * s


def log_ratio(a: int, b: int, c: int, d: int) -> float:
    return math.log2(((a or 0.5) / c) / ((b or 0.5) / d))


def bh(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q), in the order given."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        q[i] = running
    return q


def keyness(items: list[tuple[str, str, int]], rule: str = "d6", top: int = TOP) -> dict:
    """items: (text, person, overall score) for each comment in the random sample."""
    groups = {"negative": Counter(), "positive": Counter()}
    reach: dict[str, dict[str, set]] = {"negative": defaultdict(set), "positive": defaultdict(set)}
    docs = Counter()
    for text, person, overall in items:
        side = "negative" if overall < 0 else "positive" if overall > 0 else None
        if not side:
            continue
        ts = terms(text)
        groups[side].update(ts)
        docs[side] += 1
        for x in set(ts):
            reach[side][x].add(person)
    c = sum(v for k, v in groups["negative"].items() if " " not in k) or 1
    d = sum(v for k, v in groups["positive"].items() if " " not in k) or 1
    limits = RULES[rule]
    tested = []
    for side, other, cs, ds in (("negative", "positive", c, d), ("positive", "negative", d, c)):
        for term, a in groups[side].items():
            b = groups[other].get(term, 0)
            if a < limits["min_freq"] or len(reach[side][term]) < limits["min_reach"]:
                continue
            lr = log_ratio(a, b, cs, ds)
            if lr <= 0:
                continue
            score = g2(a, b, cs, ds)
            tested.append({"side": side, "term": term, "freq": a, "other_freq": b, "reach": len(reach[side][term]),
                           "g2": round(score, 1), "log_ratio": round(lr, 2), "p": float(chi2.sf(score, 1)), "_g2": score})
    if rule == "d6":
        for t, q in zip(tested, bh([t["p"] for t in tested])):
            t["q"] = q
        kept = [t for t in tested if t["q"] <= Q]
    else:
        kept = [t for t in tested if t["_g2"] >= G2_SKILL]
    out = {"basis": {"negative_items": docs["negative"], "positive_items": docs["positive"],
                     "negative_words": c, "positive_words": d, "tested": len(tested)}}
    for side in ("negative", "positive"):
        rows = sorted((t for t in kept if t["side"] == side), key=lambda t: (-t["g2"], -t["reach"]))[:top]
        out[side] = [{k: v for k, v in t.items() if k not in ("side", "_g2")} for t in rows]
    return out


METHOD = (f"log-likelihood G2 (Dunning 1993) and Log Ratio (Hardie 2014), negative against positive comments in the "
          f"random sample; kept: frequency {RULES['d6']['min_freq']}+, used by {RULES['d6']['min_reach']}+ people, "
          f"Benjamini-Hochberg q <= {Q} across all terms tested (D6)")
