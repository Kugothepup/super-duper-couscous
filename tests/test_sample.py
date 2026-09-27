"""crp sample: seeded draws, the person and thread caps, the frame rules, and keeping detail posts out of stats."""
import json
from collections import Counter

import pytest

from conftest import FIXTURE_SECRETS, read_jsonl
from crp import manifest
from crp.anonymise import anonymise
from crp.ingest import ingest
from crp.io import InputError
from crp.sample import load_detail, load_measurement, sample, thread_cap_size
from crp.signals import signals
from crp.verify import verify

PROLIFIC = "P-00000abc"


def post(tid: str, n: int, person: str, text: str, parent: str | None = None) -> dict:
    return {"post_id": f"{tid}-p{n:02d}", "source_type": "forum", "source": "reddit.com/r/test", "thread_id": tid,
            "parent_id": parent, "person_code": person, "kind": "comment" if parent else "post",
            "text": text, "capture_method": "export", "raw_ref": f"{tid}.json#p{n:02d}"}


def synthetic(d, small_threads: int = 11, pile_on: int = 40, prolific_posts: int = 0) -> list[dict]:
    """small_threads threads of 6 posts, one thread with an opening post and `pile_on` replies, all by
    different people, plus a prolific poster who opens two threads and comments across the rest."""
    rows, k = [], 0

    def person() -> str:
        nonlocal k
        k += 1
        return f"P-{k:08x}"

    threads = {f"T{t + 1:02d}": 6 for t in range(small_threads)} | {f"T{small_threads + 1:02d}": pile_on + 1}
    for tid, size in threads.items():
        for n in range(1, size + 1):
            rows.append(post(tid, n, person(), f"Person {k} writes about sync and search delays in thread {tid} "
                                               f"reply {n} at some length.", None if n == 1 else f"{tid}-p01"))
    tids = list(threads)
    for i in range(prolific_posts):
        tid = tids[i % len(tids)]
        n = sum(r["thread_id"] == tid for r in rows) + 1
        opening = i < 2
        if opening:  # the prolific poster also opens two new threads
            tid, n = f"T{len(tids) + i + 1:02d}", 1
        rows.append(post(tid, n, PROLIFIC, f"Prolific poster, item {i}, explains the export workaround step by step.",
                         None if opening else f"{tid}-p01"))
    d.mkdir(parents=True, exist_ok=True)
    (d / "posts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    signals(d)
    return rows


@pytest.fixture
def fixture_study(study, no_ocr):
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    return study


def files(d) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((d / "samples").iterdir())}


# ---- reproducible ------------------------------------------------------------

