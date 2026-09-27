"""The synthetic fixture validates, holds the facts its README states, and regenerates exactly."""
import subprocess
import sys
from collections import Counter

from conftest import FIXTURE_SECRETS, FIXTURE_STUDY, FIXTURES
from crp.io import read_csv, read_jsonl, read_yaml
from crp.schemas import COLLECTION_LOG_COLUMNS, Codebook, CollectionLogRow, Post, Study


def posts():
    return read_jsonl(FIXTURE_STUDY / "posts.jsonl", Post)


def forum():
    return [p for p in posts() if p.source_type == "forum"]


def test_every_fixture_file_validates():
    assert read_yaml(FIXTURE_STUDY / "study.yaml", Study).id == FIXTURE_STUDY.name
    assert read_yaml(FIXTURE_STUDY / "codebook.yaml", Codebook).version == "1"
    log = read_csv(FIXTURE_STUDY / "collection_log.csv", CollectionLogRow, COLLECTION_LOG_COLUMNS)
    assert len(log) == 5 and sum(r.neutral for r in log) == 2 and [r.kept for r in log].count(0) == 1
    assert len(posts()) == 78


def test_forum_threads_and_people():
    assert Counter(p.thread_id for p in forum()) == {"T01": 10, "T02": 12, "T03": 41, "T04": 7}
    assert Counter(p.capture_method for p in forum() if p.kind == "post") == \
        {"paste": 1, "export": 2, "screenshot": 1}
    assert len({p.person_code for p in forum()}) == 55


def test_pile_on_thread():
    t3 = [p for p in posts() if p.thread_id == "T03"]
    replies = [p for p in t3 if p.kind == "comment"]
    assert len(replies) == 40 and {p.parent_id for p in replies} == {"T03-p01"}
    assert {p.timestamp.date().isoformat() for p in t3} == {"2026-06-10"}


def test_prolific_poster():
    code, n = Counter(p.person_code for p in forum()).most_common(1)[0]
    assert n == 12
    assert Counter(p.thread_id for p in forum() if p.person_code == code) == {"T01": 4, "T02": 4, "T03": 2, "T04": 2}


def test_promotional_and_echo_posts():
    assert [p.post_id for p in posts() if p.promotional] == ["T01-p09"]
    assert [p.text for p in forum() if len(p.text.split()) < 8] == ["Same, it's painful."]


def test_parents_exist_within_their_thread():
    by_id = {p.post_id: p for p in posts()}
    for p in posts():
        if p.parent_id:
            assert by_id[p.parent_id].thread_id == p.thread_id


def test_interview_is_its_own_source():
    turns = [p for p in posts() if p.source_type == "interview"]
    assert len(turns) == 8 and {p.thread_id for p in turns} == {"I01"}
    assert Counter(p.role for p in turns) == {"interviewer": 4, "participant": 4}


def test_committed_fixture_matches_the_generator(tmp_path):
    subprocess.run([sys.executable, str(FIXTURES / "make_fixtures.py"), str(tmp_path)], check=True)
    committed = sorted(p for p in FIXTURE_STUDY.rglob("*") if p.is_file())
    generated = sorted(p for p in (tmp_path / FIXTURE_STUDY.name).rglob("*") if p.is_file())
    assert [p.relative_to(FIXTURE_STUDY) for p in committed] == \
        [p.relative_to(tmp_path / FIXTURE_STUDY.name) for p in generated]
    for f in committed:
        if f.suffix == ".png":  # image bytes can vary with the platform's font rendering
            continue
        assert (tmp_path / FIXTURE_STUDY.name / f.relative_to(FIXTURE_STUDY)).read_bytes() == f.read_bytes(), f.name
    assert (tmp_path / "fixture-secrets" / "salt").read_bytes() == (FIXTURE_SECRETS / "salt").read_bytes()
