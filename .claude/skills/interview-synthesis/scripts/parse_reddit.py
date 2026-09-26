#!/usr/bin/env python3
"""Parse Reddit threads into the same turn format the rest of the pipeline uses.

Each Reddit thread (submission) becomes one "transcript" (T01, T02, ...); the post and
each comment become turns, ordered as a reply tree (parents before replies, siblings
by score). Usernames are replaced with anonymous ids (A001, ...); the mapping is kept
in WORK/authors_private.json and never appears in the report.

Accepted inputs (files or folders):
  .json          thread JSON (the thread URL with .json appended), or a Listing
  .jsonl/.ndjson one object per line, e.g. Pushshift / Arctic Shift style dumps
  .csv           exports with columns like id, parent_id, link_id, author, body,
                 title, score, created_utc (common alternative names are recognised)

Usage:
  python parse_reddit.py INPUT [INPUT ...] --work WORKDIR [--min-words 1] [--keep-bots]
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import clean_quotes, save_json  # noqa: E402

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


def strip_prefix(x):
    x = str(x or "").strip()
    return x.split("_", 1)[1] if re.match(r"^t\d_", x) else x


def to_iso(v):
    try:
        return dt.datetime.fromtimestamp(float(v), dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(v) if v else None


def is_bot(author):
    a = (author or "").lower()
    return a == "automoderator" or a.endswith("bot") or a.endswith("-bot")


def clean_body(text):
    text = html.unescape(clean_quotes(text or ""))
    lines = [l for l in text.splitlines() if not l.lstrip().startswith(">")]  # drop quoted parent text
    text = " ".join(lines)
    text = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)          # markdown links -> text
    text = re.sub(r"\b/?u/[A-Za-z0-9_-]+", "u/[user]", text)           # username mentions
    text = re.sub(r"(\*\*|__|~~|`)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def item(kind, rid, parent, link, author, body, title, score, created, sub):
    return {"kind": kind, "rid": strip_prefix(rid), "parent": strip_prefix(parent) if parent else None,
            "parent_is_post": str(parent or "").startswith("t3_"),
            "link": strip_prefix(link), "author": author or "[deleted]", "body": body or "",
            "title": title or "", "score": int(float(score)) if str(score or "").lstrip("-").replace(".", "", 1).isdigit() else 0,
            "created": to_iso(created), "subreddit": sub or ""}


def walk_listing(node, out, stats, link=None):
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


def from_flat(o):
    if "title" in o and not o.get("parent_id"):
        return item("post", o.get("id"), None, o.get("id"), o.get("author"), o.get("selftext"),
                    o.get("title"), o.get("score"), o.get("created_utc"), o.get("subreddit"))
    return item("comment", o.get("id"), o.get("parent_id"), o.get("link_id"), o.get("author"),
                o.get("body"), None, o.get("score"), o.get("created_utc"), o.get("subreddit"))


def read_csv(path):
    out = []
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return out
    lower = {k.lower().strip(): k for k in rows[0].keys()}
    col = {k: next((lower[c] for c in cands if c in lower), None) for k, cands in COLS.items()}
    if not col["body"] and not col["title"]:
        raise SystemExit(f"{path}: can't find a text column (tried {COLS['body']})")
    g = lambda r, k: r.get(col[k]) if col[k] else None  # noqa: E731
    for i, r in enumerate(rows):
        parent, link = g(r, "parent"), g(r, "link")
        is_post = bool(g(r, "title")) and not parent
        rid = g(r, "id") or f"row{i}"
        if parent and link and strip_prefix(parent) == strip_prefix(link) and not str(parent).startswith("t"):
            parent = "t3_" + strip_prefix(parent)
        out.append(item("post" if is_post else "comment", rid, None if is_post else parent,
                        (rid if is_post else link) or path.stem, g(r, "author"),
                        g(r, "body") if not is_post or col["body"] != col["title"] else "",
                        g(r, "title") if is_post else None, g(r, "score"), g(r, "created"),
                        g(r, "subreddit")))
    return out


def read_file(path, stats):
    suf = path.suffix.lower()
    if suf == ".csv":
        return read_csv(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    if suf in (".jsonl", ".ndjson"):
        return [from_flat(json.loads(l)) for l in text.splitlines() if l.strip()]
    data = json.loads(text)
    out = []
    if isinstance(data, list) and data and isinstance(data[0], dict) and "kind" not in data[0]:
        return [from_flat(o) for o in data]
    walk_listing(data, out, stats)
    return out


def build_thread(items, authors, deleted_counter):
    posts = [i for i in items if i["kind"] == "post"]
    comments = [i for i in items if i["kind"] == "comment"]
    post = posts[0] if posts else None
    op = post["author"] if post else None
    children = defaultdict(list)
    ids = {c["rid"] for c in comments}
    roots = []
    for c in comments:
        if c["parent"] and c["parent"] in ids and not c["parent_is_post"]:
            children[c["parent"]].append(c)
        else:
            roots.append(c)
    turns, rid_to_turn, orphans = [], {}, 0

    def anon(a):
        if a in ("[deleted]", "", None):
            deleted_counter[0] += 1
            return f"D{deleted_counter[0]:03d}"
        if a not in authors:
            authors[a] = f"A{len(authors) + 1:03d}"
        return authors[a]

    def add(it, depth, parent_turn):
        body = clean_body(it["body"])
        if it["kind"] == "post":
            title = clean_body(it["title"])
            sep = " " if title[-1:] in ".?!" else ". "
            text = f"{title}{sep}{body}".strip() if body and body not in DELETED else title
        else:
            text = body
        removed = it["body"].strip() in DELETED and it["kind"] == "comment"
        t = {"turn_id": len(turns) + 1, "speaker": anon(it["author"]), "role": "unknown" if removed else "participant",
             "kind": it["kind"], "author_id": None, "is_op": bool(op) and it["author"] == op and it["author"] not in DELETED,
             "score": it["score"], "depth": depth, "parent_turn": parent_turn, "created": it["created"],
             "start": None, "end": None, "text": "[deleted]" if removed else text}
        t["author_id"] = t["speaker"]
        turns.append(t)
        rid_to_turn[it["rid"]] = t["turn_id"]
        return t["turn_id"]

    def walk(c, depth, parent_turn):
        tid = add(c, depth, parent_turn)
        for ch in sorted(children[c["rid"]], key=lambda x: -x["score"]):
            walk(ch, depth + 1, tid)

    post_turn = add(post, 0, None) if post else None
    for r in sorted(roots, key=lambda x: -x["score"]):
        if r["parent"] and not r["parent_is_post"] and r["parent"] not in ids and post:
            orphans += 1
        walk(r, 1, post_turn)
    return post, turns, orphans


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--work", required=True)
    ap.add_argument("--keep-bots", action="store_true")
    args = ap.parse_args()

    files = []
    for inp in args.inputs:
        p = Path(inp)
        files += [f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED] if p.is_dir() else [p]
    files = sorted(set(files), key=lambda f: f.name.lower())
    if not files:
        raise SystemExit("No .json/.jsonl/.ndjson/.csv files found.")

    by_link, src, stats = defaultdict(list), defaultdict(set), {"more": 0, "bots": 0}
    for f in files:
        for it in read_file(f, stats):
            if not args.keep_bots and is_bot(it["author"]):
                stats["bots"] += 1
                continue
            key = it["link"] or f.stem
            by_link[key].append(it)
            src[key].add(f.name)

    # dedupe by reddit id (same thread exported twice)
    for k, items in by_link.items():
        seen, uniq = set(), []
        for it in items:
            if (it["kind"], it["rid"]) not in seen:
                seen.add((it["kind"], it["rid"]))
                uniq.append(it)
        by_link[k] = uniq

    order = sorted(by_link, key=lambda k: min((i["created"] or "") for i in by_link[k]))
    work = Path(args.work)
    authors, deleted_counter, manifest = {}, [0], []
    for n, key in enumerate(order, 1):
        tid = f"T{n:02d}"
        post, turns, orphans = build_thread(by_link[key], authors, deleted_counter)
        parts = [t for t in turns if t["role"] == "participant"]
        warnings = []
        if not post:
            warnings.append("no submission found for this thread; comments only")
        n_removed = sum(t["role"] == "unknown" for t in turns)
        if n_removed:
            warnings.append(f"{n_removed} deleted/removed comment(s) kept as placeholders")
        if orphans:
            warnings.append(f"{orphans} comment(s) whose parent is missing from the export")
        title = clean_body(post["title"]) if post else ""
        doc = {"transcript_id": tid, "source_type": "reddit", "source_file": ", ".join(sorted(src[key])),
               "title": title, "subreddit": (post or by_link[key][0])["subreddit"],
               "speakers": {t["speaker"]: t["role"] for t in turns},
               "role_method": "reddit (all authors are participants)",
               "has_timestamps": False, "has_end_times": False,
               "participant_words": sum(len(t["text"].split()) for t in parts), "turns": turns}
        save_json(doc, work / "turns" / f"{tid}.json")
        manifest.append({"transcript_id": tid, "source_type": "reddit", "source_file": doc["source_file"],
                         "title": title, "subreddit": doc["subreddit"], "n_turns": len(turns),
                         "n_authors": len({t["author_id"] for t in parts}), "speakers": {},
                         "role_method": doc["role_method"], "participant_words": doc["participant_words"],
                         "warnings": warnings})
    save_json(manifest, work / "manifest.json")
    save_json({v: k for k, v in authors.items()}, work / "authors_private.json")

    total = sum(m["n_turns"] for m in manifest)
    print(f"Parsed {len(manifest)} thread(s), {total} posts+comments, {len(authors)} named authors into {work}\n")
    for m in manifest:
        print(f"{m['transcript_id']}  r/{m['subreddit']}  \"{m['title'][:60]}\"  items={m['n_turns']}  "
              f"authors={m['n_authors']}  words={m['participant_words']}")
        for w in m["warnings"]:
            print(f"     ! {w}")
    if stats["more"]:
        print(f"\n! {stats['more']} collapsed comments ('load more') were not in the export. "
              "Re-export with a higher limit or via the API if completeness matters.")
    if stats["bots"]:
        print(f"Removed {stats['bots']} bot comment(s) (AutoModerator, *bot). Use --keep-bots to keep them.")
    print("authors_private.json maps ids to usernames: keep it out of anything you share.")


if __name__ == "__main__":
    main()
