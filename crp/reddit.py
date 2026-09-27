"""Reddit exports (raw/reddit/), ported from parse_reddit.py.

Accepts thread JSON (the thread URL with .json appended) or a Listing; .jsonl/.ndjson dumps
(Pushshift / Arctic Shift style); and .csv exports with columns like id, parent_id, link_id,
author, body, title, score, created_utc. Each submission becomes one thread; the post and
comments are ordered as a reply tree, parents before replies, siblings by score.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from collections import defaultdict
from pathlib import Path

from crp.captures import Thread
from crp.io import InputError
from crp.text import clean_quotes

SUPPORTED = {".json", ".jsonl", ".ndjson", ".csv"}
DELETED = {"[deleted]", "[removed]", ""}
COLS = {
    "id": ["id", "comment_id", "name"],
    "parent": ["parent_id", "parent"],
    "link": ["link_id", "post_id", "submission_id", "thread_id"],
    "author": ["author", "username", "user"],
    "body": ["body", "comment", "text", "content", "selftext"],
    "title": ["title", "post_title"],
    "score": ["score", "upvotes", "ups"],
    "created": ["created_utc", "created", "timestamp", "date"],
    "subreddit": ["subreddit"],
}


def strip_prefix(x: object) -> str:
    x = str(x or "").strip()
    return x.split("_", 1)[1] if re.match(r"^t\d_", x) else x


def to_time(v: object) -> dt.datetime | None:
    """Unix seconds (UTC) as the skill reads them; ISO dates and times from CSVs are also accepted (D19)."""
    if v in (None, ""):
        return None
    try:
        t = dt.datetime.fromtimestamp(float(v), dt.timezone.utc)
        return t.replace(second=0, microsecond=0, tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        t = dt.datetime.fromisoformat(str(v).strip())
        return t.replace(tzinfo=None) if t.tzinfo is None else t.astimezone(dt.timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def is_bot(author: str | None) -> bool:
    a = (author or "").lower()
    return a == "automoderator" or a.endswith("bot") or a.endswith("-bot")


def clean_body(text: str | None) -> str:
    text = html.unescape(clean_quotes(text or ""))
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]  # drop quoted parent text
    text = " ".join(lines)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)  # markdown links -> text
    text = re.sub(r"\b/?u/[A-Za-z0-9_-]+", "u/[user]", text)  # username mentions
    text = re.sub(r"(\*\*|__|~~|`)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _score(v: object) -> int:
    s = str(v or "")
    return int(float(s)) if s.lstrip("-").replace(".", "", 1).isdigit() else 0


def item(kind, rid, parent, link, author, body, title, score, created, sub) -> dict:
    return {"kind": kind, "rid": strip_prefix(rid), "parent": strip_prefix(parent) if parent else None,
            "parent_is_post": str(parent or "").startswith("t3_"), "link": strip_prefix(link),
            "author": author or "[deleted]", "body": body or "", "title": title or "", "score": _score(score),
            "created": to_time(created), "subreddit": sub or ""}


def walk_listing(node, out: list, stats: dict, link=None) -> None:
    if isinstance(node, list):
        for n in node:
            walk_listing(n, out, stats, link)
        return
    if not isinstance(node, dict):
        return
    kind, d = node.get("kind"), node.get("data", {})
    if kind == "Listing":
        for c in d.get("children", []):
            walk_listing(c, out, stats, link)
    elif kind == "t3":
        out.append(item("post", d.get("id"), None, d.get("id"), d.get("author"), d.get("selftext"),
                        d.get("title"), d.get("score"), d.get("created_utc"), d.get("subreddit")))
    elif kind == "t1":
        out.append(item("comment", d.get("id"), d.get("parent_id"), d.get("link_id") or link,
                        d.get("author"), d.get("body"), None, d.get("score"), d.get("created_utc"),
                        d.get("subreddit")))
        if isinstance(d.get("replies"), dict):
            walk_listing(d["replies"], out, stats, d.get("link_id") or link)
    elif kind == "more":
        stats["more"] += int(d.get("count") or len(d.get("children", [])))


def from_flat(o: dict) -> dict:
    if "title" in o and not o.get("parent_id"):
        return item("post", o.get("id"), None, o.get("id"), o.get("author"), o.get("selftext"),
                    o.get("title"), o.get("score"), o.get("created_utc"), o.get("subreddit"))
    return item("comment", o.get("id"), o.get("parent_id"), o.get("link_id"), o.get("author"),
                o.get("body"), None, o.get("score"), o.get("created_utc"), o.get("subreddit"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    lower = {k.lower().strip(): k for k in rows[0].keys()}
    col = {k: next((lower[c] for c in cands if c in lower), None) for k, cands in COLS.items()}
    if not col["body"] and not col["title"]:
        raise InputError(f"{path}: can't find a text column (tried {', '.join(COLS['body'])})")

    def g(r: dict, k: str):
        return r.get(col[k]) if col[k] else None

    out = []
    for i, r in enumerate(rows):
        parent, link = g(r, "parent"), g(r, "link")
        is_post = bool(g(r, "title")) and not parent
        rid = g(r, "id") or f"row{i}"
        if parent and link and strip_prefix(parent) == strip_prefix(link) and not str(parent).startswith("t"):
            parent = "t3_" + strip_prefix(parent)
        out.append(item("post" if is_post else "comment", rid, None if is_post else parent,
                        (rid if is_post else link) or path.stem, g(r, "author"),
                        g(r, "body") if not is_post or col["body"] != col["title"] else "",
                        g(r, "title") if is_post else None, g(r, "score"), g(r, "created"), g(r, "subreddit")))
    return out


def read_file(path: Path, stats: dict) -> list[dict]:
    suf = path.suffix.lower()
    if suf == ".csv":
        return read_csv(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        if suf in (".jsonl", ".ndjson"):
            return [from_flat(json.loads(ln)) for ln in text.splitlines() if ln.strip()]
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise InputError(f"{path}: not valid JSON ({err.msg})") from None
    if isinstance(data, list) and data and isinstance(data[0], dict) and "kind" not in data[0]:
        return [from_flat(o) for o in data]
    out: list[dict] = []
    walk_listing(data, out, stats)
    return out


def build_thread(items: list[dict]) -> tuple[dict | None, list[dict], int]:
    posts = [i for i in items if i["kind"] == "post"]
    comments = [i for i in items if i["kind"] == "comment"]
    post = posts[0] if posts else None
    children = defaultdict(list)
    ids = {c["rid"] for c in comments}
    roots = []
    for c in comments:
        if c["parent"] and c["parent"] in ids and not c["parent_is_post"]:
            children[c["parent"]].append(c)
        else:
            roots.append(c)
    turns: list[dict] = []
    orphans = 0

    def add(it: dict, parent_turn: int | None) -> int:
        body = clean_body(it["body"])
        if it["kind"] == "post":
            title = clean_body(it["title"])
            sep = " " if title[-1:] in ".?!" else ". "
            text = f"{title}{sep}{body}".strip() if body and body not in DELETED else title
        else:
            text = body
        removed = it["body"].strip() in DELETED and it["kind"] == "comment"
        author = None if it["author"] in DELETED else it["author"]
        turns.append({"turn": len(turns) + 1, "parent_turn": parent_turn, "kind": it["kind"], "author": author,
                      "role": "unknown" if removed else "participant", "timestamp": it["created"],
                      "date_approx": False, "score": it["score"], "promotional": False,
                      "text": "[deleted]" if removed else text, "ref": it["rid"]})
        return len(turns)

    def walk(c: dict, parent_turn: int | None) -> None:
        me = add(c, parent_turn)
        for ch in sorted(children[c["rid"]], key=lambda x: -x["score"]):
            walk(ch, me)

    post_turn = add(post, None) if post else None
    for r in sorted(roots, key=lambda x: -x["score"]):
        if r["parent"] and not r["parent_is_post"] and r["parent"] not in ids and post:
            orphans += 1
        walk(r, post_turn)
    return post, turns, orphans


def read_exports(folder: Path, keep_bots: bool = False) -> tuple[list[Thread], dict]:
    files = sorted({f for f in folder.rglob("*") if f.suffix.lower() in SUPPORTED}, key=lambda f: f.name.lower()) \
        if folder.is_dir() else []
    by_link: dict[str, list[dict]] = defaultdict(list)
    src: dict[str, set[str]] = defaultdict(set)
    stats = {"more": 0, "bots": 0}
    for f in files:
        for it in read_file(f, stats):
            if not keep_bots and is_bot(it["author"]):
                stats["bots"] += 1
                continue
            key = it["link"] or f.stem
            by_link[key].append(it)
            src[key].add(str(f.relative_to(folder.parent)))
    for k, items in by_link.items():  # the same thread exported twice
        seen, uniq = set(), []
        for it in items:
            if (it["kind"], it["rid"]) not in seen:
                seen.add((it["kind"], it["rid"]))
                uniq.append(it)
        by_link[k] = uniq

    def first_time(k: str) -> str:
        return min((i["created"].strftime("%Y-%m-%d %H:%M") if i["created"] else "") for i in by_link[k])

    threads, warnings = [], []
    for key in sorted(by_link, key=first_time):
        post, turns, orphans = build_thread(by_link[key])
        source_file = ", ".join(sorted(src[key]))
        sub = (post or by_link[key][0])["subreddit"]
        th = Thread(key=key, source=f"reddit.com/r/{sub}" if sub else "reddit.com", source_file=source_file,
                    capture_method="export", title=clean_body(post["title"]) if post else None, search_term=None)
        for t in turns:
            t["ref"] = f"{source_file}#{t['ref']}"
        th.turns = turns
        if not post:
            warnings.append(f"thread {key}: no submission found; comments only")
        n_removed = sum(t["role"] == "unknown" for t in turns)
        if n_removed:
            warnings.append(f"thread {key}: {n_removed} deleted or removed comment(s) kept as placeholders")
        if orphans:
            warnings.append(f"thread {key}: {orphans} comment(s) whose parent is missing from the export")
        threads.append(th)
    if stats["more"]:
        warnings.append(f"{stats['more']} collapsed comments ('load more') were not in the export. "
                        "Re-export with a higher limit or via the API if completeness matters.")
    report = {"export_files": len(files), "bots_removed": stats["bots"], "collapsed_missing": stats["more"],
              "warnings": warnings}
    return threads, report
