import hashlib

import pytest

from crp import manifest


def test_stage_records_inputs_seed_and_versions(tmp_path):
    (tmp_path / "results").mkdir()
    posts = tmp_path / "posts.jsonl"
    posts.write_text('{"a": 1}\n')
    with manifest.stage(tmp_path, "sample", inputs=[posts], seed=42, codebook_version="1",
                        coder_model="claude-opus-5-5") as rec:
        rec["outputs"] = ["samples/measurement.jsonl"]
    [r] = manifest.read(tmp_path)
    assert r["inputs"] == {"posts.jsonl": hashlib.sha256(b'{"a": 1}\n').hexdigest()}
    assert (r["seed"], r["codebook_version"], r["coder_model"]) == (42, "1", "claude-opus-5-5")
    assert r["status"] == "ok" and r["seconds"] >= 0 and r["ended"] >= r["started"]
    assert r["outputs"] == ["samples/measurement.jsonl"]


def test_failed_stage_is_recorded_and_the_error_raised(tmp_path):
    with pytest.raises(RuntimeError):
        with manifest.stage(tmp_path, "analyse"):
            raise RuntimeError("bootstrap blew up")
    [r] = manifest.read(tmp_path)
    assert r["status"] == "failed" and r["error"] == "RuntimeError: bootstrap blew up"


def test_records_are_appended_not_replaced(tmp_path):
    for cmd in ("new", "ingest", "verify"):
        with manifest.stage(tmp_path, cmd):
            pass
    assert [r["command"] for r in manifest.read(tmp_path)] == ["new", "ingest", "verify"]
