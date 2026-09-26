import json

import pytest

from crp.io import InputError, read_csv, read_jsonl, validate
from crp.schemas import (COLLECTION_LOG_COLUMNS, Codebook, CollectionLogRow, Label, Measure, Post, Study)

HEADER = ",".join(COLLECTION_LOG_COLUMNS)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ---- the "bad row is rejected with a clear message" checks --------------------

def test_bad_collection_log_row_names_file_line_and_field(tmp_path):
    p = write(tmp_path, "collection_log.csv", HEADER + "\n"
              "reddit.com/r/x,notion pricing,2026-09-20,pricing news,y,10,2,\n"
              "reddit.com/r/x,notion,2026-09-21,neutral search,maybe,5,1,\n")
    with pytest.raises(InputError) as err:
        read_csv(p, CollectionLogRow, COLLECTION_LOG_COLUMNS)
    assert str(err.value) == f"{p} line 3: neutral: must be y or n (got 'maybe')"


def test_missing_required_column_value_is_reported_as_missing(tmp_path):
    p = write(tmp_path, "collection_log.csv", HEADER + "\nreddit.com/r/x,,2026-09-20,why,n,,,\n")
    with pytest.raises(InputError, match=r"line 2: search_term: missing"):
        read_csv(p, CollectionLogRow, COLLECTION_LOG_COLUMNS)


def test_collection_log_header_must_match(tmp_path):
    p = write(tmp_path, "collection_log.csv", "source,query,date\nreddit,x,2026-09-20\n")
    with pytest.raises(InputError, match="the header must be source,search_term,date,reason,neutral"):
        read_csv(p, CollectionLogRow, COLLECTION_LOG_COLUMNS)


def test_kept_cannot_exceed_results_seen(tmp_path):
    p = write(tmp_path, "collection_log.csv", HEADER + "\nforum,x,2026-09-20,why,n,3,5,\n")
    with pytest.raises(InputError, match=r"kept \(5\) is more than results_seen \(3\)"):
        read_csv(p, CollectionLogRow, COLLECTION_LOG_COLUMNS)


def test_excel_byte_order_mark_is_tolerated(tmp_path):
    p = tmp_path / "collection_log.csv"
    p.write_text(HEADER + "\nforum,x,2026-09-20,why,Y,3,1,dupes\n", encoding="utf-8-sig")
    [row] = read_csv(p, CollectionLogRow, COLLECTION_LOG_COLUMNS)
    assert row.neutral is True and row.why_excluded == "dupes"


def test_bad_jsonl_line_names_the_line(tmp_path, good_post):
    bad = dict(good_post, person_code="maria_k")
    p = write(tmp_path, "posts.jsonl", json.dumps(good_post) + "\n" + json.dumps(bad) + "\n")
    with pytest.raises(InputError, match=r"posts.jsonl line 2: person_code: String should match pattern"):
        read_jsonl(p, Post)


def test_broken_json_is_reported(tmp_path, good_post):
    p = write(tmp_path, "posts.jsonl", json.dumps(good_post) + "\n{not json\n")
    with pytest.raises(InputError, match=r"posts.jsonl line 2: not valid JSON"):
        read_jsonl(p, Post)


# ---- posts --------------------------------------------------------------------

def test_good_post_validates(good_post):
    post = validate(Post, good_post, "post")
    assert post.role == "participant" and post.date_approx is False


def test_unknown_field_is_rejected(good_post):
    with pytest.raises(InputError, match="post: usernme: unknown field"):
        validate(Post, dict(good_post, usernme="maria_k"), "post")


@pytest.mark.parametrize("change, message", [
    ({"capture_method": "transcript"}, "captured by paste, screenshot or export"),
    ({"kind": "turn"}, "a 'post' or a 'comment'"),
    ({"role": "interviewer"}, "forum posts have no interviewer"),
    ({"source_type": "interview"}, "interview turns are captured by transcript"),
    ({"parent_id": "T1-p02"}, "can't reply to itself"),
    ({"kind": "post"}, "an opening post has no parent"),
    ({"timestamp": None, "date_approx": True}, "no timestamp"),
    ({"text": "   "}, "text is empty"),
])
def test_inconsistent_posts_are_rejected(good_post, change, message):
    with pytest.raises(InputError, match=message):
        validate(Post, dict(good_post, **change), "post")


def test_post_text_is_kept_verbatim(good_post):
    post = validate(Post, dict(good_post, text="  two spaces  "), "post")
    assert post.text == "  two spaces  "


# ---- study --------------------------------------------------------------------

def test_study_id_must_be_a_slug():
    with pytest.raises(InputError, match="id: String should match pattern"):
        validate(Study, {"id": "Notion Study", "subject": "Notion", "type": "product", "created": "2026-09-26"}, "s")


