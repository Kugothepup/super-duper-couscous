"""The measurement statistics, ported from drivers.py.

Everything is per comment on the random measurement sample (D8). Every share carries the people
and items it rests on and its status (D11): below 20 people it is a count only, with no percentage,
range or probability. Its range comes from two cluster bootstraps, one resampling people and one
resampling threads (B = 5000, seeded), and the wider is the headline range (D3, D28). A probability
("% of re-draws") comes from both too, and the one nearer 50% is shown (D29).

Ported as drivers.py computes them: the headline shares, the per-person net-negative share, each
aspect's mentions, people, mean, negative rate, share of negative and positive mentions, mention rate
and strong negatives; the driver and strength ranking (aspects with 3+ mentions); stance; the
before/after comparison; direction over time; and the split by source. Changed on purpose: the
resampling (D3, D12, D28), the top-driver rule (D12), and ranges everywhere from the bootstrap (D28).
"""
from __future__ import annotations

import datetime as dt
import random
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from crp import thresholds

BOOT_DRAWS = 5000  # D12 (the skill used 2000)
MIN_MENTIONS = 3  # an aspect needs this many mentions to be ranked
MIN_PER_SIDE = 15  # comments needed on each side of a comparison, and in a period
TOP_SHOWN = {"stance_aspects": 6, "period_aspects": 5, "aspect_shifts": 8}


@dataclass
class Record:
    """One coded comment in the measurement sample."""
    post_id: str
    person: str
    thread: str
    source: str
    search_term: str | None
    time: dt.datetime | None
    overall: int
    aspects: dict[str, int] = field(default_factory=dict)
    stance: int | None = None


def pci(xs) -> tuple[float, float] | None:
    """drivers.py's 95% percentile interval, NaNs dropped."""
    xs = sorted(float(x) for x in xs if x == x)
    if not xs:
        return None
    return (round(xs[int(0.025 * (len(xs) - 1))], 1), round(xs[int(0.975 * (len(xs) - 1))], 1))


