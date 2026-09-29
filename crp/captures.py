"""Forum posts the AI transcribed from pastes and screenshots (raw/capture/*.json), ported from parse_forum.py.

A capture file, written by the AI following the coding guide (section 10):
{"source_file": "forum_thread_1.txt",   # the paste or screenshot, relative to raw/
 "site": "Notion community forum", "url": "https://...", "captured": "2026-09-20",
 "thread_title": "...", "search_query": "notion pricing researchers",
 "posts": [{"id": "p1", "author": "maria_k", "date": "2026-09-02", "date_approx": false,
            "parent": null, "score": 14, "text": "verbatim post text"}]}

This module parses and de-duplicates. Whether each text matches its source is crp verify's job.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from crp.io import InputError
from crp.text import clean_quotes, jaccard, loose, shingles

TEXT_EXT = {".txt", ".md", ".html", ".htm"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PROMO = re.compile(r"(use (?:my )?code|discount code|affiliate|dm me|check out my|sign up (?:here|at)|"
                   r"link in (?:my )?bio|promo|sponsored|referral)", re.I)
MIN_WORDS_EXACT_DUP = 6
MIN_WORDS_NEAR_DUP = 12
NEAR_DUP = 0.8


@dataclass
class Thread:
    key: str  # capture file name
    source: str
    source_file: str
    capture_method: str
    title: str | None
    search_term: str | None
    turns: list[dict] = field(default_factory=list)


def _date(s: object) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(s), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def is_promotional(text: str) -> bool:
    return bool(PROMO.search(text)) or text.count("http") >= 3


def read_captures(raw: Path) -> tuple[list[Thread], dict]:
    """Parse every capture file. Structural problems raise InputError listing all of them."""
    caps = sorted((raw / "capture").glob("*.json"))
    errors, warnings, loaded = [], [], []
    for cp in caps:
        where = f"capture/{cp.name}"
        try:
            cap = json.loads(cp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err:
            errors.append(f"{where}: not valid JSON ({err.msg})")
            continue
        sf = cap.get("source_file")
        if not sf or not (raw / sf).exists():
            errors.append(f"{where}: source_file '{sf}' not found in raw/")
            continue
        suf = Path(sf).suffix.lower()
        if suf not in TEXT_EXT | IMG_EXT:
            errors.append(f"{where}: source_file '{sf}' is neither a text paste nor an image")
            continue
        posts = cap.get("posts") or []
        if not posts:
            errors.append(f"{where}: no posts")
            continue
        ids = [p.get("id") for p in posts]
        if len(set(ids)) != len(ids):
            errors.append(f"{where}: duplicate post ids")
        if not _date(cap.get("captured")):
            warnings.append(f"{where}: no valid 'captured' date; relative dates can't be checked")
        for p in posts:
            pw = f"{where}/{p.get('id')}"
            text = clean_quotes(p.get("text") or "").strip()
            if not text:
                errors.append(f"{pw}: empty text")
            if p.get("parent") and p["parent"] not in ids:
                errors.append(f"{pw}: parent '{p['parent']}' not in this capture")
            if p.get("date") and not _date(p["date"]):
                errors.append(f"{pw}: date must be YYYY-MM-DD (convert '2 years ago' using the capture date "
                              "and set date_approx: true)")
            p["text"] = text
        loaded.append((cp, cap, suf))
    if errors:
        raise InputError("\n".join(errors) + f"\n{len(errors)} problem(s) in the capture files; nothing was written.")

    # de-duplicate across all captures (cross-posts, quoted reposts, the same thread captured twice)
    seen_exact: set[str] = set()
    seen_sh: list[set] = []
    dropped: Counter = Counter()
    for _, cap, _ in loaded:
        keep = []
        for p in cap["posts"]:
            key = loose(p["text"])
            if len(key.split()) >= MIN_WORDS_EXACT_DUP and key in seen_exact:
                dropped["exact"] += 1
                continue
            sh = shingles(p["text"])
            if len(key.split()) >= MIN_WORDS_NEAR_DUP and any(jaccard(sh, o) >= NEAR_DUP for o in seen_sh):
                dropped["near"] += 1
                continue
            seen_exact.add(key)
            seen_sh.append(sh)
            keep.append(p)
        cap["posts"] = keep

    threads = []
    for cp, cap, suf in loaded:
        th = Thread(key=cp.name, source=cap.get("site") or "unknown site", source_file=cap["source_file"],
                    capture_method="screenshot" if suf in IMG_EXT else "paste",
                    title=cap.get("thread_title") or None, search_term=cap.get("search_query") or None)
        pid = {p["id"]: p for p in cap["posts"]}
        kids = defaultdict(list)
        for p in cap["posts"]:
            (kids[p["parent"]] if p.get("parent") in pid else kids[None]).append(p)
        order: list[tuple[dict, int, int | None]] = []

        def walk(p: dict, depth: int, parent_turn: int | None) -> None:
            order.append((p, depth, parent_turn))
            me = len(order)
            for c in kids[p["id"]]:
                walk(c, depth + 1, me)

        for r in kids[None]:
            walk(r, 0 if r is cap["posts"][0] else 1, None)
        for i, (p, depth, parent_turn) in enumerate(order, 1):
            d = _date(p.get("date"))
            th.turns.append({"turn": i, "parent_turn": parent_turn,
                             "kind": "post" if i == 1 and depth == 0 else "comment",
                             "author": p.get("author") or None, "role": "participant",
                             "timestamp": dt.datetime.combine(d, dt.time(12, 0)) if d else None,
                             "date_approx": bool(p.get("date_approx")) and d is not None,
                             "score": p.get("score"), "promotional": is_promotional(p["text"]),
                             "headline": bool(p.get("headline")) and p is cap["posts"][0],
                             "text": p["text"], "ref": f"{cap['source_file']}#{p['id']}"})
        threads.append(th)
    report = {"capture_files": len(loaded), "duplicates_dropped": dict(dropped), "warnings": warnings,
              "promotional_flagged": sum(t["promotional"] for th in threads for t in th.turns)}
    return threads, report
