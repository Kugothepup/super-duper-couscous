import json

import pytest

from crp.anonymise import anonymise
from crp.cli import main
from crp.ingest import ingest
from crp.io import InputError
from crp.verify import check_ocr, check_quote, check_text, verify

SOURCE = ("maria_k  ·  2026-04-02\nWe cancelled the team plan in April. Nobody could justify the jump to "
          "the department, so half of us went back to the free tier.\nReply   Like 11\n")


# ---- the Phase 2 "Done when" checks: a tidied quote is caught, an invented one fails ----

def test_exact_text_passes():
    assert check_text("Nobody could justify the jump to the department", SOURCE) == {"status": "exact"}


def test_tidied_quote_is_caught_with_a_diff():
    res = check_text("We cancelled the team plan in April. Nobody could justify the price jump to the "
                     "department, so half of us went back to the free tier.", SOURCE)
    assert res["status"] == "tidied" and res["score"] >= 90
    assert "{+price+}" in res["diff"]


def test_invented_quote_fails():
    res = check_text("Everyone on our team is moving to Obsidian because Quillnote is too expensive.", SOURCE)
    assert res["status"] == "failed" and res["score"] < 90


def test_spacing_and_quote_marks_pass_with_a_note():
    res = check_text("half of us  went back", "so half of us\nwent back")
    assert res["status"] == "normalised" and "normalised" in res["note"]
    assert check_text("it's full", "once it’s full")["status"] == "normalised"


def test_case_change_counts_as_tidied():
    assert check_text("nobody could justify the jump", SOURCE)["status"] == "tidied"


def test_quotes_with_elisions_must_keep_their_order():
    assert check_quote("We cancelled the team plan ... went back to the free tier", SOURCE)["status"] == "exact"
    assert check_quote("went back to the free tier ... We cancelled the team plan", SOURCE)["status"] == "failed"
    assert check_quote("We cancelled the team plan … Nobody could justify the jump to the department, so half "
                       "of us went back to the paid tier", SOURCE)["status"] == "tidied"
    # a changed word in a short fragment falls below the fuzzy threshold: failed, not tidied
    assert check_quote("We cancelled the team plan ... went back to the paid tier", SOURCE)["status"] == "failed"


def test_ocr_overlap_rules():
    ocr = "Backlinks changed how I write. I find old ideas I had forgotten about."
    assert check_ocr("Backlinks changed how I write. I find old ideas I had forgotten about.", ocr)["status"] == "ocr_ok"
    flagged = check_ocr("Backlinks changed how I write. I find old ideas I had never written.", ocr)
    assert flagged["status"] == "ocr_flagged" and flagged["missing"] == ["never", "written"]
    assert check_ocr("Backlinks changed how I write [cut off]", ocr)["status"] == "ocr_ok"  # markers ignored (D19)


# ---- verify on the fixture ----------------------------------------------------

def test_fixture_verifies(study, no_ocr):
    ingest(study)
    rep = verify(study)
    assert rep["ok"] and rep["counts"] == {"exact": 9, "normalised": 1, "unverified": 7, "parsed": 61}
    report = json.loads((study / "results" / "verify_report.json").read_text())
    assert report["posts"]["T01-p05"] == "normalised"  # the page has a curly apostrophe


def test_fixture_screenshot_with_ocr(study, monkeypatch):
    page = json.loads((study / "raw" / "capture" / "love.json").read_text())
    # OCR misreads one word in one post (still fine) and two words in another (flagged for a human look)
    ocr = " ".join(p["text"] for p in page["posts"]).replace("clutter", "c1utter") \
        .replace("literature review", "1iterature rev1ew")
    monkeypatch.setattr("crp.verify.ocr_text", lambda path: ocr)
    ingest(study)
    rep = verify(study)
    assert rep["ok"] and rep["counts"]["ocr_ok"] == 6 and rep["counts"]["ocr_flagged"] == 1
    [flagged] = [d for d in rep["details"] if d["status"] == "ocr_flagged"]
    assert flagged["post_id"] == "T04-p02" and flagged["missing"] == ["literature", "review"]


def tidy_one_post(study):
    cap_path = study / "raw" / "capture" / "pro_price.json"
    cap = json.loads(cap_path.read_text())
    cap["posts"][2]["text"] = cap["posts"][2]["text"].replace("Nobody could justify", "Nobody could really justify")
    cap_path.write_text(json.dumps(cap))


def test_tidied_transcription_blocks_anonymise(study, no_ocr, capsys):
    tidy_one_post(study)
    assert main(["ingest", str(study)]) == 0
    assert main(["verify", str(study)]) == 1
    out = capsys.readouterr().out
    assert "TIDIED" in out and "{+really+}" in out
    with pytest.raises(InputError, match="0 failed and 1 tidied"):
        anonymise(study)
    assert not (study / "posts.jsonl").exists()


def test_diffs_stay_in_raw(study, no_ocr):
    tidy_one_post(study)
    ingest(study)
    verify(study)
    assert "really" in (study / "raw" / "verify_details.json").read_text()
    assert "really" not in (study / "results" / "verify_report.json").read_text()


def test_anonymise_needs_a_current_verify(study, no_ocr):
    ingest(study)
    with pytest.raises(InputError, match="Run crp verify first"):
        anonymise(study)
    verify(study)
    with (study / "raw" / "ingested.jsonl").open("a") as f:
        f.write("\n")
    with pytest.raises(InputError, match="has changed since crp verify ran"):
        anonymise(study)


def test_missing_source_file_fails(study, no_ocr):
    ingest(study)
    (study / "raw" / "pro_price.txt").unlink()
    rep = verify(study)
    assert not rep["ok"] and rep["counts"]["failed"] == 10
