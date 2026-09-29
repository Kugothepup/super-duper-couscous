"""crp paste: turn a copied Reddit thread page into a capture file. Ported from ux-t's forum_source.py (D38).

The paste is saved as raw/<name>.txt and its posts as raw/capture/<name>.json, in the capture format
the skill's reference/capture.md sets out. crp verify then checks every post against the paste word for
word, as for any capture, and crp anonymise replaces the names.

It reads new Reddit's desktop page in both layouts ux-t has seen: a header (title, "r/<community> -
<title>", a link post's domain, the opening post and its votes), then each comment as a name, optional
OP or MOD badges, "•", an age such as "21d ago", the text, and the vote count either after an "Upvote"
line or on its own. Ads, bots, deleted and image-only comments are skipped and counted, and collapsed
replies ("N more replies", "Continue this thread") are counted so Steeve can expand them and paste again.

Changed from ux-t on purpose:
- Names and links are kept. A capture is verbatim; crp anonymise replaces names later (D21).
- Quoted text from an earlier post at the top of a reply is left out, and that post becomes the reply's
  parent (capture rules). Otherwise the paste doesn't show who replied to whom, so parents are unknown.
- The opening post is the post's own text, or the title when it has none or links to another page (the
  title and body aren't next to each other in the paste, so together they couldn't be verified). Its
  author is whoever carries the OP badge, if anyone does, and its date is the earliest comment's.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from crp import manifest
from crp.io import InputError, atomic_write_text
from crp.reddit import is_bot

AGE = re.compile(r"^(\d+)\s?(s|m|min|h|hr|d|w|mo|y|yr)s?\.? ago$")
VOTES = re.compile(r"^-?\d+(\.\d+)?[kK]?$")
MARKERS = {"OP", "MOD", "Mod", "ADMIN", "Admin"}  # badges between a name and "•"
BOT_TEXT = ("i am a bot", "i detect haikus", "this action was performed automatically")
FILLER = re.compile(r"^(Continue this thread|View more comments|\d+ more repl(y|ies)|Reply|Share|Award|Downvote|"
                    r".+ avatar)$")
MORE = re.compile(r"^(\d+) more repl(?:y|ies)$")
DELETED = {"Comment deleted by user", "[deleted]", "[removed]"}
DOMAIN = re.compile(r"[\w-]+(\.[\w-]+)+")
MIN_QUOTE_CHARS = 20  # a leading paragraph this long, found in an earlier post, is a quote of it


def age_to_date(age: str, captured: dt.date) -> str | None:
    m = AGE.match(age)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {"s": 0, "m": 0, "min": 0, "h": 0, "hr": 0, "d": n, "w": 7 * n, "mo": 30 * n, "y": 365 * n, "yr": 365 * n}
    return (captured - dt.timedelta(days=days[unit])).isoformat()


def votes(value: str) -> int | None:
    if not VOTES.match(value):
        return None
    return int(float(value[:-1]) * 1000) if value[-1] in "kK" else int(float(value))


def parse_reddit(raw: str, captured: dt.date) -> dict | None:
    """The thread in a new-Reddit paste, or None if the layout isn't recognised."""
    lines = [line.rstrip() for line in raw.replace("\r\n", "\n").split("\n")]

    def start_at(i: int) -> tuple[int, list[str]] | None:
        """(index of the age or "Ad" line, badges) if a comment starts at line i: name, badges, "•", age."""
        if not lines[i].strip() or lines[i].strip() in MARKERS:
            return None
        j, badges = i + 1, []
        while j < len(lines) and lines[j].strip() in MARKERS and len(badges) < 2:
            badges.append(lines[j].strip())
            j += 1
        if j + 1 < len(lines) and lines[j].strip() == "•" and (AGE.match(lines[j + 1].strip())
                                                               or lines[j + 1].strip() == "Ad"):
            return j + 1, badges
        return None

    found = {i: start_at(i) for i in range(len(lines))}
    starts = [i for i, info in found.items() if info]
    if len(starts) < 3:
        return None

    header = [l.strip() for l in lines[:starts[0]]]
    community = next((m.group(1) for l in header if (m := re.match(r"^(r/\w+) - ", l))), None)
    title = next((l for l in header if l), "")
    post_votes = None
    if "Upvote" in header:
        after = [l for l in header[header.index("Upvote") + 1:] if l]
        post_votes = votes(after[0]) if after else None
    elif "Open" in header:
        after = [l for l in header[header.index("Open") + 1:] if l]
        post_votes = votes(after[0]) if after else None
    body_end = next((i for i, l in enumerate(header) if l in ("Open", "Upvote")), len(header))
    body_start = next((i + 1 for i, l in enumerate(header) if community and l.startswith(community)), 1)
    if body_start < body_end and DOMAIN.fullmatch(header[body_start]):  # a link post's domain, not its text
        body_start += 1
    body = header[body_start:body_end]
    while body and (VOTES.match(body[-1]) or body[-1] in ("·", "") or body[-1].endswith(" avatar")):
        last = body.pop()
        if post_votes is None and VOTES.match(last):
            post_votes = votes(last)
    link_post = any(DOMAIN.fullmatch(l) for l in header[:body_end] if l)
    post_text = "\n".join(l for l in body if l).strip()

    comments, skipped = [], {"ads": 0, "bots": 0, "deleted": 0, "image_only": 0}
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        author = lines[i].strip()
        age_index, badges = found[i]
        if lines[age_index].strip() == "Ad":
            skipped["ads"] += 1
            continue
        age = lines[age_index].strip()
        block = lines[age_index + 1:end]
        upvote = next((j for j, l in enumerate(block) if l.strip() == "Upvote"), None)
        score = None
        if upvote is None:
            upvote = len(block)
            while upvote and (not block[upvote - 1].strip() or FILLER.match(block[upvote - 1].strip())):
                upvote -= 1
            if upvote and VOTES.match(block[upvote - 1].strip()):
                score = votes(block[upvote - 1].strip())
                upvote -= 1
        else:
            following = [l.strip() for l in block[upvote + 1:] if l.strip()]
            score = votes(following[0]) if following else None
        body_lines = []
        for l in block[:upvote]:
            s = l.strip()
            if not body_lines and (s.startswith("Edited ") or s.startswith("Profile Badge") or s == "•"):
                continue
            if s != "Comment Image":
                body_lines.append(s)
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(body_lines).strip())
        if author == "[deleted]" or text in DELETED:
            skipped["deleted"] += 1
        elif is_bot(author) or any(b in text.lower() for b in BOT_TEXT):
            skipped["bots"] += 1
        elif not text:
            skipped["image_only"] += 1
        else:
            comments.append({"author": author, "op": "OP" in badges, "date": age_to_date(age, captured),
                             "score": score, "text": text})
    stripped = [l.strip() for l in lines]
    collapsed = {"more_replies": sum(int(m.group(1)) for l in stripped if (m := MORE.match(l))),
                 "continue_threads": stripped.count("Continue this thread") + stripped.count("View more comments")}
    return {"community": community, "title": title, "link_post": link_post, "post_text": post_text,
            "post_votes": post_votes, "comments": comments, "skipped": skipped, "collapsed": collapsed}


