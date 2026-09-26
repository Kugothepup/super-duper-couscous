from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_STUDY = FIXTURES / "quillnote-fixture"


@pytest.fixture
def good_post() -> dict:
    return {"post_id": "T1-p02", "source_type": "forum", "source": "reddit.com/r/notetaking", "thread_id": "T1",
            "parent_id": "T1-p01", "person_code": "P-0a1b2c3d", "kind": "comment",
            "timestamp": "2026-04-02T09:14:00", "score": 3, "text": "Search takes ten seconds now.",
            "capture_method": "export", "raw_ref": "thread.json#p02"}