def test_same_seed_gives_identical_samples(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    synthetic(a, prolific_posts=12)
    synthetic(b, prolific_posts=12)
    sample(a, seed=5, budget=40)
    sample(b, seed=5, budget=40)
    assert files(a) == files(b)
    sample(a, seed=5, budget=40)  # re-running changes nothing
    assert files(a) == files(b)


def test_different_seed_gives_different_sample(tmp_path):
    synthetic(tmp_path)
    sample(tmp_path, seed=1)
    first = read_jsonl(tmp_path / "samples" / "measurement.jsonl")
    sample(tmp_path, seed=2)
    assert read_jsonl(tmp_path / "samples" / "measurement.jsonl") != first


def test_seed_is_generated_logged_and_reused(tmp_path):
    synthetic(tmp_path)
    s = sample(tmp_path)
    assert s["seed_source"] == "generated"
    rec = manifest.read(tmp_path)[-1]
    assert rec["command"] == "sample" and rec["seed"] == s["seed"] and rec["seed_source"] == "generated"
    before = files(tmp_path)
    again = sample(tmp_path)
    assert again["seed"] == s["seed"] and again["seed_source"] == "reused"
    assert files(tmp_path)["measurement.jsonl"] == before["measurement.jsonl"]


def test_manifest_records_frame_hash_caps_and_inputs(tmp_path):
    synthetic(tmp_path)
    s = sample(tmp_path, seed=3)
    rec = manifest.read(tmp_path)[-1]
    assert rec["status"] == "ok" and rec["seed"] == 3
    assert set(rec["inputs"]) == {"posts.jsonl", "signals.jsonl"}
    assert rec["frame_sha256"] == s["measurement"]["frame"]["frame_sha256"]
    assert rec["settings"] == {"size": 150, "person_cap": 5, "thread_cap_pct": 10,
                                    "thread_cap_posts": s["measurement"]["thread_cap"], "budget": 200,
                                    "detail_per_person": 5, "min_words": 8}


# ---- caps --------------------------------------------------------------------

def test_prolific_poster_is_capped_at_five_opening_posts_included(tmp_path):
    rows = synthetic(tmp_path, prolific_posts=12)
    assert sum(r["person_code"] == PROLIFIC and r["kind"] == "post" for r in rows) == 2
    kept = set()
    for seed in range(8):
        s = sample(tmp_path, seed=seed)
        fr = s["measurement"]["frame"]
        assert (fr["people_capped"], fr["posts_capped"]) == (1, 7)
        drawn = read_jsonl(tmp_path / "samples" / "measurement.jsonl")
        mine = [r["post_id"] for r in drawn if r["person_code"] == PROLIFIC]
        assert len(mine) <= 5
        assert max(Counter(r["person_code"] for r in drawn).values()) <= 5
        kept.update(mine)
    assert len(kept) > 5  # which five is random, not always the first five


def test_pile_on_thread_stays_within_ten_percent(tmp_path):
    synthetic(tmp_path, small_threads=11, pile_on=40, prolific_posts=12)
    for seed in range(5):
        s = sample(tmp_path, seed=seed)
        m = s["measurement"]
        drawn = read_jsonl(tmp_path / "samples" / "measurement.jsonl")
        assert len(drawn) == m["drawn"] > 0
        per_thread = Counter(r["thread_id"] for r in drawn)
        assert 10 * m["threads"]["T12"]["eligible"] > len(drawn)  # the pile-on alone would pass 10% ...
        assert all(10 * k <= len(drawn) for k in per_thread.values())  # ... but every thread is within 10%
        sizes = [t["after_person_cap"] for t in m["threads"].values()]
        for bigger in range(m["drawn"] + 1, min(150, sum(sizes)) + 1):  # no larger sample would fit
            assert sum(min(s, bigger // 10) for s in sizes) < bigger


def test_largest_sample_that_fits_hand_worked():
    # one 50-post thread and ten 5-post threads: at n = 55 the cap is 5, and 5 + 10 x 5 = 55 fits;
    # from 56 to 59 the cap is still 5; at 60 and above the cap c gives c + 50 < 10c
    assert thread_cap_size([50] + [5] * 10, 150, 10) == (55, 5)
    assert thread_cap_size([10] * 10, 150, 10) == (100, 10)
    assert thread_cap_size([100] * 20, 150, 10) == (150, 15)
    assert thread_cap_size([10] * 4, 150, 10) == (0, 0)
    assert thread_cap_size([10] * 4, 150, 25) == (40, 10)
    assert thread_cap_size([30, 2], 150, 100) == (32, 32)


def test_fewer_than_ten_threads_stops_until_the_cap_is_loosened(fixture_study):
    with pytest.raises(InputError, match=r"at least 10 threads, and the frame has 4 .*--thread-cap-pct"):
        sample(fixture_study, seed=1)
    assert manifest.read(fixture_study)[-1]["status"] == "failed"
    assert not (fixture_study / "samples" / "measurement.jsonl").exists()
    s = sample(fixture_study, seed=1, thread_cap_pct=30)
    assert s["measurement"]["thread_cap_pct"] == 30
    assert manifest.read(fixture_study)[-1]["settings"]["thread_cap_pct"] == 30
    drawn = read_jsonl(fixture_study / "samples" / "measurement.jsonl")
    assert all(100 * k <= 30 * len(drawn) for k in Counter(r["thread_id"] for r in drawn).values())


# ---- frame rules -------------------------------------------------------------

def test_frame_leaves_out_promotional_echo_and_interview_posts(fixture_study):
    s = sample(fixture_study, seed=1, thread_cap_pct=30)
    assert s["measurement"]["frame"]["left_out"] == {"echo_reply": 1, "promotional": 1}
    assert s["measurement"]["frame"]["eligible"] == 68
    detail = {r["post_id"]: r for r in read_jsonl(fixture_study / "samples" / "detail.jsonl")}
    measured = {r["post_id"] for r in read_jsonl(fixture_study / "samples" / "measurement.jsonl")}
    for left_out in ("T01-p09", "T02-p12"):  # the promotional post and the echo reply
        assert left_out not in detail and left_out not in measured
    interview = {pid for pid, r in detail.items() if r["source_type"] == "interview"}
    assert len(interview) == 4 and all(detail[i]["reasons"] == ["interview"] for i in interview)
    assert not interview & measured


def test_short_comments_are_left_out_but_short_opening_posts_kept(tmp_path):
    rows = [post("T01", 1, "P-00000001", "Sync broken?"),
            post("T01", 2, "P-00000002", "Try logging out.", "T01-p01"),
            post("T01", 3, "P-00000003", "Logging out and back in fixed the sync for me.", "T01-p01")]
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "posts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    signals(tmp_path)
    s = sample(tmp_path, seed=1, thread_cap_pct=100)
    assert s["measurement"]["frame"]["left_out"] == {"short": 1}
    assert {r["post_id"] for r in read_jsonl(tmp_path / "samples" / "measurement.jsonl")} == {"T01-p01", "T01-p03"}


# ---- detail posts never reach the measurement stats -------------------------

def test_detail_posts_cannot_enter_measurement_stats(tmp_path):
    synthetic(tmp_path, prolific_posts=12)
    sample(tmp_path, seed=4, budget=30)
    measured = {r["post_id"] for r in read_jsonl(tmp_path / "samples" / "measurement.jsonl")}
    detail = load_detail(tmp_path)
    assert all(item.selection == "purposive" and item.reasons for item, _ in detail)
    detail_only = [item.post_id for item, _ in detail if item.post_id not in measured]
    assert detail_only
    posts = load_measurement(tmp_path)
    assert {p.post_id for p in posts} == measured
    assert not {p.post_id for p in posts} & set(detail_only)


def test_planting_a_detail_row_in_the_measurement_sample_is_refused(tmp_path):
    synthetic(tmp_path)
    sample(tmp_path, seed=4, budget=30)
    path = tmp_path / "samples" / "measurement.jsonl"
    detail_row = (tmp_path / "samples" / "detail.jsonl").read_text().splitlines()[0]
    path.write_text(path.read_text() + detail_row + "\n")
    with pytest.raises(InputError, match="edited since crp sample drew it"):
        load_measurement(tmp_path)
    # even with the recorded hash forged to match, the row itself is rejected
    summary_path = tmp_path / "samples" / "summary.json"
    summary = json.loads(summary_path.read_text())
    from crp.io import sha256_file
    summary["measurement"]["sha256"] = sha256_file(path)
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(InputError, match=r"selection|reasons|source_type"):
        load_measurement(tmp_path)


def test_edited_sample_is_refused(tmp_path):
    synthetic(tmp_path)
    sample(tmp_path, seed=4)
    path = tmp_path / "samples" / "measurement.jsonl"
    path.write_text("".join(path.read_text().splitlines(keepends=True)[1:]))
    with pytest.raises(InputError, match="edited since crp sample drew it"):
        load_measurement(tmp_path)


# ---- guards ------------------------------------------------------------------

def test_no_redraw_once_coding_has_started(tmp_path):
    synthetic(tmp_path)
    sample(tmp_path, seed=4)
    (tmp_path / "batches").mkdir()
    (tmp_path / "batches" / "batch_001.jsonl").write_text("{}\n")
    with pytest.raises(InputError, match="the sample is fixed"):
        sample(tmp_path, seed=5)


def test_signals_must_match_the_current_posts(tmp_path):
    synthetic(tmp_path)
    with (tmp_path / "posts.jsonl").open("a") as f:
        f.write(json.dumps(post("T99", 1, "P-0000ffff", "A late post about search being slow on every device.")) + "\n")
    with pytest.raises(InputError, match="Run crp signals again"):
        sample(tmp_path, seed=1)


def test_signals_must_have_run(tmp_path):
    synthetic(tmp_path)
    (tmp_path / "signals.jsonl").unlink()
    with pytest.raises(InputError, match="Run crp signals first"):
        sample(tmp_path, seed=1)



def test_cli(fixture_study, capsys):
    from crp.cli import main
    assert main(["sample", str(fixture_study), "--seed", "3"]) == 2
    assert "--thread-cap-pct" in capsys.readouterr().err
    assert main(["sample", str(fixture_study), "--seed", "3", "--thread-cap-pct", "30"]) == 0
    out = capsys.readouterr().out
    assert "Seed 3 (given)" in out and "not the method's 10%" in out and "4 participant turn(s)" in out
    assert main(["sample", str(fixture_study), "--thread-cap-pct", "30"]) == 0
    assert "Seed 3 (reused from the last run)" in capsys.readouterr().out


def test_interview_only_study_has_detail_but_no_measurement_sample(study, no_ocr, tmp_path):
    import shutil
    d = tmp_path / "interviews-only"
    shutil.copytree(study / "raw" / "interviews", d / "raw" / "interviews")
    ingest(d)
    verify(d)
    anonymise(d, FIXTURE_SECRETS)
    signals(d)
    s = sample(d, seed=1)
    assert s["measurement"]["drawn"] == 0 and s["detail"]["interview_turns"] == 4
    assert load_measurement(d) == []
    assert [item.reasons for item, _ in load_detail(d)] == [["interview"]] * 4