def split_quote(text: str, earlier: list[dict]) -> tuple[str, str | None]:
    """A reply that opens with a paragraph quoted from an earlier post: (the reply without it, that post's id)."""
    paras = text.split("\n\n")
    if len(paras) < 2:
        return text, None
    first = paras[0].lstrip(">").strip()
    if len(first) < MIN_QUOTE_CHARS:
        return text, None
    for post in reversed(earlier):
        if first in post["text"]:
            return "\n\n".join(paras[1:]).strip(), post["id"]
    return text, None


def to_capture(parsed: dict, source_file: str, captured: dt.date, search_term: str | None) -> tuple[dict, int]:
    """The capture file's contents, and how many replies had a quote removed."""
    op = next((c["author"] for c in parsed["comments"] if c["op"]), None)
    dates = [c["date"] for c in parsed["comments"] if c["date"]]
    opening = parsed["title"] if parsed["link_post"] or not parsed["post_text"] else parsed["post_text"]
    posts = [{"id": "p1", "author": op, "date": min(dates) if dates else None, "date_approx": bool(dates),
              "parent": None, "score": parsed["post_votes"], "text": opening}]
    if parsed["link_post"]:
        posts[0]["headline"] = True  # the article's headline: context only, never sampled (D41)
    quoted = 0
    for c in parsed["comments"]:
        text, parent = split_quote(c["text"], posts)
        quoted += parent is not None
        posts.append({"id": f"p{len(posts) + 1}", "author": c["author"], "date": c["date"],
                      "date_approx": c["date"] is not None, "parent": parent, "score": c["score"], "text": text})
    site = f"reddit.com/{parsed['community']}" if parsed["community"] else "reddit.com"
    return {"source_file": source_file, "site": site, "url": None, "captured": captured.isoformat(),
            "thread_title": parsed["title"] or None, "search_query": search_term, "posts": posts}, quoted


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].rstrip("-") or "thread"


