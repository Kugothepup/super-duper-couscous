import json
import subprocess
import sys
from pathlib import Path

from crp import thresholds
from crp.cli import main
from crp.io import read_csv, read_yaml
from crp.schemas import COLLECTION_LOG_COLUMNS, CollectionLogRow, Study

ARGS = ["new", "notion-teams", "--subject", "Notion for research teams", "--type", "product",
        "--question", "Why do research teams leave?"]


def run(tmp_path, *extra):
    return main([*ARGS, "--root", str(tmp_path / "studies"), *extra])


def test_new_scaffolds_a_study(tmp_path):
    assert run(tmp_path) == 0
    d = tmp_path / "studies" / "notion-teams"
    for sub in ("raw", "sealed", "samples", "batches", "labels", "human", "results"):
        assert (d / sub).is_dir()
    assert list((d / "sealed").iterdir()) == []
    study = read_yaml(d / "study.yaml", Study)
    assert study.id == "notion-teams" and study.questions == ["Why do research teams leave?"]
    assert (d / "collection_log.csv").read_text() == ",".join(COLLECTION_LOG_COLUMNS) + "\n"
    assert read_csv(d / "collection_log.csv", CollectionLogRow, COLLECTION_LOG_COLUMNS) == []


def test_new_writes_a_manifest_record(tmp_path):
    run(tmp_path)
    [rec] = json.loads((tmp_path / "studies/notion-teams/results/run_manifest.json").read_text())
    assert rec["command"] == "new" and rec["status"] == "ok"
    assert rec["seconds"] >= 0 and rec["packages"]["pydantic"] and rec["packages"]["python"]
    assert set(rec["outputs"]) >= {"study.yaml", "collection_log.csv", "sealed/"}


def test_new_is_safe_to_rerun(tmp_path, capsys):
    run(tmp_path)
    d = tmp_path / "studies" / "notion-teams"
    before = (d / "study.yaml").read_text()
    (d / "collection_log.csv").write_text(
        ",".join(COLLECTION_LOG_COLUMNS) + "\nforum,x,2026-09-20,why,y,3,1,\n")
    assert run(tmp_path) == 0
    assert (d / "study.yaml").read_text() == before
    assert "forum,x" in (d / "collection_log.csv").read_text()
    assert "nothing was overwritten" in capsys.readouterr().out
    assert len(json.loads((d / "results/run_manifest.json").read_text())) == 2


def test_new_refuses_to_change_an_existing_study(tmp_path, capsys):
    run(tmp_path)
    d = tmp_path / "studies" / "notion-teams"
    before = (d / "study.yaml").read_text()
    assert main([*ARGS[:3], "Something else", *ARGS[4:], "--root", str(tmp_path / "studies")]) == 2
    assert "already exists with different settings" in capsys.readouterr().err
    assert (d / "study.yaml").read_text() == before


def test_bad_id_creates_nothing(tmp_path, capsys):
    code = main(["new", "Notion Teams", "--subject", "X", "--type", "product", "--root", str(tmp_path / "s")])
    assert code == 2
    assert "study settings: id: String should match pattern" in capsys.readouterr().err
    assert not (tmp_path / "s").exists()


def test_news_study_without_stance_target_warns(tmp_path, capsys):
    main(["new", "four-day-week", "--subject", "Four-day week", "--type", "news", "--root", str(tmp_path)])
    assert "need --stance-target" in capsys.readouterr().out


def test_module_entry_point(tmp_path):
    out = subprocess.run([sys.executable, "-m", "crp", "new", "cli-check", "--subject", "X", "--type", "brand",
                          "--root", str(tmp_path)], capture_output=True, text=True, cwd=Path(__file__).parents[1])
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "cli-check" / "study.yaml").exists()


def test_thresholds_match_claude_md():
    assert thresholds.result_status(19, 500) == "counts-only"
    assert thresholds.result_status(20, 59) == "early-signal"
    assert thresholds.result_status(20, 60) == "full"
    assert [thresholds.agreement_status(a) for a in (None, 0.66, 0.667, 0.79, 0.80)] == \
        ["unverified", "unverified", "tentative", "tentative", "verified"]
