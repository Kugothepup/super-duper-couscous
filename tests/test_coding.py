"""Codebook freeze, blinded batches, label validation and locking, and unseal."""
import json
import os
import time

import pytest
import yaml

from conftest import read_jsonl, write_labels
from crp import manifest
from crp.agreement import export, score
from crp.batch import HEADER_FIELDS, ITEM_FIELDS, VARIABLE_FIELDS, make_batches
from crp.codebook import freeze
from crp.io import InputError
from crp.labels import lock, locked, unseal, validate


def edit_codebook(d, change):
    data = yaml.safe_load((d / "codebook.yaml").read_text())
    change(data)
    (d / "codebook.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def batch_lines(d):
    return {p.stem: [json.loads(line) for line in p.read_text().splitlines()]
            for p in sorted((d / "batches").glob("batch_*.jsonl"))}


def label_rows(d, batch):
    return read_jsonl(d / "labels" / f"{batch}.labels.jsonl")


def put_labels(d, batch, rows):
    (d / "labels" / f"{batch}.labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def write_prior(d):
    (d / "sealed").mkdir(exist_ok=True)
    (d / "sealed" / "prior.md").write_text("Test prior, written by the test.\n")


# ---- codebook freeze ---------------------------------------------------------

def test_freeze_writes_version_and_hash_and_is_safe_to_rerun(batched):
    lock_data = json.loads((batched / "codebook.lock").read_text())
    assert lock_data["version"] == "1" and len(lock_data["sha256"]) == 64
    assert freeze(batched)["unchanged"]


def test_a_changed_codebook_blocks_every_later_stage(batched):
    write_labels(batched)
    edit_codebook(batched, lambda c: c["aspects"].append("export"))
    for stage in (make_batches, validate, lambda d: lock(d, "m"), unseal, export, score):
        with pytest.raises(InputError, match="has changed since version 1 was frozen"):
            stage(batched)
    with pytest.raises(InputError, match="Steeve's call"):
        freeze(batched)


def test_new_version_moves_old_coding_aside(batched):
    write_labels(batched)
    edit_codebook(batched, lambda c: c["aspects"].append("export"))
    with pytest.raises(InputError, match="still says version 1"):
        freeze(batched, new_version=True)
    edit_codebook(batched, lambda c: c.update(version="2"))
    out = freeze(batched, new_version=True)
    assert out["version"] == "2" and out["replaces"] == "1"
    old = batched / "superseded" / "codebook-v1"
    assert (old / "batches" / "batch_001.jsonl").exists() and (old / "labels" / "batch_001.labels.jsonl").exists()
    assert not (batched / "labels").exists()
    assert make_batches(batched)["batches"]


def test_codebook_design_checks(batched):
    edit_codebook(batched, lambda c: c.update(study_type="brand"))
    (batched / "codebook.lock").unlink()
    with pytest.raises(InputError, match="for a brand study, but study.yaml says product"):
        freeze(batched)
    edit_codebook(batched, lambda c: c.update(study_type="product", variables=c["variables"][1:]))
    with pytest.raises(InputError, match="needs a 'overall' variable"):
        freeze(batched)
    study = yaml.safe_load((batched / "study.yaml").read_text())
    (batched / "study.yaml").write_text(yaml.safe_dump(study | {"type": "news", "stance_target": "x"}))
    edit_codebook(batched, lambda c: c.update(study_type="news"))
    with pytest.raises(InputError, match="'overall'|'stance'"):
        freeze(batched)


# ---- batches -----------------------------------------------------------------

def test_batch_files_hold_nothing_outside_the_allow_list(batched):
    posts = read_jsonl(batched / "posts.jsonl")
    study = yaml.safe_load((batched / "study.yaml").read_text())
    texts = " ".join(p["text"] for p in posts)
    forbidden = {p["person_code"] for p in posts} | {p["post_id"] for p in posts} | {p["raw_ref"] for p in posts}
    forbidden |= {p["thread_title"] for p in posts if p["thread_title"] and p["thread_title"] not in texts}
    forbidden |= {p["search_term"] for p in posts if p["search_term"] and p["search_term"] not in texts}
    forbidden |= set(study["questions"]) | set(study["sources"]) | {study["subject"], study["population"], study["owner"]}
    forbidden |= {"T01", "T02", "T03", "T04", "I01", "high_engagement", '"score":', '"timestamp":', '"flags":',
                  '"person_code":', '"thread_id":', '"promotional":'}
    for name, lines in batch_lines(batched).items():
        header, items = lines[0], lines[1:]
        assert set(header) <= set(HEADER_FIELDS) and header["record"] == "header"
        assert set(header["codebook"]) <= {"aspects", "variables"}
        for v in header["codebook"]["variables"]:
            assert set(v) <= set(VARIABLE_FIELDS)
        for item in items:
            assert set(item) <= set(ITEM_FIELDS) and {"item_id", "text"} <= set(item)
        raw = (batched / "batches" / f"{name}.jsonl").read_text()
        for word in forbidden:
            assert word not in raw, f"{word!r} is in {name}"


def test_every_sampled_post_is_batched_once_with_its_context(batched):
    posts = {p["post_id"]: p for p in read_jsonl(batched / "posts.jsonl")}
    index = json.loads((batched / "batches" / "index.json").read_text())
    lines = {i["item_id"]: i for ls in batch_lines(batched).values() for i in ls[1:]}
    measured = [r["post_id"] for r in read_jsonl(batched / "samples" / "measurement.jsonl")]
    detail = [r["post_id"] for r in read_jsonl(batched / "samples" / "detail.jsonl")]
    by_sample = {"measurement": [], "detail": []}
    for b in index["batches"]:
        for it in b["items"]:
            by_sample[b["sample"]].append(it["post_id"])
            post, line = posts[it["post_id"]], lines[it["item_id"]]
            assert line["text"] == post["text"]
            if post["source_type"] == "forum" and post["parent_id"]:
                assert line["parent_text"] == posts[post["parent_id"]]["text"]
            elif post["source_type"] == "interview":
                assert line["parent_text"].endswith("?")  # the interviewer's question before the turn
            else:
                assert "parent_text" not in line
    assert sorted(by_sample["measurement"]) == sorted(measured) and sorted(by_sample["detail"]) == sorted(detail)
    assert by_sample["measurement"] != measured  # shuffled, not in thread order


def test_batches_are_reproducible_and_fixed_once_coding_starts(batched, tmp_path):
    before = {p.name: p.read_bytes() for p in (batched / "batches").iterdir()}
    assert make_batches(batched)["unchanged"]
    make_batches(batched, seed=99)
    assert {p.name: p.read_bytes() for p in (batched / "batches").iterdir()} != before
    make_batches(batched)  # back to the sample's seed
    assert {p.name: p.read_bytes() for p in (batched / "batches").iterdir()} == before
    write_labels(batched)
    assert make_batches(batched)["unchanged"]
    with pytest.raises(InputError, match="the batches are fixed"):
        make_batches(batched, size=10)


# ---- labels validate ---------------------------------------------------------

def test_clean_labels_pass(batched):
    write_labels(batched)
    report = validate(batched)
    assert report["ok"] and sum(b["coded"] for b in report["batches"]) == sum(b["items"] for b in report["batches"])


@pytest.mark.parametrize("change, message", [
    (lambda r: r[0]["values"].update(friction=1), "'friction' is 1, not one of [true, false]"),
    (lambda r: r[1]["values"].update(severity="2"), "'severity' is \"2\""),
    (lambda r: r[0]["values"].update(jtbd_force="Push"), "'jtbd_force' is \"Push\""),
    (lambda r: r[0]["values"].update(mood="angry"), "'mood' isn't a variable this batch codes"),
    (lambda r: r[0]["values"].pop("aspect"), "'aspect' is missing"),
    (lambda r: r[0]["values"].update(friction=False, severity=2), "'severity' must be null because friction is false"),
    (lambda r: r[1]["values"].update(friction=True, severity=None), "'severity' is required because friction is true"),
    (lambda r: r[0]["values"].update(jtbd_force=None), "'jtbd_force' can't be null"),
    (lambda r: r.append(dict(r[0])), "labelled more than once"),
    (lambda r: r.append({"item_id": "d9999", "values": {}}), "d9999: not an item in this batch"),
    (lambda r: r.pop(), "1 item(s) not labelled"),
])
def test_bad_detail_labels_fail(batched, change, message):
    write_labels(batched)
    rows = label_rows(batched, "batch_002")
    change(rows)
    put_labels(batched, "batch_002", rows)
    report = validate(batched)
    assert not report["ok"]
    assert any(message in e for b in report["batches"] for e in b["errors"]), report["batches"][1]["errors"]


def test_bad_measurement_labels_fail_and_warnings_are_raised(batched):
    write_labels(batched)
    rows = label_rows(batched, "batch_001")
    rows[0]["values"]["aspect_scores"] = {"speed": -1, "sync": True}
    rows[1]["values"].update(overall=-1, aspect_scores={"sync": 1, "search": 2})
    rows[2], rows[3] = rows[3], rows[2]
    put_labels(batched, "batch_001", rows)
    (batched / "labels" / "batch_002.labels.jsonl").write_text("not json\n")
    report = {b["batch"]: b for b in validate(batched)["batches"]}
    errors = report["batch_001"]["errors"]
    assert any("values.aspect_scores" in e for e in errors)  # true isn't a score, even though 1 == True
    rows[0]["values"]["aspect_scores"] = {"speed": -1}
    put_labels(batched, "batch_001", rows)
    report = {b["batch"]: b for b in validate(batched)["batches"]}
    assert any("'speed' isn't in the codebook's aspect list" in e for e in report["batch_001"]["errors"])
    assert any("point opposite ways" in w for w in report["batch_001"]["warnings"])
    assert any("aren't in the order" in w for w in report["batch_001"]["warnings"])
    assert any("not valid JSON" in e for e in report["batch_002"]["errors"])
    assert validate(batched, ["batch_003"])["ok"]


def test_uncoded_batches_and_edited_batch_files_fail(batched):
    report = validate(batched)
    assert not report["ok"] and "not coded yet" in report["batches"][0]["errors"][0]
    path = batched / "batches" / "batch_001.jsonl"
    path.write_text(path.read_text().replace("update", "upgrade", 1))
    with pytest.raises(InputError, match="has been edited since crp batch wrote it"):
        validate(batched)


# ---- lock and unseal ---------------------------------------------------------

def test_unseal_fails_before_lock(batched):
    write_prior(batched)
    write_labels(batched)
    with pytest.raises(InputError, match="aren't locked yet"):
        unseal(batched)
    assert not (batched / "results" / "prior.md").exists()


def test_lock_needs_clean_labels_and_a_coder_model(batched):
    with pytest.raises(InputError, match="problem"):
        lock(batched, "claude-opus-5-5")
    write_labels(batched)
    with pytest.raises(InputError, match="coder model"):
        lock(batched, " ")
    data = lock(batched, "claude-opus-5-5")
    assert data["coder_model"] == "claude-opus-5-5" and "labels/batch_001.labels.jsonl" in data["files"]
    assert lock(batched, "claude-opus-5-5")["unchanged"]
    rec = manifest.read(batched)[-1]
    assert rec["command"] == "labels lock" and rec["coder_model"] == "claude-opus-5-5" and rec["codebook_version"] == "1"
    with pytest.raises(InputError, match="labels are locked"):
        make_batches(batched)


def test_unseal_copies_the_prior_only_after_lock_and_refuses_changed_labels(batched):
    write_prior(batched)
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    out = unseal(batched)
    assert (batched / "results" / "prior.md").read_bytes() == (batched / "sealed" / "prior.md").read_bytes()
    assert out["prior_modified_after_first_ingest"]  # the test wrote the prior after ingest
    assert manifest.read(batched)[-1]["command"] == "unseal"
    rows = label_rows(batched, "batch_001")
    rows[0]["values"]["overall"] = 2 if rows[0]["values"]["overall"] != 2 else 1
    put_labels(batched, "batch_001", rows)
    with pytest.raises(InputError, match="changed since the lock: labels/batch_001.labels.jsonl"):
        locked(batched)
    with pytest.raises(InputError, match="changed since the lock"):
        unseal(batched)


def test_prior_written_before_ingest_is_not_flagged(batched):
    write_prior(batched)
    first = min(r["started"] for r in manifest.read(batched) if r["command"] == "ingest")
    import datetime as dt
    earlier = dt.datetime.fromisoformat(first).timestamp() - 3600
    os.utime(batched / "sealed" / "prior.md", (earlier, earlier))
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    assert not unseal(batched)["prior_modified_after_first_ingest"]


def test_unseal_needs_a_prior(batched):
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    with pytest.raises(InputError, match="No sealed/prior.md"):
        unseal(batched)


def test_cli_runs_every_coding_stage(batched, capsys):
    from crp.cli import main
    d = str(batched)
    assert main(["codebook", "freeze", d]) == 0 and "already frozen" in capsys.readouterr().out
    assert main(["batch", d]) == 0 and "batch_003  detail" in capsys.readouterr().out
    assert main(["labels", "validate", d]) == 1 and "not coded yet" in capsys.readouterr().out
    write_labels(batched)
    assert main(["labels", "validate", d, "--batch", "batch_002"]) == 0
    assert main(["unseal", d]) == 2 and "aren't locked yet" in capsys.readouterr().err
    assert main(["labels", "lock", d, "--coder-model", "claude-opus-5-5"]) == 0
    write_prior(batched)
    assert main(["unseal", d]) == 0 and "after the first crp ingest" in capsys.readouterr().out
    assert main(["agreement", "export", d, "--n", "20", "--measurement-n", "12"]) == 0
    assert "20 of 100 coded items (12 measurement, then 8 detail)" in capsys.readouterr().out
    assert main(["agreement", "score", d]) == 2 and "No human/human_labels.csv" in capsys.readouterr().err