def test_study_window_must_run_forwards():
    with pytest.raises(InputError, match="window_end is before window_start"):
        validate(Study, {"id": "x", "subject": "X", "type": "product", "created": "2026-09-26",
                         "window_start": "2026-08-01", "window_end": "2026-03-01"}, "s")


def test_news_study_without_stance_target_is_flagged_not_rejected():
    s = validate(Study, {"id": "x", "subject": "X", "type": "news", "created": "2026-09-26"}, "s")
    assert s.needs_stance_target


# ---- codebook -----------------------------------------------------------------

def codebook(**changes):
    base = {"version": "1", "study_type": "product", "aspects": ["pricing", "search"],
            "variables": [{"name": "overall", "description": "evaluation of the subject",
                           "applies_to": "measurement", "level": "ordinal", "values": [-2, -1, 0, 1, 2],
                           "definitions": {-2: "strongly negative"}},
                          {"name": "friction", "description": "hit an obstacle", "applies_to": "detail",
                           "level": "nominal", "values": [True, False]},
                          {"name": "severity", "description": "how bad", "applies_to": "detail",
                           "level": "ordinal", "values": [1, 2, 3], "required_when": "friction"}]}
    base.update(changes)
    return base


def test_codebook_validates_and_reads_numeric_definition_keys():
    cb = validate(Codebook, codebook(), "codebook")
    assert cb.variable("overall").definitions == {"-2": "strongly negative"}


@pytest.mark.parametrize("change, message", [
    ({"aspects": ["pricing", "pricing"]}, "an aspect is listed twice"),
    ({"aspects": ["Too Expensive"]}, "aspects.0: String should match pattern"),
    ({"aspect_definitions": {"sync": "x"}}, "aspects not in the aspect list"),
])
def test_bad_codebooks_are_rejected(change, message):
    with pytest.raises(InputError, match=message):
        validate(Codebook, codebook(**change), "codebook")


def test_duplicate_variable_names_are_rejected():
    cb = codebook()
    cb["variables"].append(dict(cb["variables"][0]))
    with pytest.raises(InputError, match=r"variables named more than once: \['overall'\]"):
        validate(Codebook, cb, "codebook")


def test_required_when_must_name_a_true_false_variable():
    cb = codebook()
    cb["variables"][2]["required_when"] = "overall"
    with pytest.raises(InputError, match="which isn't true/false"):
        validate(Codebook, cb, "codebook")


def test_per_aspect_variable_needs_aspects():
    cb = codebook(aspects=[])
    cb["variables"].append({"name": "aspect_scores", "description": "per aspect", "applies_to": "measurement",
                            "kind": "per_aspect", "level": "ordinal", "values": [-2, -1, 0, 1, 2]})
    with pytest.raises(InputError, match="per aspect but the codebook lists no aspects"):
        validate(Codebook, cb, "codebook")


def test_definitions_must_be_for_listed_values():
    cb = codebook()
    cb["variables"][0]["definitions"] = {3: "off the scale"}
    with pytest.raises(InputError, match=r"defines values it doesn't list: \['3'\]"):
        validate(Codebook, cb, "codebook")


# ---- labels and results -------------------------------------------------------

def test_label_keeps_booleans_and_scores_apart():
    lab = validate(Label, {"item_id": "i1", "values": {"friction": True, "severity": 1,
                                                       "aspect_scores": {"pricing": -2}}}, "label")
    assert lab.values["friction"] is True and lab.values["severity"] == 1


def test_label_rationale_is_capped_at_15_words():
    with pytest.raises(InputError, match="15 words or fewer"):
        validate(Label, {"item_id": "i1", "values": {}, "rationale": " ".join(["word"] * 16)}, "label")


def test_measure_status_must_match_thresholds():
    with pytest.raises(InputError, match="status is 'full' but 12 people and 150 items make it 'counts-only'"):
        validate(Measure, {"name": "negative", "method": "m", "n_people": 12, "n_items": 150,
                           "status": "full", "share_pct": 60.0}, "measure")


def test_counts_only_measure_cannot_carry_ranges():
    with pytest.raises(InputError, match="counts-only results can't carry share_pct, range_pct"):
        validate(Measure, {"name": "negative", "method": "m", "n_people": 12, "n_items": 40,
                           "status": "counts-only", "k": 25, "share_pct": 62.5, "range_pct": [40, 80]}, "measure")


def test_early_signal_and_full_measures_validate():
    early = validate(Measure, {"name": "negative", "method": "m", "n_people": 25, "n_items": 40,
                               "status": "early-signal", "share_pct": 62.5, "range_pct": [45, 78]}, "m")
    full = validate(Measure, {"name": "negative", "method": "m", "n_people": 96, "n_items": 150,
                              "status": "full", "share_pct": 64.7, "range_pct": [56.8, 72.1]}, "m")
    assert early.status == "early-signal" and full.status == "full"
