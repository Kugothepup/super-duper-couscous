"""crp ingest: parse everything in raw/ into raw/ingested.jsonl, names still attached.

raw/ layout:
  raw/capture/*.json   the AI's transcriptions of pastes and screenshots (originals anywhere under raw/)
  raw/reddit/          Reddit exports (.json, .jsonl, .ndjson, .csv)
  raw/interviews/      interview transcripts (.txt, .md, .docx, .vtt, .srt)

Forum threads (captures and exports) are numbered T01, T02 ... in order of their first post;
interviews I01, I02 ... in file-name order. Posts are numbered in reply-tree order.
The output keeps real names, so it stays in raw/. crp anonymise turns it into posts.jsonl.

Numbers are kept (D35): raw/ids.json remembers each thread's number by its source (capture file, Reddit
thread or transcript file) and each post's by its thread, author and text. A re-ingest, or a later round
that adds threads or a fuller paste of a thread, keeps every earlier number; new threads and posts are
numbered after the ones already used. So the first ingest numbers as above, and later ones only add.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from crp import manifest
from crp.captures import Thread, read_captures
from crp.io import InputError, atomic_write_text, validate, write_jsonl
from crp.reddit import read_exports
from crp.transcripts import read_interviews
from crp.schemas import IngestedPost

INGESTED = Path("raw") / "ingested.jsonl"
REPORT = Path("results") / "ingest_report.json"  # counts only: no names, no text
DETAILS = Path("raw") / "ingest_details.json"  # speaker names and role assignments: private
IDS = Path("raw") / "ids.json"  # the thread and post numbers already given; holds names, so private


def _first_time(th: Thread) -> str:
    times = [t["timestamp"].isoformat() for t in th.turns if t["timestamp"]]
    return min(times) if times else ""


def _next(used: set[int]) -> int:
    return max(used, default=0) + 1


def thread_number(ids: dict, source_type: str, th: Thread, prefix: str) -> str:
    key = f"{source_type}|{th.key}"
    if key not in ids["threads"]:
        used = {int(v[len(prefix):]) for v in ids["threads"].values() if v.startswith(prefix)}
        ids["threads"][key] = f"{prefix}{_next(used):02d}"
    return ids["threads"][key]


def post_numbers(ids: dict, tid: str, th: Thread) -> dict[int, int]:
    """{position in the thread: post number}, keeping the numbers earlier ingests gave."""
    known = ids["posts"].setdefault(tid, {})
    seen: Counter = Counter()
    out = {}
    for t in th.turns:
        base = f"{t['author'] or ''}\0{hashlib.sha256(t['text'].encode('utf-8')).hexdigest()}"
        seen[base] += 1
        key = f"{base}\0{seen[base]}"
        if key not in known:
            known[key] = _next(set(known.values()))
        out[t["turn"]] = known[key]
    return out


def to_rows(threads: list[Thread], prefix: str, source_type: str, ids: dict) -> list[IngestedPost]:
    rows = []
    letter = "t" if source_type == "interview" else "p"
    for th in threads:
        tid = thread_number(ids, source_type, th, prefix)
        num = post_numbers(ids, tid, th)
        for t in th.turns:
            data = {"post_id": f"{tid}-{letter}{num[t['turn']]:02d}", "source_type": source_type, "source": th.source,
                    "thread_id": tid, "thread_title": th.title, "search_term": th.search_term,
                    "parent_id": f"{tid}-{letter}{num[t['parent_turn']]:02d}" if t["parent_turn"] else None,
                    "author": t["author"], "role": t["role"], "kind": t["kind"], "timestamp": t["timestamp"],
                    "date_approx": t["date_approx"], "score": t["score"], "start_s": t.get("start_s"),
                    "end_s": t.get("end_s"), "promotional": t["promotional"], "text": t["text"],
                    "capture_method": th.capture_method, "raw_ref": t["ref"]}
            rows.append(validate(IngestedPost, data, f"{t['ref']}"))
    return rows


def ingest(study_dir: Path, interviewer: str | None = None, keep_bots: bool = False) -> dict:
    study_dir = Path(study_dir)
    raw = study_dir / "raw"
    inputs = sorted(p for sub in ("capture", "reddit", "interviews") for p in (raw / sub).rglob("*") if p.is_file()) \
        if raw.is_dir() else []
    if not inputs:
        raise InputError(f"Nothing to ingest in {raw}/. Put capture files in raw/capture/, Reddit exports in "
                         "raw/reddit/ and interview transcripts in raw/interviews/.")
    with manifest.stage(study_dir, "ingest", inputs=inputs) as record:
        captured, cap_report = read_captures(raw) if (raw / "capture").is_dir() else ([], {})
        exported, red_report = read_exports(raw / "reddit", keep_bots=keep_bots)
        interviews, int_report = read_interviews(raw / "interviews", interviewer)
        origin = {id(th): i for i, th in enumerate(captured + exported)}
        forum = sorted(captured + exported, key=lambda th: (_first_time(th), origin[id(th)]))
        ids_path = study_dir / IDS
        ids = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else {"threads": {}, "posts": {}}
        rows = to_rows(forum, "T", "forum", ids) + to_rows(interviews, "I", "interview", ids)
        rows.sort(key=lambda r: (r.source_type != "forum", r.thread_id))  # stable: posts keep tree order
        write_jsonl(study_dir / INGESTED, rows)
        atomic_write_text(ids_path, json.dumps(ids, indent=1, ensure_ascii=False, sort_keys=True) + "\n")

        firsts = {}
        for r in rows:
            firsts.setdefault(r.thread_id, r)
        threads = [{"thread_id": r.thread_id, "source": r.source, "capture_method": r.capture_method,
                    "source_file": r.raw_ref.split("#")[0]} for r in firsts.values()]
        for t in threads:
            t["posts"] = sum(r.thread_id == t["thread_id"] for r in rows)
        report = {"threads": threads, "forum_posts": sum(r.source_type == "forum" for r in rows),
                  "interview_turns": sum(r.source_type == "interview" for r in rows),
                  "captures": cap_report, "reddit": red_report,
                  "interviews": [{k: v for k, v in d.items() if k != "speakers"} | {"speakers": len(d["speakers"])}
                                 for d in int_report.get("interviews", [])]}
        atomic_write_text(study_dir / REPORT, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        atomic_write_text(study_dir / DETAILS, json.dumps(int_report, indent=2, ensure_ascii=False) + "\n")
        record["outputs"] = [str(INGESTED), str(REPORT), str(DETAILS), str(IDS)]
    report["interview_speakers"] = int_report.get("interviews", [])
    return report