def rate(W: np.ndarray, num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """100 x (weighted num) / (weighted den) for each re-draw, NaN where the denominator is 0."""
    top, bottom = W @ num, W @ den
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(bottom > 0, 100 * top / bottom, np.nan)


class Boot:
    """One cluster bootstrap. W[b, i] is how many times record i's cluster was drawn in re-draw b.
    The draws follow drivers.py exactly: random.Random(seed), then one rng.choice over the clusters
    per cluster, with clusters in order of first appearance."""

    def __init__(self, keys: list[str], draws: int, seed: int):
        clusters = list(dict.fromkeys(keys))
        pos = {c: j for j, c in enumerate(clusters)}
        rng = random.Random(seed)
        counts = np.zeros((draws, len(clusters)))
        for b in range(draws):
            row = counts[b]
            for c in [rng.choice(clusters) for _ in clusters]:
                row[pos[c]] += 1
        self.n_clusters = len(clusters)
        self.W = counts[:, [pos[k] for k in keys]]


def wider(ranges: dict[str, tuple | None]) -> dict:
    """Both resampled ranges, and the wider as the headline (people if they tie)."""
    out = {f"range_{k}": v for k, v in ranges.items()}
    given = [(k, v) for k, v in ranges.items() if v is not None]
    if given:
        name, r = max(given, key=lambda kv: kv[1][1] - kv[1][0])  # max keeps the first (people) on a tie
        out |= {"range": r, "range_from": name}
    return out


def nearer_half(probs: dict[str, float | None]) -> dict | None:
    """Both probabilities, and the one nearer 50% (D29; people if they tie)."""
    given = [(k, v) for k, v in probs.items() if v is not None]
    if not given:
        return None
    name, p = min(given, key=lambda kv: abs(kv[1] - 50))
    return {"pct": p, "source": name} | {f"pct_{k}": v for k, v in probs.items()}


class Engine:
    """Shares, comparisons and probabilities on a list of records, with both bootstraps."""

    def __init__(self, records: list[Record], draws: int = BOOT_DRAWS, seed: int = 0):
        self.records = records
        self.draws = draws
        self.people = [r.person for r in records]
        self.boots = {"people": Boot(self.people, draws, seed)}
        threads = [r.thread for r in records]
        if len(set(threads)) >= 2:  # one thread can't be resampled
            self.boots["threads"] = Boot(threads, draws, seed)
        self.one = np.ones(len(records))

    def vec(self, f) -> np.ndarray:
        return np.array([float(f(r)) for r in self.records])

    def method(self, status: str, what: str = "random sample, per comment") -> str:
        if status == "counts-only":
            return f"{what}; count only (fewer than {thresholds.MIN_PEOPLE_FOR_RANGES} people)"
        return (f"{what}; range from {self.draws} re-draws resampling people and threads, "
                "the wider shown")

    def rests_on(self, mask: np.ndarray) -> tuple[int, int, str]:
        people = {p for p, m in zip(self.people, mask) if m}
        n_items = int(np.count_nonzero(mask))
        return len(people), n_items, thresholds.result_status(len(people), n_items)

    def share(self, num: np.ndarray, den: np.ndarray, rests_on: np.ndarray | None = None,
              what: str = "random sample, per comment") -> dict:
        """k = sum(num) of n = sum(den). The status comes from the comments it rests on (default: den > 0)."""
        k, n = int(num.sum()), int(den.sum())
        n_people, n_items, status = self.rests_on(den > 0 if rests_on is None else rests_on)
        out = {"k": k, "n": n, "n_people": n_people, "n_items": n_items, "status": status,
               "method": self.method(status, what)}
        if status == "counts-only":
            return out
        out["pct"] = round(100 * k / n, 1) if n else None
        return out | wider({name: pci(rate(b.W, num, den)) for name, b in self.boots.items()})

    def probability(self, hits: dict[str, np.ndarray]) -> dict | None:
        """% of re-draws where something held; hits[name] is a boolean per re-draw."""
        return nearer_half({name: round(100 * float(h.sum()) / self.draws, 1) for name, h in hits.items()})

    def compare(self, measure: str, num: np.ndarray, before: np.ndarray, after: np.ndarray,
                words: tuple[str, str] = ("rose", "fell")) -> dict:
        """after minus before, in points, with its resampled range and drivers.py's verdict rule."""
        b = self.share(num * before, before.astype(float), before, "random sample, before")
        a = self.share(num * after, after.astype(float), after, "random sample, after")
        out = {"measure": measure, "before": b, "after": a, "verdict": "insufficient data", "diff_pts": None}
        _, _, status = self.rests_on(before | after)
        if status == "counts-only" or b.get("pct") is None or a.get("pct") is None:
            return out
        out["diff_pts"] = round(a["pct"] - b["pct"], 1)
        out |= wider({name: pci(rate(bt.W, num * after, after.astype(float)) - rate(bt.W, num * before, before.astype(float)))
                      for name, bt in self.boots.items()})
        if before.sum() >= MIN_PER_SIDE and after.sum() >= MIN_PER_SIDE and out.get("range"):
            lo, hi = out["range"]
            out["verdict"] = words[0] if lo > 0 else words[1] if hi < 0 else "no clear change"
        return out


# ---- the measures ------------------------------------------------------------

def headline(eng: Engine) -> dict:
    neg = eng.vec(lambda r: r.overall < 0)
    pos = eng.vec(lambda r: r.overall > 0)
    out = {"negative": eng.share(neg, eng.one), "neutral": eng.share(eng.one - neg - pos, eng.one),
           "positive": eng.share(pos, eng.one), "people_net_negative": people_net_negative(eng)}
    if out["negative"]["status"] != "counts-only":
        out["mean"] = round(sum(r.overall for r in eng.records) / len(eng.records), 2)
    return out


def people_net_negative(eng: Engine) -> dict:
    """Share of people whose mean overall score is below 0 (D8's secondary figure). In a re-draw each
    person counts as often as they were drawn (their mean weight across their comments)."""
    people = list(dict.fromkeys(eng.people))
    col = {p: j for j, p in enumerate(people)}
    P = np.zeros((len(eng.records), len(people)))
    for i, p in enumerate(eng.people):
        P[i, col[p]] = 1
    overall = eng.vec(lambda r: r.overall)
    means = (overall @ P) / P.sum(axis=0)
    k, n = int((means < 0).sum()), len(people)
    n_people, n_items, status = eng.rests_on(eng.one > 0)
    out = {"k": k, "n": n, "n_people": n_people, "n_items": n_items, "status": status,
           "method": eng.method(status, "random sample, per person (mean score below 0)")}
    if status == "counts-only":
        return out
    out["pct"] = round(100 * k / n, 1)
    reps = {}
    for name, b in eng.boots.items():
        WS, MS = b.W @ P, b.W @ (P * overall[:, None])
        mult = WS / P.sum(axis=0)
        reps[name] = pci(100 * (mult * (MS < 0)).sum(axis=1) / mult.sum(axis=1))
    return out | wider(reps)


def aspect_matrix(eng: Engine) -> tuple[list[str], np.ndarray]:
    """Aspect names (sorted), and each comment's score per aspect (NaN if not mentioned)."""
    names = sorted({a.strip().lower() for r in eng.records for a in r.aspects})
    S = np.full((len(eng.records), len(names)), np.nan)
    col = {a: j for j, a in enumerate(names)}
    for i, r in enumerate(eng.records):
        for a, s in r.aspects.items():
            S[i, col[a.strip().lower()]] = s
    return names, S


def top_driver_hits(eng: Engine, names: list[str], S: np.ndarray, ranked: list[str],
                    rule: str = "d12") -> dict[str, dict[str, np.ndarray]]:
    """For each bootstrap, for each aspect: was it the top driver in each re-draw?
    rule "d12": only ranked aspects compete, and a re-draw with no negative mention of them has no top driver.
    rule "skill": drivers.py's rule, every aspect competes whenever any aspect is mentioned (for the D12 log)."""
    neg = (S < 0).astype(float)
    mentioned = ~np.isnan(S)
    compete = sorted(names.index(a) for a in (ranked if rule == "d12" else names))  # alphabetical, for ties
    out = {}
    for bname, b in eng.boots.items():
        negc = (b.W @ neg)[:, compete]
        best = negc.argmax(axis=1)  # ties go to the first, i.e. alphabetically first (as drivers.py)
        if rule == "d12":
            has_top = negc.max(axis=1) > 0 if compete else np.zeros(eng.draws, bool)
        else:
            has_top = (b.W @ mentioned.astype(float)).sum(axis=1) > 0
        out[bname] = {names[j]: (best == i) & has_top for i, j in enumerate(compete)}
    return out


def aspects(eng: Engine, min_mentions: int = MIN_MENTIONS, rule: str = "d12") -> dict:
    names, S = aspect_matrix(eng)
    mentioned = ~np.isnan(S)
    neg, pos = (S < 0).astype(float), (S > 0).astype(float)
    tot_neg, tot_pos = neg.sum(axis=1), pos.sum(axis=1)
    rows = []
    for j, a in enumerate(names):
        m = mentioned[:, j]
        scores = S[m, j]
        rows.append({"aspect": a, "mentions": int(m.sum()),
                     "people": len({p for p, x in zip(eng.people, m) if x}),
                     "_mean": round(float(scores.mean()), 2), "strong_negative": int((scores <= -2).sum()),
                     "negative_rate": eng.share(neg[:, j], m.astype(float), m, "random sample, of comments mentioning it"),
                     "share_of_negative": eng.share(neg[:, j], tot_neg, eng.one > 0,
                                                    "random sample, of all negative aspect mentions"),
                     "share_of_positive": eng.share(pos[:, j], tot_pos, eng.one > 0,
                                                    "random sample, of all positive aspect mentions"),
                     "mention_rate": eng.share(m.astype(float), eng.one, eng.one > 0,
                                               "random sample, of comments")})

    def pct(sh: dict) -> float:  # as drivers.py ranks: rounded share, 0 when there are no mentions
        return round(100 * sh["k"] / sh["n"], 1) if sh["n"] else 0.0

    first = list(dict.fromkeys(a.strip().lower() for r in eng.records for a in r.aspects))
    rows.sort(key=lambda r: first.index(r["aspect"]))  # drivers.py's order: ties stay in order of first mention
    ranked = [r for r in rows if r["mentions"] >= min_mentions]
    for r in rows:
        r["ranked"] = r["mentions"] >= min_mentions
    drivers = sorted([r for r in ranked if pct(r["share_of_negative"]) > 0],
                     key=lambda r: (-pct(r["share_of_negative"]), r["_mean"]))
    strengths = sorted([r for r in ranked if pct(r["share_of_positive"]) > 0], key=lambda r: -pct(r["share_of_positive"]))
    counts_only = eng.rests_on(eng.one > 0)[2] == "counts-only"
    if not counts_only:
        hits = top_driver_hits(eng, names, S, [r["aspect"] for r in ranked], rule)
        for r in rows:
            if r["ranked"] or rule == "skill":
                r["top_driver"] = eng.probability({b: h[r["aspect"]] for b, h in hits.items()})
    for r in rows:
        mean = r.pop("_mean")
        r["mean"] = None if counts_only else mean
    return {"aspects": rows, "drivers": [r["aspect"] for r in drivers], "strengths": [r["aspect"] for r in strengths],
            "rare": sorted(r["aspect"] for r in rows if not r["ranked"])}


def most_common(masked: list[Record], n: int) -> list[str]:
    """Aspect names by how many of these comments mention them, ties in order of first mention (Counter)."""
    c = Counter(a.lower() for r in masked for a in r.aspects)
    return [a for a, _ in c.most_common(n)]


def stance(eng: Engine, target: str | None) -> dict | None:
    has = eng.vec(lambda r: r.stance is not None)
    if not has.any():
        return None
    st = np.array([r.stance if r.stance is not None else 0 for r in eng.records], dtype=float)
    fav, ag = has * (st > 0), has * (st < 0)
    out = {"target": target, "expressing": eng.share(has, eng.one, eng.one > 0, "random sample, of comments"),
           "in_favour": eng.share(fav, has, has > 0, "random sample, of comments taking a position"),
           "against": eng.share(ag, has, has > 0, "random sample, of comments taking a position"),
           "neither": eng.share(has * (st == 0), has, has > 0, "random sample, of comments taking a position"),
           "talks_about": {}}
    for side, mask in (("in_favour", fav), ("against", ag)):
        chosen = [r for r, m in zip(eng.records, mask) if m]
        out["talks_about"][side] = {
            a: eng.share(mask * eng.vec(lambda r, a=a: a in {x.lower() for x in r.aspects}), mask, mask > 0,
                         "random sample, of comments on this side")
            for a in most_common(chosen, TOP_SHOWN["stance_aspects"])}
    return out


def at_midnight(day: dt.date, like: dt.datetime) -> dt.datetime:
    start = dt.datetime.combine(day, dt.time())
    return start.replace(tzinfo=dt.timezone.utc) if like.tzinfo else start


def event(eng: Engine, day: dt.date | None) -> dict | None:
    timed = [r.time for r in eng.records if r.time]
    if day is None or not timed:
        return None
    cut = at_midnight(day, timed[0])
    before = np.array([r.time is not None and r.time < cut for r in eng.records])
    after = np.array([r.time is not None and r.time >= cut for r in eng.records])
    measures = [eng.compare("negative", eng.vec(lambda r: r.overall < 0), before, after)]
    has = eng.vec(lambda r: r.stance is not None) > 0
    if (has & before).any() and (has & after).any():
        measures.append(eng.compare("in_favour", eng.vec(lambda r: (r.stance or 0) > 0), before & has, after & has))
    shifts = []
    for a in aspect_matrix(eng)[0]:
        c = eng.compare(a, eng.vec(lambda r, a=a: a in {x.lower() for x in r.aspects}), before, after)
        if c["verdict"] in ("rose", "fell"):
            shifts.append(c)
    shifts.sort(key=lambda c: -abs(c["diff_pts"]))
    return {"date": day, "measures": measures, "aspect_shifts": shifts[:TOP_SHOWN["aspect_shifts"]],
            "note": "Before and after the event date, in the random sample. Other things change over time too, "
                    "so a shift is consistent with the event's effect but doesn't prove it."}


def period_key(t: dt.datetime, unit: str) -> str:
    if unit == "month":
        return t.strftime("%Y-%m")
    iso = t.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def direction(eng: Engine, switching: list[tuple[dt.datetime, str, bool]]) -> dict:
    """Negativity per period, drivers.py's rules for the unit and the verdict (first against last usable
    period), with the verdict now from the resampled difference (D28). switching: (time, person, flagged)
    for every forum post of 8+ words in the collection, not just the sample."""
    times = [r.time for r in eng.records if r.time]
    if not times:
        return {"status": "no timestamps"}
    span = (max(times) - min(times)).days
    unit = "month" if span > 60 else "week" if span > 14 else None
    if unit is None:
        return {"status": "single window", "span_days": span,
                "note": "All sampled comments fall within about two weeks, so this is a snapshot. "
                        "Collect threads across several months to see direction."}
    keys = [period_key(r.time, unit) if r.time else None for r in eng.records]
    neg = eng.vec(lambda r: r.overall < 0)
    periods, masks = [], {}
    for k in sorted({k for k in keys if k}):
        mask = np.array([x == k for x in keys])
        masks[k] = mask
        chosen = [r for r, m in zip(eng.records, mask) if m]
        periods.append({"period": k, "negative": eng.share(neg * mask, mask.astype(float), mask, "random sample, this period"),
                        "top_aspects": {a: eng.share(mask * eng.vec(lambda r, a=a: a in {x.lower() for x in r.aspects}),
                                                     mask.astype(float), mask, "random sample, this period")
                                        for a in most_common(chosen, TOP_SHOWN["period_aspects"])}})
    usable = [k for k in masks if masks[k].sum() >= MIN_PER_SIDE]
    out = {"status": "ok", "unit": unit, "span_days": span, "periods": periods, "usable_periods": usable}
    if len(usable) >= 2:
        out["trend"] = eng.compare(f"negative, {usable[0]} against {usable[-1]}", neg, masks[usable[0]],
                                   masks[usable[-1]], ("worsening", "improving"))
    by = {}
    for t, person, flagged in switching:
        by.setdefault(period_key(t, unit), []).append((person, flagged))
    out["switching"] = {}
    for k, rows in sorted(by.items()):
        n_people = len({p for p, _ in rows})
        status = thresholds.result_status(n_people, len(rows))
        sh = {"k": sum(f for _, f in rows), "n": len(rows), "n_people": n_people, "n_items": len(rows),
              "status": status, "method": "all forum posts of 8 or more words in the collection; count"}
        if status != "counts-only":
            sh["pct"] = round(100 * sh["k"] / sh["n"], 1)
        out["switching"][k] = sh
    return out


def by_source(eng: Engine) -> tuple[list[dict], str | None]:
    order = Counter(r.source for r in eng.records)
    rows = []
    neg = eng.vec(lambda r: r.overall < 0)
    for src, _ in sorted(order.items(), key=lambda kv: -kv[1]):
        mask = eng.vec(lambda r, s=src: r.source == s)
        rows.append({"source": src, "share_of_sample": eng.share(mask, eng.one, eng.one > 0, "random sample, of comments"),
                     "negative": eng.share(neg * mask, mask, mask > 0, "random sample, this source")})
    dominant = None
    if len(rows) > 1 and round(100 * rows[0]["share_of_sample"]["k"] / len(eng.records), 1) > 50:
        dominant = rows[0]["source"]  # drivers.py: over 50% of the sample, as rounded
    return rows, dominant
