"""The synthetic fixture validates, and holds the facts its README states."""
import subprocess
import sys
from collections import Counter

from conftest import FIXTURE_STUDY, FIXTURES
from crp.io import read_csv, read_jsonl, read_yaml
from crp.schemas import COLLECTION_LOG_COLUMNS, Codebook, CollectionLogRow, Post, Study


def posts():
    return read_jsonl(FIXTURE_STUDY / "posts.jsonl", Post)


def test_every_fixture_file_validates():
    assert read_yaml(FIXTURE_STUDY / "study.yaml", Study).id == FIXTURE_STUDY.name
    assert read_yaml(FIXTURE_STUDY / "codebook.yaml", Codebook).version == "1"
    log = read_csv(FIXTURE_STUDY / "collection_log.csv", CollectionLogRow, COLLECTION_LOG_COLUMNS)
    assert len(log) == 5 and sum(r.neutral for r in log) == 2 and [r.kept for r in log].count(0) == 1
    assert len(posts()) == 78


def test_forum_threads_and_people():
    forum = [p for p in posts() if p.source_type == "forum"]
    assert Counter(p.thread_id for p in forum) == {"T1": 10, "T2": 12, "T3": 41, "T4": 7}
    assert len({p.person_code for p in forum}) == 55


def test_pile_on_thread():
    t3 = [p for p in posts() if p.thread_id == "T3"]
    replies = [p for p in t3 if p.kind == "comment"]
    assert len(replies) == 40 and {p.parent_id for p in replies} == {"T3-p01"}
    assert {p.timestamp.date().isoformat() for p in t3} == {"2026-06-10"}


def test_prolific_poster():
    forum = [p for p in posts() if p.source_type == "forum"]
    code, n = Counter(p.person_code for p in forum).most_common(1)[0]
    assert n == 12
    assert Counter(p.thread_id for p in forum if p.person_code == code) == {"T1": 4, "T2": 4, "T3": 2, "T4": 2}


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
    for f in sorted(FIXTURE_STUDY.iterdir()):
        assert (tmp_path / FIXTURE_STUDY.name / f.name).read_bytes() == f.read_bytes(), f.name
