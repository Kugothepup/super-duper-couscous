"""Rounds (D35) and top-ups (D37): adding to a coded study keeps earlier picks and reuses their labels."""
import json

import pytest

from conftest import FIXTURE_SECRETS, dummy_values, read_jsonl, write_labels
from crp import manifest
from crp.anonymise import anonymise
from crp.batch import make_batches
from crp.cli import main
from crp.ingest import ingest
from crp.io import InputError
from crp.labels import lock, validate
from crp.rounds import start_round, topup
from crp.sample import sample
from crp.signals import signals
from crp.verify import verify

MODEL = "claude-opus-5-5"
NEW_THREAD = [  # an invented fifth thread: an opening post and replies from new people
    ("fresh_start", None, "Thinking of moving my research notes into Quillnote this summer, is it still worth it?"),
    ("birch_leaf", "p1", "The templates alone are worth it, I set up a reading log in an afternoon."),
    ("stone_path", "p1", "Sync has been shaky for me since June, so I keep a backup in plain text files."),
    ("tall_grass", "p1", "Price went up again last spring and our department stopped paying for it."),
    ("wide_river", "p1", "Backlinks are the reason I stay, nothing else links ideas as easily as this."),
    ("low_cloud", "p1", "Search is fine with a small archive but gets slow once you have thousands of notes."),
    ("red_kite", "p1", "I moved to a folder of markdown files and only miss the daily note feature."),
]


def add_thread(study, name="fifth"):
    (study / "raw" / f"{name}.txt").write_text("\n\n".join(t for _, _, t in NEW_THREAD) + "\n")
    posts = [{"id": f"p{i + 1}", "author": a, "date": f"2026-07-{i + 1:02d}", "parent": parent, "text": text}
             for i, (a, parent, text) in enumerate(NEW_THREAD)]
    (study / "raw" / "capture" / f"{name}.json").write_text(json.dumps(
        {"source_file": f"{name}.txt", "site": "reddit.com/r/notetaking", "captured": "2026-09-20",
         "thread_title": "Still worth it?", "posts": posts}))


def rerun(study, **kw):
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    sample(study, thread_cap_pct=30, **kw)
    return make_batches(study)


def coded_labels(study) -> dict[tuple[str, str], dict]:
    index = json.loads((study / "batches" / "index.json").read_text())
    out = {}
    for b in index["batches"]:
        rows = {r["item_id"]: r["values"] for r in read_jsonl(study / "labels" / f"{b['batch']}.labels.jsonl")}
        out.update({(b["sample"], it["post_id"]): rows[it["item_id"]] for it in b["items"]})
    return out


