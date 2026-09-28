"""Shared phrases and signal-language rates, ported from language.py (parts 2 and 3; keyness is keyness.py).

Phrases: two- and three-word phrases ranked by how many different people used them (3 or more), across
every forum post in the collection; where overlapping phrases reach about the same people, the longest
is kept. Signal rates: the share of forum posts of 5+ words carrying each signal flag. Forum posts
only: interviews are counted apart (D14). These are pointers for reading, not estimates, so they carry
counts and no ranges.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from crp import thresholds
from crp.keyness import STOP, tokens
from crp.schemas import Post

MIN_REACH = 3  # language.py: max(3, --min-reach 2)
TOP = 30  # language.py: --top 15, doubled for phrases
RATE_FLAGS = ("constraint_language", "implicit_request", "workaround_language", "switching_language",
              "hesitation_cluster")


def phrases_of(text: str) -> list[str]:
    toks = tokens(text)
    out = []
    for n in (2, 3):
        for i in range(len(toks) - n + 1):
            g = toks[i:i + n]
            if g[0] in STOP or g[-1] in STOP or sum(w not in STOP for w in g) < 2:
                continue
            out.append(" ".join(g))
    return out


def bigrams(p: str) -> set[str]:
    w = p.split()
    return {" ".join(w[i:i + 2]) for i in range(len(w) - 1)}


def phrases(items: list[tuple[str, str]], min_reach: int = MIN_REACH, top: int = TOP) -> list[dict]:
    """items: (text, person). Phrases used by min_reach+ people, overlapping ones merged."""
    reach, freq = defaultdict(set), Counter()
    for text, person in items:
        for p in phrases_of(text):
            reach[p].add(person)
            freq[p] += 1
    common = sorted(((p, len(u)) for p, u in reach.items() if len(u) >= min_reach),
                    key=lambda x: (-x[1], -len(x[0].split()), -freq[x[0]]))
    kept: list[tuple[str, int]] = []
    for p, r in common:
        if any(r >= 0.8 * rq and (p in q or bigrams(p) & bigrams(q)) for q, rq in kept):
            continue
        kept.append((p, r))
    return [{"phrase": p, "reach": r, "freq": freq[p]} for p, r in kept[:top]]


def signal_rates(posts: list[Post], signal_rows: dict[str, dict]) -> dict[str, dict]:
    rows = [(p, signal_rows[p.post_id]) for p in posts
            if p.source_type == "forum" and p.post_id in signal_rows and signal_rows[p.post_id]["words"] >= 5]
    n_people = len({p.person_code for p, _ in rows})
    status = thresholds.result_status(n_people, len(rows))
    out = {}
    for flag in RATE_FLAGS:
        k = sum(flag in r["flags"] for _, r in rows)
        share = {"k": k, "n": len(rows), "n_people": n_people, "n_items": len(rows), "status": status,
                 "method": "all forum posts of 5 or more words in the collection; count"}
        if status != "counts-only":
            share["pct"] = round(100 * k / len(rows), 1) if rows else None
        out[flag] = share
    return out
