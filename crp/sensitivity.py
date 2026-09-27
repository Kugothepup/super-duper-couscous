"""How much the headline depends on the collection (D4) and on the caps (D9, D27).

Leave-one-out: the headline (% negative) recomputed with each source, each search term, and each of the
5 largest threads in the sample left out in turn. Reports each, the min and max, and the removal that
moved it most.

Without caps: the sample was drawn with a person cap and a thread cap, so it can't be re-coded
uncapped. Instead each coded comment is weighted by how many eligible posts it stands for (D27):
(person's eligible posts / the posts they kept in the frame) x (thread's posts in the frame / its
posts sampled). Both caps pick at random within a person or thread, so the weighted share estimates
what an uncapped sample would have found.
"""
from __future__ import annotations

from collections import Counter

from crp import thresholds
from crp.stats import Record

LARGEST_THREADS = 5


def point_share(records: list[Record], what: str) -> dict:
    """% negative, as a count-backed share with no range (it's a sensitivity check, not an estimate)."""
    k, n = sum(r.overall < 0 for r in records), len(records)
    n_people = len({r.person for r in records})
    status = thresholds.result_status(n_people, n)
    out = {"k": k, "n": n, "n_people": n_people, "n_items": n, "status": status, "method": what}
    if status != "counts-only":
        out["pct"] = round(100 * k / n, 1) if n else None
    return out


def leave_one_out(records: list[Record], largest: int = LARGEST_THREADS) -> dict:
    base = point_share(records, "random sample")
    removals = []
    sources = list(dict.fromkeys(r.source for r in records))
    terms = sorted({r.search_term for r in records if r.search_term})
    threads = [t for t, _ in sorted(Counter(r.thread for r in records).items(), key=lambda kv: (-kv[1], kv[0]))]
    groups = [("source", s, lambda r, s=s: r.source == s) for s in sources if len(sources) > 1]
    groups += [("search_term", t, lambda r, t=t: r.search_term == t) for t in terms]
    groups += [("thread", t, lambda r, t=t: r.thread == t) for t in threads[:largest] if len(threads) > 1]
    for kind, name, inside in groups:
        rest = [r for r in records if not inside(r)]
        if rest:
            removals.append({"kind": kind, "removed": name,
                             "negative": point_share(rest, f"random sample, leaving out this {kind.replace('_', ' ')}")})
    moved = [(r, r["negative"]["pct"]) for r in removals if r["negative"].get("pct") is not None]
    out: dict = {"removals": removals, "removals_with_pct": len(moved)}
    if moved and base.get("pct") is not None:
        out["min_pct"] = min(p for _, p in moved)
        out["max_pct"] = max(p for _, p in moved)
        r, p = max(moved, key=lambda rp: abs(rp[1] - base["pct"]))  # the first of any tie
        out["most_moved"] = {"kind": r["kind"], "removed": r["removed"], "change_pts": round(p - base["pct"], 1)}
    return out


def cap_weights(records: list[Record], eligible_per_person: Counter, person_cap: int,
                threads: dict[str, dict]) -> list[float]:
    """Each comment's weight for the uncapped estimate (D27). threads: samples/summary.json's per-thread counts."""
    out = []
    for r in records:
        e = eligible_per_person[r.person]
        t = threads[r.thread]
        out.append((e / min(e, person_cap)) * (t["after_person_cap"] / t["sampled"]))
    return out


def without_caps(records: list[Record], weights: list[float]) -> dict:
    n_people = len({r.person for r in records})
    status = thresholds.result_status(n_people, len(records))
    out = {"n_people": n_people, "n_items": len(records), "status": status,
           "method": "random sample, % negative weighted by how many eligible posts each comment stands for "
                     "(person cap and thread cap undone); an estimate (D27)"}
    if status != "counts-only":
        total = sum(weights)
        out["pct"] = round(100 * sum(w for r, w in zip(records, weights) if r.overall < 0) / total, 1)
    return out
