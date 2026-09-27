import json
from pathlib import Path

import pytest

from conftest import read_jsonl
from crp.ingest import ingest
from crp.io import InputError, read_jsonl as read_rows
from crp.schemas import IngestedPost


def test_fixture_ingest_report(study):
    rep = ingest(study)
    assert [(t["thread_id"], t["capture_method"], t["posts"]) for t in rep["threads"]] == [
        ("T01", "paste", 10), ("T02", "export", 12), ("T03", "export", 41), ("T04", "screenshot", 7),
        ("I01", "transcript", 8)]
    assert rep["reddit"]["bots_removed"] == 1 and rep["reddit"]["collapsed_missing"] == 3
    assert rep["captures"]["promotional_flagged"] == 1
    [iv] = rep["interview_speakers"]
    assert iv["speakers"] == {"Ana": "interviewer", "Dev": "participant"}
    assert iv["role_method"] == "question-ratio heuristic (check!)"


def test_names_stay_in_raw(study):
    ingest(study)
    rows = read_rows(study / "raw" / "ingested.jsonl", IngestedPost)
    names = {r.author for r in rows if r.author}
    assert {"maria_k", "night_owl_notes", "Ana", "Dev"} <= names
    public = (study / "results" / "ingest_report.json").read_text()
    assert not [n for n in names if n in public]
    assert "Ana" in (study / "raw" / "ingest_details.json").read_text()


def test_threads_are_numbered_by_first_post_and_posts_by_reply_tree(study):
    ingest(study)
    rows = read_jsonl(study / "raw" / "ingested.jsonl")
    t2 = [r for r in rows if r["thread_id"] == "T02"]
    assert t2[0]["kind"] == "post" and t2[0]["text"].startswith("Search is slow once you pass 2,000 notes. Anyone")
    # siblings by score, each reply right after its parent
    assert [r["score"] for r in t2 if r["parent_id"] == "T02-p01"] == sorted(
        (r["score"] for r in t2 if r["parent_id"] == "T02-p01"), reverse=True)
    for i, r in enumerate(t2):
        if r["parent_id"] and r["parent_id"] != "T02-p01":
            assert any(p["post_id"] == r["parent_id"] for p in t2[:i])


def test_screenshot_dates_are_approximate_and_noon(study):
    ingest(study)
    t4 = [r for r in read_jsonl(study / "raw" / "ingested.jsonl") if r["thread_id"] == "T04"]
    assert {(r["timestamp"], r["date_approx"]) for r in t4} == {("2026-07-20T12:00:00", True)}


def test_nothing_to_ingest(tmp_path):
    (tmp_path / "raw").mkdir()
    with pytest.raises(InputError, match="Nothing to ingest"):
        ingest(tmp_path)


def write_capture(raw: Path, name: str, posts: list[dict], source="page.txt", page=None) -> None:
    (raw / "capture").mkdir(parents=True, exist_ok=True)
    (raw / source).write_text(page if page is not None else "\n".join(p["text"] for p in posts), encoding="utf-8")
    (raw / "capture" / name).write_text(json.dumps(
        {"source_file": source, "site": "forum.example", "captured": "2026-09-20", "thread_title": "t",
         "posts": posts}), encoding="utf-8")


def test_capture_problems_are_all_listed(tmp_path):
    raw = tmp_path / "raw"
    write_capture(raw, "a.json", [{"id": "p1", "author": "x", "text": "hello there", "parent": "p9",
                                   "date": "3 months ago"}])
    (raw / "capture" / "b.json").write_text(json.dumps({"source_file": "missing.txt", "posts": []}))
    with pytest.raises(InputError) as err:
        ingest(tmp_path)
    msg = str(err.value)
    assert "a.json/p1: parent 'p9' not in this capture" in msg
    assert "a.json/p1: date must be YYYY-MM-DD" in msg
    assert "b.json: source_file 'missing.txt' not found in raw/" in msg
    assert "nothing was written" in msg and not (raw / "ingested.jsonl").exists()


def test_duplicate_posts_across_captures_are_dropped(tmp_path):
    raw = tmp_path / "raw"
    long = ("The export drops every relation between my notes, so the archive I spent three years building "
            "is useless anywhere else and I cannot leave without losing all of that work")
    write_capture(raw, "a.json", [{"id": "p1", "author": "x", "text": long}], source="a.txt")
    write_capture(raw, "b.json", [{"id": "p1", "author": "y", "text": "Opening post of thread b here."},
                                  {"id": "p2", "author": "x", "text": long, "parent": "p1"},
                                  {"id": "p3", "author": "z", "text": long.replace("that work", "that effort"),
                                   "parent": "p1"}], source="b.txt")
    rep = ingest(tmp_path)
    assert rep["captures"]["duplicates_dropped"] == {"exact": 1, "near": 1}
    assert rep["forum_posts"] == 2


def test_reddit_csv_accepts_iso_dates(tmp_path):
    (tmp_path / "raw" / "reddit").mkdir(parents=True)
    (tmp_path / "raw" / "reddit" / "x.csv").write_text(
        "id,parent_id,link_id,author,body,title,score,created_utc\n"
        "s1,,s1,op,Body text,A title,5,2026-05-01T10:30:00\n"
        "c1,t3_s1,t3_s1,[deleted],[removed],,1,2026-05-01T11:00:00\n", encoding="utf-8")
    ingest(tmp_path)
    rows = read_jsonl(tmp_path / "raw" / "ingested.jsonl")
    assert rows[0]["timestamp"] == "2026-05-01T10:30:00" and rows[0]["text"] == "A title. Body text"
    assert rows[1]["role"] == "unknown" and rows[1]["text"] == "[deleted]" and rows[1]["author"] is None


def test_vtt_interview_keeps_cue_times(tmp_path):
    (tmp_path / "raw" / "interviews").mkdir(parents=True)
    (tmp_path / "raw" / "interviews" / "call.vtt").write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v Moderator>How do you find old notes?\n\n"
        "00:00:07.500 --> 00:00:12.000\n<v Kim>Um, I, I mostly search, I guess.\n", encoding="utf-8")
    rep = ingest(tmp_path)
    rows = read_jsonl(tmp_path / "raw" / "ingested.jsonl")
    assert [(r["role"], r["start_s"], r["end_s"]) for r in rows] == [
        ("interviewer", 1.0, 4.0), ("participant", 7.5, 12.0)]
    assert rep["interview_speakers"][0]["role_method"] == "speaker labels"


def test_docx_interview(tmp_path):
    import docx
    (tmp_path / "raw" / "interviews").mkdir(parents=True)
    doc = docx.Document()
    for line in ("Interviewer: What do you use it for?", "P1: Mostly lecture notes.", "P1: And recipes."):
        doc.add_paragraph(line)
    doc.save(tmp_path / "raw" / "interviews" / "p1.docx")
    ingest(tmp_path)
    rows = read_jsonl(tmp_path / "raw" / "ingested.jsonl")
    assert [(r["role"], r["text"]) for r in rows] == [
        ("interviewer", "What do you use it for?"), ("participant", "Mostly lecture notes. And recipes.")]