def code_new_batches(study):
    """Dummy labels for the batches the blind coder would get; reused ones are already there."""
    index = json.loads((study / "batches" / "index.json").read_text())
    for b in index["batches"]:
        if "reused" not in b:
            rows = [{"item_id": it["item_id"], "values": dummy_values(b["sample"], n + 3)} for n, it in enumerate(b["items"])]
            (study / "labels" / f"{b['batch']}.labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


@pytest.fixture
def locked_round(batched):
    write_labels(batched)
    lock(batched, MODEL)
    return batched


def test_round_needs_locked_labels(batched):
    with pytest.raises(InputError, match="aren't locked yet"):
        start_round(batched, "added a thread")


def test_adding_a_thread_keeps_earlier_picks_and_codes_only_new_ones(locked_round):
    """Phase 7b's check: most earlier picks stay, only new picks are batched, and reused labels are counted."""
    d = locked_round
    before = coded_labels(d)
    old_measurement = {pid for s, pid in before if s == "measurement"}
    rep = start_round(d, "added a fifth thread")
    assert rep["closed"] == 1 and rep["next"] == 2 and (d / "rounds" / "1" / "labels.lock").exists()
    assert not (d / "batches").exists() and not (d / "labels.lock").exists()
    add_thread(d)
    out = rerun(d)
    assert out["reused_from"] == "rounds/1"
    new_measurement = {r["post_id"] for r in read_jsonl(d / "samples" / "measurement.jsonl")}
    kept = old_measurement & new_measurement
    assert len(kept) >= 0.7 * len(old_measurement)  # the seed carried over and the draw is stable
    index = json.loads((d / "batches" / "index.json").read_text())
    reused = {(b["sample"], it["post_id"]) for b in index["batches"] if "reused" in b for it in b["items"]}
    to_code = {(b["sample"], it["post_id"]) for b in index["batches"] if "reused" not in b for it in b["items"]}
    assert reused and to_code and not reused & to_code
    assert all(key in before for key in reused)  # only earlier items are reused ...
    assert all(key not in before for key in to_code)  # ... and only new ones go to the coder
    assert {pid for _, pid in to_code} >= {r["post_id"] for r in read_jsonl(d / "posts.jsonl") if r["thread_id"] == "T05"}
    code_new_batches(d)
    assert validate(d)["ok"]
    data = lock(d, MODEL)
    assert data["reused_items"] == len(reused) and data["reused_from"] == "rounds/1"
    runs = manifest.read(d)
    assert [r["reused_items"] for r in runs if r["command"] == "labels lock"][-1] == len(reused)
    after = coded_labels(d)
    assert all(after[key] == before[key] for key in reused)  # the reused labels are the earlier ones, unchanged


def test_reused_labels_refuse_a_different_coder_model(locked_round):
    d = locked_round
    start_round(d, "added a fifth thread")
    add_thread(d)
    rerun(d)
    code_new_batches(d)
    with pytest.raises(InputError, match="can't be mixed"):
        lock(d, "another-model")


def test_edited_reused_labels_are_caught(locked_round):
    d = locked_round
    start_round(d, "added a fifth thread")
    add_thread(d)
    rerun(d)
    code_new_batches(d)
    path = d / "labels" / "reused_measurement.labels.jsonl"
    path.write_text(path.read_text().replace('"overall": 2', '"overall": -2', 1))
    assert not validate(d)["ok"]


def test_no_reuse_codes_everything_again(locked_round):
    d = locked_round
    start_round(d, "new coder model")
    ingest(d)
    verify(d)
    anonymise(d, FIXTURE_SECRETS)
    signals(d)
    sample(d, thread_cap_pct=30)
    out = make_batches(d, reuse=False)
    assert not any(b["reused"] for b in out["batches"]) and out["reused_from"] is None


def test_topup_adds_named_posts_to_the_detail_selection_only(locked_round):
    """D37: after a new round, named posts join the detail selection with their reason; percentages don't move."""
    d = locked_round
    measurement = (d / "samples" / "measurement.jsonl").read_text()
    with pytest.raises(InputError, match="batches already exist"):
        topup(d, ["T03-p02"], "explain the sync driver")
    start_round(d, "top-up: explain the sync driver")
    posts = read_jsonl(d / "posts.jsonl")
    detail = {r["post_id"] for r in read_jsonl(d / "rounds" / "1" / "samples" / "detail.jsonl")}
    outside = next(p["post_id"] for p in posts if p["source_type"] == "forum" and p["post_id"] not in detail)
    rep = topup(d, [outside], "explain the sync driver")
    assert rep["added"] == [outside]
    out = rerun(d)
    new = {r["post_id"]: r for r in read_jsonl(d / "samples" / "detail.jsonl")}
    assert new[outside]["reasons"] == ["topup: explain the sync driver"]
    assert (d / "samples" / "measurement.jsonl").read_text() == measurement
    index = json.loads((d / "batches" / "index.json").read_text())
    to_code = [it["post_id"] for b in index["batches"] if "reused" not in b for it in b["items"]]
    assert to_code == [outside]
    assert sum(1 for b in out["batches"] if not b["reused"]) == 1


def test_cli_round_and_topup(locked_round, capsys):
    d = str(locked_round)
    assert main(["round", d, "--reason", "added a fifth thread"]) == 0
    out = capsys.readouterr().out
    assert "Closed round 1" in out and "--thread-cap-pct 30" in out
    assert main(["topup", d, "T01-p02", "--reason", "explain pricing"]) == 0
    assert "Added 1 post(s)" in capsys.readouterr().out


def fake_posts(n: int):
    from crp.schemas import Post
    return [Post(post_id=f"T01-p{i + 1:02d}", source_type="forum", source="s", thread_id="T01", kind="comment",
                 person_code=f"P-{i:08x}", text=f"post {i}", capture_method="paste", raw_ref=f"x#{i}")
            for i in range(n)]


def test_heard_enough_averages_over_orders():
    """D39: a topic in one post of four is found by the k-th post in k/4 of orders, whatever order they came in."""
    from crp.analyse import heard_enough
    posts = fake_posts(4)
    tags = {"T01-p01": {"sync"}, "T01-p02": {"sync", "search"}, "T01-p03": {"search"}, "T01-p04": {"pricing"}}
    he = heard_enough(posts, tags, 20000, seed=5)
    assert (he["posts"], he["topics"], he["mean"][-1], he["low"][-1], he["high"][-1]) == (4, 3, 3.0, 3.0, 3.0)
    # pricing is in one post of four: found by post k in k/4 of orders; sync and search in two of four
    exact = [k / 4 + 2 * (1 - (4 - k) * (3 - k) / 12) for k in range(1, 5)]
    assert he["mean"] == pytest.approx(exact, abs=0.03)
    assert all(lo <= m <= hi for lo, m, hi in zip(he["low"], he["mean"], he["high"]))
    assert he == heard_enough(posts, tags, 20000, seed=5)  # seeded
    assert heard_enough(posts, {}, 100, seed=5) is None


def test_round_comparison_reaches_the_report(locked_round, capsys):
    """Phase 7b's check, end to end: the round comparison appears in the report and check-numbers passes."""
    from conftest import write_synthesis
    from crp.analyse import analyse
    from crp.build import build
    from crp.numbers import check_numbers
    d = locked_round
    write_synthesis(d)
    first = analyse(d, draws=200)["results"]
    start_round(d, "added a fifth thread")
    add_thread(d)
    rerun(d)
    code_new_batches(d)
    lock(d, MODEL)
    out = analyse(d, draws=200)["results"]
    ro = out.rounds
    assert (ro.current, ro.reason, ro.earlier[0].round) == (2, "added a fifth thread", 1)
    assert ro.earlier[0].n_items == first.sample.n_items and ro.earlier[0].negative == first.headline.negative
    assert ro.change_pts == round(out.headline.negative.pct - first.headline.negative.pct, 1)
    assert out.heard_enough and out.heard_enough.topics >= 1
    build(d)
    report = (d / "results" / "report.md").read_text()
    assert "This is round 2: added a fifth thread." in report and "## Have we heard enough?" in report
    assert 'class="heard"' in (d / "results" / "dashboard.html").read_text()
    assert check_numbers(d)["ok"]


def test_status_follows_the_study(locked_round):
    from crp.status import status
    d = locked_round
    by = {s.name: s for s in status(d)["stages"]}
    assert by["labels lock"].state == "done" and by["prior"].state == "skipped"
    assert by["agreement"].state == "to do" and by["analyse"].state == "to do"
    start_round(d, "added a fifth thread")
    add_thread(d)
    rep = status(d)
    by = {s.name: s for s in rep["stages"]}
    assert rep["round"]["round"] == 2
    assert by["ingest"].state == "stale" and "fifth" in by["ingest"].why
    assert by["sample"].state == "to do" and by["batch"].state == "to do"
    assert rep["next"]["do"] == "crp ingest"
    rerun(d)
    by = {s.name: s for s in status(d)["stages"]}
    assert by["blind coding"].state == "waiting on Claude" and "batch_001" in by["blind coding"].why
    (d / "codebook.yaml").write_text((d / "codebook.yaml").read_text() + "\n# a change\n")
    assert {s.name: s for s in status(d)["stages"]}["codebook"].state == "blocked"


def test_reset_archives_and_keeps_the_sources(locked_round, capsys):
    from crp.rounds import reset
    d = locked_round
    assert main(["reset", str(d)]) == 2 and "--yes" in capsys.readouterr().err
    rep = reset(d)
    archive = d / rep["archive"]
    for rel in ("posts.jsonl", "labels.lock", "codebook.lock", "batches", "samples"):
        assert (archive / rel).exists() and not (d / rel).exists()
    for kept in ("raw", "study.yaml", "collection_log.csv", "codebook.yaml", "results/run_manifest.json"):
        assert (d / kept).exists()
    assert manifest.read(d)[-1]["command"] == "reset"


def test_the_range_draws_through_the_middle_of_each_step():
    from crp.build import through_steps
    steps = [0, 0, 1, 1, 1, 2, 2, 3, 3, 3]
    drawn = through_steps(steps)
    assert drawn[0] == 0 and drawn[-1] == 3
    assert all(abs(a - b) <= 0.5 for a, b in zip(drawn, steps))
    assert all(a <= b for a, b in zip(drawn, drawn[1:]))  # still never falls
