"""crp ingest: parse everything in raw/ into raw/ingested.jsonl, names still attached.

raw/ layout:
  raw/capture/*.json   the AI's transcriptions of pastes and screenshots (originals anywhere under raw/)
  raw/reddit/          Reddit exports (.json, .jsonl, .ndjson, .csv)
  raw/interviews/      interview transcripts (.txt, .md, .docx, .vtt, .srt)

Forum threads (captures and exports) are numbered T01, T02 ... in order of their first post;
interviews I01, I02 ... in file-name order. Posts are numbered in reply-tree order.
The output keeps real names, so it stays in raw/. crp anonymise turns it into posts.jsonl.
"""
from __future__ import annotations

import json
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


def _first_time(th: Thread) -> str:
    times = [t["timestamp"].isoformat() for t in th.turns if t["timestamp"]]
    return min(times) if times else ""


def to_rows(threads: list[Thread], prefix: str, source_type: str) -> list[IngestedPost]:
    rows = []
    letter = "t" if source_type == "interview" else "p"
    for n, th in enumerate(threads, 1):
        tid = f"{prefix}{n:02d}"
        for t in th.turns:
            data = {"post_id": f"{tid}-{letter}{t['turn']:02d}", "source_type": source_type, "source": th.source,
                    "thread_id": tid, "thread_title": th.title, "search_term": th.search_term,
                    "parent_id": f"{tid}-{letter}{t['parent_turn']:02d}" if t["parent_turn"] else None,
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
        rows = to_rows(forum, "T", "forum") + to_rows(interviews, "I", "interview")
        write_jsonl(study_dir / INGESTED, rows)

        threads = [{"thread_id": r.thread_id, "source": r.source, "capture_method": r.capture_method,
                    "source_file": r.raw_ref.split("#")[0]} for r in rows if r.post_id.endswith(("p01", "t01"))]
        for t in threads:
            t["posts"] = sum(r.thread_id == t["thread_id"] for r in rows)
        report = {"threads": threads, "forum_posts": sum(r.source_type == "forum" for r in rows),
                  "interview_turns": sum(r.source_type == "interview" for r in rows),
                  "captures": cap_report, "reddit": red_report,
                  "interviews": [{k: v for k, v in d.items() if k != "speakers"} | {"speakers": len(d["speakers"])}
                                 for d in int_report.get("interviews", [])]}
        atomic_write_text(study_dir / REPORT, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        atomic_write_text(study_dir / DETAILS, json.dumps(int_report, indent=2, ensure_ascii=False) + "\n")
        record["outputs"] = [str(INGESTED), str(REPORT), str(DETAILS)]
    report["interview_speakers"] = int_report.get("interviews", [])
    return report
