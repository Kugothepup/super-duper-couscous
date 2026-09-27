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
