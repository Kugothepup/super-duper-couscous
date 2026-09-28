"""crp view: read the study compactly, for the AI's synthesis. Prints only; writes nothing.

Ported from view_transcript.py, kwic.py and list_nuggets.py (python -m crp view <what> <study> ...):
  thread <study> T01 [--range 1-80]   a whole thread or interview, with signal flags
  detail <study> [--batch N]          the detail selection, in batches of 40 (what to write observations on)
  posts <study> ID ...                particular posts, e.g. a theme's representatives
  kwic <study> TERM                   every use of a term in context
  observations <study> [filters]      the observations with their blind codes, one line each
Forum lines:     [p12] P-1a2b3c4d OP ^34 re[p09] (+3 agree/-1)  {flags}  text
Interview lines: [t12] P  03:12  {flags}  text
When a comment's parent isn't shown, a context line gives the start of the parent.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from crp.anonymise import POSTS
from crp.batch import read_index
from crp.io import InputError, read_jsonl
from crp.labels import labelled
from crp.sample import load_detail
from crp.schemas import Post
from crp.signals import SIGNALS
from crp.synthesis import load

BATCH = 40


def read_signals(study_dir: Path) -> dict[str, dict]:
    path = study_dir / SIGNALS
    if not path.exists():
        return {}
    return {r["post_id"]: r for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)}


def short(post_id: str) -> str:
    return post_id.split("-", 1)[1] if "-" in post_id else post_id


def clock(s: float | None) -> str:
    if s is None:
        return "     "
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def show(posts: list[Post], thread: list[Post], sig: dict[str, dict], keep: set[str] | None = None) -> list[str]:
    """view_transcript.py's show(): the thread's posts (or just `keep`), with parent context where needed."""
    by_id = {p.post_id: p for p in thread}
    first = thread[0]
    forum = first.source_type == "forum"
    op = next((p.person_code for p in thread if p.kind == "post"), None)
    lines = [f"# {first.thread_id}  {first.source}" + (f'  "{first.thread_title}"' if first.thread_title else "")]
    shown, context = set(), set()
    for p in thread:
        if keep is not None and p.post_id not in keep:
            continue
        s = sig.get(p.post_id, {})
        flags = "{" + ",".join(s["flags"]) + "}  " if s.get("flags") else ""
        if forum:
            parent = p.parent_id
            if parent and parent not in shown and parent not in context and parent in by_id and p.kind != "post":
                context.add(parent)
                t = by_id[parent].text
                lines.append(f"    (replying to [{short(parent)}] {by_id[parent].person_code}: \"{t[:110]}"
                             f"{'...' if len(t) > 110 else ''}\")")
            echo = f" (+{s.get('echo_agree', 0)} agree/-{s.get('echo_disagree', 0)})" \
                if s.get("echo_agree") or s.get("echo_disagree") else ""
            lines.append(f"[{short(p.post_id)}]{' POST' if p.kind == 'post' else ''} {p.person_code}"
                         f"{' OP' if p.person_code == op and p.kind != 'post' else ''} ^{p.score or 0}"
                         f"{f' re[{short(parent)}]' if parent else ''}{echo}  {flags}{p.text}")
        else:
            role = {"interviewer": "I", "participant": "P"}.get(p.role, "?")
            lines.append(f"[{short(p.post_id)}] {role}  {clock(p.start_s)}  {flags}{p.text}")
        shown.add(p.post_id)
    return lines


def threads_of(posts: list[Post]) -> dict[str, list[Post]]:
    out: dict[str, list[Post]] = {}
    for p in posts:
        out.setdefault(p.thread_id, []).append(p)
    return out


def view_thread(study_dir: Path, thread_id: str, lo: int = 1, hi: int = 10 ** 9) -> list[str]:
    posts = read_jsonl(Path(study_dir) / POSTS, Post)
    thread = threads_of(posts).get(thread_id)
    if not thread:
        raise InputError(f"No thread {thread_id}.")
    keep = {p.post_id for i, p in enumerate(thread, 1) if lo <= i <= hi}
    return show(posts, thread, read_signals(Path(study_dir)), keep)


def view_posts(study_dir: Path, ids: list[str]) -> list[str]:
    posts = read_jsonl(Path(study_dir) / POSTS, Post)
    known = {p.post_id for p in posts}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise InputError(f"No such post(s): {', '.join(unknown)}")
    sig, lines = read_signals(Path(study_dir)), []
    for tid, thread in threads_of(posts).items():
        keep = {p.post_id for p in thread} & set(ids)
        if keep:
            lines += show(posts, thread, sig, keep) + [""]
    return lines


def view_detail(study_dir: Path, batch: int | None = None) -> list[str]:
    study_dir = Path(study_dir)
    items = load_detail(study_dir)
    posts = read_jsonl(study_dir / POSTS, Post)
    order = [post.post_id for _, post in items]
    batches = [order[i:i + BATCH] for i in range(0, len(order), BATCH)]
    if batch is None:
        return [f"The detail selection has {len(order)} posts in {len(batches)} batch(es) of up to {BATCH}. "
                "Read one with --batch N."]
    if not 1 <= batch <= len(batches):
        raise InputError(f"The batch must be 1 to {len(batches)}.")
    keep = set(batches[batch - 1])
    lines = [f"## Detail batch {batch}/{len(batches)} ({len(keep)} posts)"]
    sig = read_signals(study_dir)
    for tid, thread in threads_of(posts).items():
        if keep & {p.post_id for p in thread}:
            lines += show(posts, thread, sig, keep) + [""]
    return lines


def kwic(study_dir: Path, term: str, regex: bool = False, all_speakers: bool = False, width: int = 60) -> list[str]:
    rx = re.compile(term if regex else r"\b" + re.escape(term) + r"\w*", re.I)
    lines, per = [], Counter()
    for p in read_jsonl(Path(study_dir) / POSTS, Post):
        if p.role != "participant" and not all_speakers:
            continue
        for hit in rx.finditer(p.text):
            left = p.text[max(0, hit.start() - width):hit.start()]
            right = p.text[hit.end():hit.end() + width]
            lines.append(f"{p.post_id:<10}{'P' if p.role == 'participant' else 'I'} {left:>{width}} [{hit.group(0)}] {right}")
            per[p.thread_id] += 1
    lines.append(f"\n{sum(per.values())} hit(s) in {len(per)} thread(s): {dict(per)}")
    return lines


def view_observations(study_dir: Path, force: str | None = None, tag: str | None = None, evidence: str | None = None,
                      friction: bool = False, min_severity: int = 0, quotes: bool = False) -> list[str]:
    study_dir = Path(study_dir)
    coded = {pid: v for (s, pid), v in labelled(study_dir, read_index(study_dir)).items() if s == "detail"}
    rows = [(o, coded.get(o.post_id, {})) for o in load(study_dir)["observations"]]
    if force:
        rows = [(o, c) for o, c in rows if c.get("jtbd_force") == force]
    if tag:
        rows = [(o, c) for o, c in rows if tag in o.tags]
    if evidence:
        rows = [(o, c) for o, c in rows if c.get("evidence_type") in set(evidence.split(","))]
    if friction or min_severity:
        rows = [(o, c) for o, c in rows if c.get("friction") is True and (c.get("severity") or 0) >= min_severity]
    lines = []
    for o, c in rows:
        sev = f" S{c['severity']}" if c.get("friction") is True else ""
        lines.append(f"{o.post_id:<10} {str(c.get('jtbd_force', '-')):<7} {str(c.get('evidence_type', '-'))[:10]:<10}"
                     f"{sev:<4} [{','.join(o.tags)}] {o.observation}")
        if quotes:
            lines.append(f"           \"{o.quote}\"")
    tags = Counter(t for o, _ in rows for t in o.tags)
    lines.append(f"\n{len(rows)} observation(s) from {len({o.post_id.split('-')[0] for o, _ in rows})} thread(s). "
                 f"Top tags: {', '.join(f'{t}({n})' for t, n in tags.most_common(15))}")
    return lines
