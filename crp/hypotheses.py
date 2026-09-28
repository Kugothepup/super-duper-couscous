"""Hypotheses for discovery, scored. Ported from hypotheses.py.

Signal tests:
  top_driver {aspect}                   % of re-draws in which the aspect is the top driver (D12's rule)
  greater    {a, b, measure}            % of re-draws in which a's measure beats b's
  above      {aspect, measure, threshold}  % of re-draws in which the measure is above the threshold (in %)
  proportion {k_ids, n_ids}             k of n people, with a range from resampling those people
  (no test)  {for, against}             people on each side
Probabilities come from both bootstraps, and the one nearer 50% is shown (D29). None is given below
20 people in the sample, and a proportion over fewer than 20 people is a count only (D11).
Leans, strength and priority follow hypotheses.py: a probability of 80%+ leans for and 20% or less
against; a proportion leans when its whole range is above or below 50%; people lean when one side has
2+ and at least twice the other. Overall: all informative signals one way leans that way, both ways is
mixed, none is "can't tell from this data". Strength is weak under 5 people or a sample under 60,
moderate under 15, else strong. Priority: low importance parks it; formed hypotheses are always "test
first" (this data suggested them, so it can't test them); stated ones are "build on it, keep checking"
only when evidenced.
"""
from __future__ import annotations

import random

import numpy as np

from crp import thresholds
from crp.schemas import Hypothesis
from crp.stats import MIN_MENTIONS, Engine, nearer_half, pci, rate, top_driver_hits
from crp.synthesis import Nugget

LEAN_FOR, LEAN_AGAINST = 80.0, 20.0
SMALL_SAMPLE = thresholds.MIN_ITEMS_FOR_FULL