def paste(study_dir: Path, text: str, name: str | None = None, captured: dt.date | None = None,
          search_term: str | None = None, replace: bool = False) -> dict:
    """Save a pasted thread in raw/ and write its capture file."""
    study_dir = Path(study_dir)
    if not (study_dir / "study.yaml").exists():
        raise InputError(f"{study_dir} isn't a study folder (no study.yaml).")
    if not text.strip():
        raise InputError("The paste is empty.")
    captured = captured or dt.date.today()
    parsed = parse_reddit(text, captured)
    if parsed is None:
        raise InputError("This doesn't look like a copied Reddit thread page (fewer than three comments found). "
                         "Write its capture file by hand instead, following the skill's reference/capture.md.")
    name = slug(name or parsed["title"])
    raw_file = study_dir / "raw" / f"{name}.txt"
    cap_file = study_dir / "raw" / "capture" / f"{name}.json"
    replaced = None
    if raw_file.exists() or cap_file.exists():
        if not replace:
            raise InputError(f"raw/{name}.txt already exists. Give another --name, or --replace it with this paste "
                             "(the old paste is kept in raw/replaced/).")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        keep = study_dir / "raw" / "replaced"
        keep.mkdir(parents=True, exist_ok=True)
        for f in (raw_file, cap_file):
            if f.exists():
                f.rename(keep / f"{f.stem}-{stamp}{f.suffix}")
        replaced = f"raw/replaced/{name}-{stamp}.txt"
    capture, quoted = to_capture(parsed, raw_file.name, captured, search_term)
    with manifest.stage(study_dir, "paste") as record:
        atomic_write_text(raw_file, text if text.endswith("\n") else text + "\n")
        atomic_write_text(cap_file, json.dumps(capture, indent=1, ensure_ascii=False) + "\n")
        record["outputs"] = [f"raw/{raw_file.name}", f"raw/capture/{cap_file.name}"]
        record["settings"] = {"captured": captured.isoformat(), "replace": replace}
        record["counts"] = {"posts": len(capture["posts"]), "skipped": parsed["skipped"],
                            "collapsed": parsed["collapsed"], "quotes_removed": quoted}
    return {"name": name, "title": parsed["title"], "site": capture["site"], "posts": len(capture["posts"]),
            "names": len({p["author"] for p in capture["posts"] if p["author"]}), "link_post": parsed["link_post"],
            "skipped": parsed["skipped"], "collapsed": parsed["collapsed"], "quotes_removed": quoted,
            "replaced": replaced}
