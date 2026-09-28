"""Verdict words and safe wording, generated from results.json values and statuses.

Ported from dashboard.js and build_report.py: the verdict leans negative or positive when one side is more
than 15 points ahead, "Leaning" rather than "Mostly" in a small sample; stance reads "Mostly for", "Mostly
against" or "Divided" the same way. Changed on purpose: each sentence keeps one unit (D8), comments or
people, never both in one percentage claim; a count-only result (fewer than 20 people, D11) is worded as a
count; and ranges say "within this collection", since they describe these posts, not a population.
"""
from __future__ import annotations

from crp import thresholds
from crp.schemas import Study

GAP = 15  # points: the verdict rule in dashboard.js and build_report.py


def join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def range_text(sh: dict) -> str:
    r = sh.get("range")
    return f"likely {r[0]}–{r[1]}% within this collection" if r else "no range"


def verdict(r: dict, study: Study) -> str:
    h, st = r.get("headline"), r.get("stance")
    if study.type in ("news", "topic") and st and st["in_favour"].get("pct") is not None:
        g = st["in_favour"]["pct"] - st["against"]["pct"]
        word = "Mostly for" if g > GAP else "Mostly against" if g < -GAP else "Divided"
        return f"{word}: {st['in_favour']['pct']}% for, {st['against']['pct']}% against"
    if not h:
        return f"Findings: {study.subject}"
    neg, pos = h["negative"], h["positive"]
    if neg["status"] == "counts-only":
        return f"Too few people to measure: {neg['k']} of {neg['n']} sampled comments were negative"
    small = neg["status"] == "early-signal"
    gap = neg["pct"] - pos["pct"]
    side = "negative" if gap > GAP else "positive" if gap < -GAP else None
    mood = "Mixed" if side is None else ("Leaning " if small else "Mostly ") + side
    tops = r.get("drivers", [])[:2 if small else 3]
    about = (", mostly about " if small else ", driven by ") + join(tops) if tops else ""
    return mood + about + (", in a small sample" if small else "")


def who(r: dict, sources: list[str]) -> str:
    c = r.get("collection") or {}
    w = c.get("window")
    window = "" if not w else f" on {w[0]}" if w[0] == w[1] else f" between {w[0]} and {w[1]}"
    return f"posting in {join(sources)}{window}" if sources else window.strip()


def safe_wording(r: dict, study: Study, sources: list[str]) -> str | None:
    """A sentence for a deck that stays within what the data supports. One unit per sentence (D8)."""
    h, st = r.get("headline"), r.get("stance")
    place = who(r, sources)
    if study.type in ("news", "topic") and st:
        f, a = st["in_favour"], st["against"]
        if f["status"] == "counts-only":
            return (f"Of {f['n']} sampled comments from people {place} that took a position on \"{study.stance_target}\", "
                    f"{f['k']} supported it and {a['k']} opposed it. With fewer than "
                    f"{thresholds.MIN_PEOPLE_FOR_RANGES} people, these are counts, not measured shares.")
        return (f"Of {f['n']} sampled comments from people {place} that took a position on \"{study.stance_target}\", "
                f"{f['pct']}% supported it ({range_text(f)}) and {a['pct']}% opposed it ({range_text(a)}).")
    if not h:
        return None
    neg = h["negative"]
    top = (r.get("drivers") or [None])[0]
    base = f"In a random sample of {neg['n']} comments from {neg['n_people']} people {place}"
    if neg["status"] == "full":
        return (f"{base}, {neg['pct']}% of the comments were negative ({range_text(neg)})"
                + (f", most often about {top}." if top else "."))
    tail = ("This is an early signal from a small sample, not a measured share." if neg["status"] == "early-signal"
            else f"With fewer than {thresholds.MIN_PEOPLE_FOR_RANGES} people, this is a count, not a measured share.")
    return f"{base}, {neg['k']} of the {neg['n']} comments were negative" + (f", most often about {top}. " if top else ". ") + tail


def population_note(study: Study) -> str:
    whom = "the public" if study.type in ("news", "topic") else "customers"
    return f"Describes people who chose to post, not all {whom}. Avoid \"users think\" or \"most people\"."
