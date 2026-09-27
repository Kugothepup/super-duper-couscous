"""Ported code against the skill's own scripts on the same inputs (D7).

Wherever DECISIONS.md hasn't changed the method, crp must give the same result as the scripts
in tests/reference/. Known, recorded differences: thread numbering across source types, and
names kept until crp anonymise.
"""
import json
import shutil

import pytest

from conftest import FIXTURE_SECRETS, read_jsonl, run_reference
from crp.anonymise import anonymise
from crp.ingest import ingest
from crp.signals import signals
from crp.verify import verify


@pytest.fixture
def ours(study, no_ocr):
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    posts = read_jsonl(study / "posts.jsonl")
    sig = {r["post_id"]: r for r in read_jsonl(study / "signals.jsonl")}
    return study, posts, sig


def reference_threads(work):
    manifest = json.loads((work / "manifest.json").read_text())
    return [json.loads((work / "turns" / f"{m['transcript_id']}.json").read_text()) for m in manifest]


def same_partition(ref_ids, our_ids):
    """Two labellings name the same people if they map one-to-one."""
    pairs = set(zip(ref_ids, our_ids))
    return len(pairs) == len(set(ref_ids)) == len(set(our_ids))


def compare_thread(ref_doc, our_rows):
    ref = ref_doc["turns"]
    assert [t["text"] for t in ref] == [r["text"] for r in our_rows]
    assert [t.get("kind", "turn") for t in ref] == [r["kind"] for r in our_rows]
    assert [t["role"] for t in ref] == [r["role"] for r in our_rows]
    idx = {r["post_id"]: i + 1 for i, r in enumerate(our_rows)}
    assert [t.get("parent_turn") for t in ref] == [idx.get(r["parent_id"]) for r in our_rows]
    assert [t.get("score") or 0 for t in ref] == [r["score"] or 0 for r in our_rows]


def test_reddit_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", study / "raw" / "reddit", "--work", work)
    ref = reference_threads(work)
    for ref_doc, tid in zip(ref, ("T02", "T03")):
        rows = [p for p in posts if p["thread_id"] == tid]
        compare_thread(ref_doc, rows)
        assert [t["created"] for t in ref_doc["turns"]] == \
            [r["timestamp"].replace("T", " ")[:16] for r in rows]
    ref_people = [t["author_id"] for d in ref for t in d["turns"]]
    our_people = [p["person_code"] for p in posts if p["thread_id"] in ("T02", "T03")]
    assert same_partition(ref_people, our_people)


def test_forum_capture_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    shutil.copytree(study / "raw" / "capture", work / "capture")
    run_reference("parse_forum.py", "--work", work, "--sources", study / "raw")
    ref = {d["source_file"]: d for d in reference_threads(work)}
    for source, tid in (("pro_price.txt", "T01"), ("love.png", "T04")):
        rows = [p for p in posts if p["thread_id"] == tid]
        compare_thread(ref[source], rows)
        assert [t["promotional"] for t in ref[source]["turns"]] == [r["promotional"] for r in rows]
        assert [t["date_approx"] for t in ref[source]["turns"]] == [r["date_approx"] for r in rows]


def test_interview_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    run_reference("parse_transcripts.py", study / "raw" / "interviews", "--work", work)
    [ref_doc] = reference_threads(work)
    compare_thread(ref_doc, [p for p in posts if p["thread_id"] == "I01"])


def signal_rows(work):
    out = []
    for m in json.loads((work / "manifest.json").read_text()):
        out += json.loads((work / "signals" / f"{m['transcript_id']}.json").read_text())["turns"]
    return out


KEYS = ("words", "counts", "density", "response_gap_s", "flags")


def test_forum_signals_match(ours, tmp_path):
    study, posts, sig = ours
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", study / "raw" / "reddit", "--work", work)
    run_reference("signals.py", "--work", work)
    ref = signal_rows(work)
    mine = [sig[p["post_id"]] for p in posts if p["thread_id"] in ("T02", "T03") and p["role"] == "participant"]
    assert len(ref) == len(mine)
    for r, m in zip(ref, mine):
        assert {k: r[k] for k in KEYS + ("score", "n_replies", "echo_agree", "echo_disagree")} == \
            {k: m[k] for k in KEYS + ("score", "n_replies", "echo_agree", "echo_disagree")}
    assert any("high_engagement" in m["flags"] for m in mine)


def test_interview_signals_match_with_response_gaps(tmp_path, no_ocr):
    interviews = tmp_path / "study" / "raw" / "interviews"
    interviews.mkdir(parents=True)
    cues = [("Moderator", "How do you find old notes?", 1.0, 4.0),
            ("Kim", "Um, I, I mostly search, I guess, but, uh, it kind of depends, you know, on the project.", 7.5, 14.0),
            ("Moderator", "What happens when search fails?", 15.0, 17.0),
            ("Kim", "I had to scroll through backlinks, and I wish there was a way to filter by date.", 17.4, 23.0),
            ("Moderator", "Anything else?", 24.0, 25.0),
            ("Kim", "I switched to paper for my thesis references, honestly.", 28.0, 31.0)]
    body = "WEBVTT\n\n" + "".join(
        f"00:00:{s:06.3f} --> 00:00:{e:06.3f}\n<v {who}>{text}\n\n" for who, text, s, e in cues)
    (interviews / "call.vtt").write_text(body, encoding="utf-8")
    work = tmp_path / "ref"
    run_reference("parse_transcripts.py", interviews, "--work", work)
    run_reference("signals.py", "--work", work)
    study = tmp_path / "study"
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    ref, mine = signal_rows(work), read_jsonl(study / "signals.jsonl")
    assert [{k: r[k] for k in KEYS} for r in ref] == [{k: m[k] for k in KEYS} for m in mine]
    assert any("long_response_gap" in m["flags"] for m in mine)
