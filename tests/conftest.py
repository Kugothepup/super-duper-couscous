import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_STUDY = FIXTURES / "quillnote-fixture"
FIXTURE_SECRETS = FIXTURES / "fixture-secrets"
REFERENCE = Path(__file__).parent / "reference"


@pytest.fixture
def good_post() -> dict:
    return {"post_id": "T1-p02", "source_type": "forum", "source": "reddit.com/r/notetaking", "thread_id": "T1",
            "parent_id": "T1-p01", "person_code": "P-0a1b2c3d", "kind": "comment",
            "timestamp": "2026-04-02T09:14:00", "score": 3, "text": "Search takes ten seconds now.",
            "capture_method": "export", "raw_ref": "thread.json#p02"}


@pytest.fixture
def study(tmp_path) -> Path:
    """A copy of the fixture study's inputs, at <tmp>/studies/quillnote-fixture, ready for crp ingest."""
    d = tmp_path / "studies" / FIXTURE_STUDY.name
    shutil.copytree(FIXTURE_STUDY, d)
    (d / "posts.jsonl").unlink()
    return d


@pytest.fixture
def no_ocr(monkeypatch):
    """Make runs the same whether or not Tesseract is installed."""
    monkeypatch.setattr("crp.verify.ocr_text", lambda path: None)


def run_reference(script: str, *args) -> None:
    subprocess.run([sys.executable, str(REFERENCE / script), *map(str, args)], check=True, capture_output=True)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


@pytest.fixture
def batched(study, no_ocr):
    """The fixture study up to crp batch. Its thread cap is loosened to 30%, as it has only 4 threads (D22)."""
    from crp.anonymise import anonymise
    from crp.batch import make_batches
    from crp.codebook import freeze
    from crp.ingest import ingest
    from crp.sample import sample
    from crp.signals import signals
    from crp.verify import verify
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    sample(study, seed=11, thread_cap_pct=30)
    freeze(study)
    make_batches(study)
    return study


def dummy_values(sample: str, n: int) -> dict:
    """Fixed, varied codes chosen by an item's position: test data, not coding."""
    if sample == "measurement":
        aspects = {["sync", "search", "pricing"][n % 3]: [-1, 1][n % 2]} if n % 4 else {}
        return {"overall": [-2, -1, 0, 1, 2][n % 5], "aspect_scores": aspects}
    friction = n % 3 != 0
    return {"jtbd_force": ["push", "pull", "anxiety", "habit", "none"][n % 5],
            "evidence_type": ["opinion", "habitual", "specific_incident"][n % 3], "friction": friction,
            "severity": [1, 2, 3][n % 3] if friction else None, "aspect": ["sync", "search", "not_applicable"][n % 3]}


def write_labels(d: Path, values=dummy_values) -> dict:
    index = json.loads((d / "batches" / "index.json").read_text())
    (d / "labels").mkdir(exist_ok=True)
    for b in index["batches"]:
        rows = [{"item_id": it["item_id"], "values": values(b["sample"], n)} for n, it in enumerate(b["items"])]
        (d / "labels" / f"{b['batch']}.labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return index