def replicate_series(eng: Engine, names: list[str], S: np.ndarray, measure: str, aspect: str) -> dict[str, np.ndarray]:
    """The measure for one aspect in every re-draw, per bootstrap (as drivers_boot.json stored it)."""
    j = names.index(aspect)
    neg, mentioned = (S < 0).astype(float), (~np.isnan(S)).astype(float)
    out = {}
    for name, b in eng.boots.items():
        if measure == "share_of_negative":  # drivers.py divides by (total negative mentions or 1)
            top, tot = b.W @ neg[:, j], b.W @ neg.sum(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                out[name] = np.where(tot > 0, 100 * top / tot, 0.0)
        elif measure == "negative_rate":
            out[name] = rate(b.W, neg[:, j], mentioned[:, j])
        else:
            out[name] = rate(b.W, mentioned[:, j], eng.one)
    return out


def probability(hits: dict[str, np.ndarray]) -> dict | None:
    """hits: 1, 0 or NaN (can't tell) per re-draw. The % of re-draws that can tell, per bootstrap."""
    probs = {}
    for name, h in hits.items():
        valid = h[~np.isnan(h)]
        probs[name] = round(100 * float(valid.sum()) / len(valid), 1) if len(valid) else None
    return nearer_half(probs)


def lean_of(p: float | None) -> str:
    return "unclear" if p is None else "for" if p >= LEAN_FOR else "against" if p <= LEAN_AGAINST else "unclear"


def proportion(k_people: set, n_people: set, n_items: int, draws: int, seed: int) -> dict:
    k, n = len(k_people & n_people), len(n_people)
    status = thresholds.result_status(n, n_items)
    share = {"k": k, "n": n, "n_people": n, "n_items": n_items, "status": status,
             "method": "coded posts, per person" + ("; count only (fewer than 20 people)" if status == "counts-only"
                                                    else f"; range from {draws} re-draws resampling these people")}
    if status == "counts-only":
        return share
    voters = sorted(n_people)
    rng = random.Random(seed)
    reps = [100 * sum(v in k_people for v in [rng.choice(voters) for _ in voters]) / n for _ in range(draws)]
    r = pci(reps)
    return share | {"pct": round(100 * k / n, 1), "range": r, "range_from": "people", "range_people": r}


def score(hyps: list[Hypothesis], nuggets: dict[str, Nugget], eng: Engine | None, sample_items: int,
          sample_people: int, draws: int, seed: int) -> dict:
    from crp.stats import aspect_matrix
    errors, warnings, results = [], [], []
    names, S = aspect_matrix(eng) if eng else ([], np.zeros((0, 0)))
    mentions = {a: int((~np.isnan(S[:, j])).sum()) for j, a in enumerate(names)}
    ranked = [a for a in names if mentions[a] >= MIN_MENTIONS]
    probabilities = eng is not None and thresholds.result_status(sample_people, sample_items) != "counts-only"
    hits = top_driver_hits(eng, names, S, ranked) if probabilities else {}

    def people_of(ids: list[str]) -> set:
        return {nuggets[i].person for i in ids if i in nuggets}

    for h in hyps:
        sigs, all_ids = [], []
        for sg in h.signals:
            out: dict = {"id": sg.id, "kind": sg.test.type if sg.test else "voices"}
            t = sg.test
            if t is not None and t.type in ("top_driver", "greater", "above"):
                used = [a for a in (getattr(t, f, None) for f in ("aspect", "a", "b")) if a]
                missing = [a for a in used if a not in names]
                if missing:
                    errors.append(f"{h.id}/{sg.id}: {missing} isn't mentioned in the measurement sample")
                    continue
                if not probabilities:
                    out["note"] = "too few people in the sample for a probability (D11)"
                elif t.type == "top_driver" and t.aspect not in ranked:
                    out["note"] = f"{t.aspect} has fewer than {MIN_MENTIONS} mentions, so it can't be the top driver (D12)"
                elif t.type == "top_driver":
                    out["probability"] = probability({b: h_[t.aspect].astype(float) for b, h_ in hits.items()})
                elif t.type == "greater":
                    sa = replicate_series(eng, names, S, t.measure, t.a)
                    sb = replicate_series(eng, names, S, t.measure, t.b)
                    out["probability"] = probability({b: np.where(np.isnan(sa[b]) | np.isnan(sb[b]), np.nan,
                                                                  (sa[b] > sb[b]).astype(float)) for b in sa})
                else:
                    sa = replicate_series(eng, names, S, t.measure, t.aspect)
                    out["probability"] = probability({b: np.where(np.isnan(v), np.nan, (v > t.threshold).astype(float))
                                                      for b, v in sa.items()})
                p = out.get("probability")
                out["lean"] = lean_of(p["pct"] if p else None)
            elif t is not None:  # proportion
                share = proportion(people_of(t.k_ids), people_of(t.n_ids), len([i for i in t.n_ids if i in nuggets]),
                                   draws, seed)
                out["share"] = share
                r = share.get("range")
                out["lean"] = "unclear" if r is None else "for" if r[0] > 50 else "against" if r[1] < 50 else "unclear"
                if r is None:
                    out["note"] = "fewer than 20 people: a count only (D11)"
                all_ids += t.n_ids
            else:
                vf, va = len(people_of(sg.for_ids)), len(people_of(sg.against_ids))
                out |= {"voices_for": vf, "voices_against": va,
                        "lean": "for" if vf >= 2 and vf >= 2 * va else "against" if va >= 2 and va >= 2 * vf
                        else "unclear"}
                all_ids += sg.for_ids + sg.against_ids
            sigs.append(out)
        leans = {s["lean"] for s in sigs if s["lean"] != "unclear"}
        lean = ("can't tell from this data" if not leans else "leans for" if leans == {"for"}
                else "leans against" if leans == {"against"} else "mixed")
        voices = len(people_of(all_ids))
        if any(s.get("probability") and s["lean"] != "unclear" for s in sigs):
            voices = max(voices, sample_people)  # measured on the whole random sample
        small = sample_items < SMALL_SAMPLE
        strength = "weak" if voices < 5 or small else "moderate" if voices < 15 else "strong"
        evidenced = strength != "weak" and lean in ("leans for", "leans against")
        priority = ("park for now" if h.importance == "low" else "test first" if h.origin == "formed"
                    else "build on it, keep checking" if evidenced else "test first")
        if h.origin == "formed" and lean == "leans against":
            warnings.append(f"{h.id}: formed from this data, yet the same data leans against it; reword it or drop it")
        results.append({"id": h.id, "origin": h.origin, "importance": h.importance, "lean": lean,
                        "strength": strength, "voices": voices, "small_sample": small, "priority": priority,
                        "signals": sigs})
    stated = [r for r in results if r["origin"] == "stated"]
    if stated and len(stated) == len(results) and all(r["lean"] == "leans for" for r in stated):
        warnings.append("Only your own hypotheses, all leaning for. Add at least one rival or formed hypothesis, "
                        "so discovery tests alternatives, not just your view.")
    return {"hypotheses": results, "errors": errors, "warnings": warnings}
