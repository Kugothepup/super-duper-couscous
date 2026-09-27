"""Ported code against the skill's own scripts on the same inputs (D7).

Wherever DECISIONS.md hasn't changed the method, crp must give the same result as the scripts
in tests/reference/. Known, recorded differences: thread numbering across source types, and
names kept until crp anonymise. The measurement sample's caps are new (D2, D9), so only its
frame is compared.
"""
import json
import shutil
from collections import defaultdict

import pytest

from conftest import FIXTURE_SECRETS, read_jsonl, run_reference
from crp.anonymise import anonymise
from crp.ingest import ingest
from crp.sample import ids_hash, sample
from crp.signals import signals
from crp.verify import verify


@pytest.fixture
def ours(study, no_ocr):
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    posts = read_jsonl(study / "posts.jsonl")
    sig = {r["post_id"]: r for r in read_jsonl(study / "signals.jsonl")}
    return study, posts, sig


def reference_threads(work):
    manifest = json.loads((work / "manifest.json").read_text())
    return [json.loads((work / "turns" / f"{m['transcript_id']}.json").read_text()) for m in manifest]


def same_partition(ref_ids, our_ids):
    """Two labellings name the same people if they map one-to-one."""
    pairs = set(zip(ref_ids, our_ids))
    return len(pairs) == len(set(ref_ids)) == len(set(our_ids))


def compare_thread(ref_doc, our_rows):
    ref = ref_doc["turns"]
    assert [t["text"] for t in ref] == [r["text"] for r in our_rows]
    assert [t.get("kind", "turn") for t in ref] == [r["kind"] for r in our_rows]
    assert [t["role"] for t in ref] == [r["role"] for r in our_rows]
    idx = {r["post_id"]: i + 1 for i, r in enumerate(our_rows)}
    assert [t.get("parent_turn") for t in ref] == [idx.get(r["parent_id"]) for r in our_rows]
    assert [t.get("score") or 0 for t in ref] == [r["score"] or 0 for r in our_rows]


def test_reddit_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", study / "raw" / "reddit", "--work", work)
    ref = reference_threads(work)
    for ref_doc, tid in zip(ref, ("T02", "T03")):
        rows = [p for p in posts if p["thread_id"] == tid]
        compare_thread(ref_doc, rows)
        assert [t["created"] for t in ref_doc["turns"]] == \
            [r["timestamp"].replace("T", " ")[:16] for r in rows]
    ref_people = [t["author_id"] for d in ref for t in d["turns"]]
    our_people = [p["person_code"] for p in posts if p["thread_id"] in ("T02", "T03")]
    assert same_partition(ref_people, our_people)


def test_forum_capture_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    shutil.copytree(study / "raw" / "capture", work / "capture")
    run_reference("parse_forum.py", "--work", work, "--sources", study / "raw")
    ref = {d["source_file"]: d for d in reference_threads(work)}
    for source, tid in (("pro_price.txt", "T01"), ("love.png", "T04")):
        rows = [p for p in posts if p["thread_id"] == tid]
        compare_thread(ref[source], rows)
        assert [t["promotional"] for t in ref[source]["turns"]] == [r["promotional"] for r in rows]
        assert [t["date_approx"] for t in ref[source]["turns"]] == [r["date_approx"] for r in rows]


def test_interview_parsing_matches(ours, tmp_path):
    study, posts, _ = ours
    work = tmp_path / "ref"
    run_reference("parse_transcripts.py", study / "raw" / "interviews", "--work", work)
    [ref_doc] = reference_threads(work)
    compare_thread(ref_doc, [p for p in posts if p["thread_id"] == "I01"])


def signal_rows(work):
    out = []
    for m in json.loads((work / "manifest.json").read_text()):
        out += json.loads((work / "signals" / f"{m['transcript_id']}.json").read_text())["turns"]
    return out


KEYS = ("words", "counts", "density", "response_gap_s", "flags")


def test_forum_signals_match(ours, tmp_path):
    study, posts, sig = ours
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", study / "raw" / "reddit", "--work", work)
    run_reference("signals.py", "--work", work)
    ref = signal_rows(work)
    mine = [sig[p["post_id"]] for p in posts if p["thread_id"] in ("T02", "T03") and p["role"] == "participant"]
    assert len(ref) == len(mine)
    for r, m in zip(ref, mine):
        assert {k: r[k] for k in KEYS + ("score", "n_replies", "echo_agree", "echo_disagree")} == \
            {k: m[k] for k in KEYS + ("score", "n_replies", "echo_agree", "echo_disagree")}
    assert any("high_engagement" in m["flags"] for m in mine)


def test_interview_signals_match_with_response_gaps(tmp_path, no_ocr):
    interviews = tmp_path / "study" / "raw" / "interviews"
    interviews.mkdir(parents=True)
    cues = [("Moderator", "How do you find old notes?", 1.0, 4.0),
            ("Kim", "Um, I, I mostly search, I guess, but, uh, it kind of depends, you know, on the project.", 7.5, 14.0),
            ("Moderator", "What happens when search fails?", 15.0, 17.0),
            ("Kim", "I had to scroll through backlinks, and I wish there was a way to filter by date.", 17.4, 23.0),
            ("Moderator", "Anything else?", 24.0, 25.0),
            ("Kim", "I switched to paper for my thesis references, honestly.", 28.0, 31.0)]
    body = "WEBVTT\n\n" + "".join(
        f"00:00:{s:06.3f} --> 00:00:{e:06.3f}\n<v {who}>{text}\n\n" for who, text, s, e in cues)
    (interviews / "call.vtt").write_text(body, encoding="utf-8")
    work = tmp_path / "ref"
    run_reference("parse_transcripts.py", interviews, "--work", work)
    run_reference("signals.py", "--work", work)
    study = tmp_path / "study"
    ingest(study)
    verify(study)
    anonymise(study, FIXTURE_SECRETS)
    signals(study)
    ref, mine = signal_rows(work), read_jsonl(study / "signals.jsonl")
    assert [{k: r[k] for k in KEYS} for r in ref] == [{k: m[k] for k in KEYS} for m in mine]
    assert any("long_response_gap" in m["flags"] for m in mine)


# ---- sampling (triage.py) ----------------------------------------------------

def ref_post_ids(work, posts):
    """The skill's "T01#5" refs as crp post ids, matching each thread by its texts."""
    ours = defaultdict(list)
    for p in posts:
        ours[p["thread_id"]].append(p)
    out = {}
    for doc in reference_threads(work):
        texts = [t["text"] for t in doc["turns"]]
        [tid] = [t for t, ps in ours.items() if [p["text"] for p in ps] == texts]
        out.update({f"{doc['transcript_id']}#{t['turn_id']}": ours[tid][i]["post_id"]
                    for i, t in enumerate(doc["turns"])})
    return out


def crp_study(tmp_path, study, *parts):
    d = tmp_path / "ours"
    for part in parts:
        src = study / "raw" / part
        (shutil.copytree if src.is_dir() else shutil.copy)(src, d / "raw" / part)
    ingest(d)
    verify(d)
    anonymise(d, FIXTURE_SECRETS)
    signals(d)
    return d


def compare_sampling(d, work, **kw):
    ref = json.loads((work / "triage.json").read_text())
    summary = sample(d, seed=7, thread_cap_pct=100, **kw)
    posts = read_jsonl(d / "posts.jsonl")
    ids = ref_post_ids(work, posts)
    ours = {r["post_id"]: r["reasons"] for r in read_jsonl(d / "samples" / "detail.jsonl")}
    assert ours == {ids[k]: v for k, v in ref["reasons"].items()}
    forum = summary["detail"]["forum"]
    assert forum["clusters"] == ref["clusters"]
    assert forum["candidates"] == ref["n_candidates"] and forum["selected"] == ref["n_selected"]
    # the skill's random sample took the whole pool (under 150), so it is the frame before caps
    frame = summary["measurement"]["frame"]
    assert ref["sentiment_population"] == frame["eligible"] == len(ref["sentiment_sample"])
    order = {p["post_id"]: i for i, p in enumerate(posts)}
    assert ids_hash(sorted((ids[r] for r in ref["sentiment_sample"]), key=order.get)) == frame["eligible_sha256"]
    assert frame["left_out"].get("echo_reply", 0) == ref["n_echo_replies"]
    return ref, summary


def test_detail_selection_matches_triage_over_budget(study, no_ocr, tmp_path):
    d = crp_study(tmp_path, study, "reddit")
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", d / "raw" / "reddit", "--work", work)
    run_reference("signals.py", "--work", work)
    run_reference("triage.py", "--work", work, "--budget", 20, "--per-author", 2)
    ref, summary = compare_sampling(d, work, budget=20, per_person=2)
    firsts = {r[0].split(":")[0] for r in ref["reasons"].values()}
    assert firsts == {"post", "top_score", "flag", "cluster"}  # every stage of the selection ran
    assert ref["n_echo_replies"] == 1


def test_frame_matches_triage_on_captures(study, no_ocr, tmp_path):
    d = crp_study(tmp_path, study, "capture", "pro_price.txt", "love.png")
    work = tmp_path / "ref"
    shutil.copytree(study / "raw" / "capture", work / "capture")
    run_reference("parse_forum.py", "--work", work, "--sources", study / "raw")
    run_reference("signals.py", "--work", work)
    run_reference("triage.py", "--work", work)
    ref, summary = compare_sampling(d, work)
    assert set(map(tuple, ref["reasons"].values())) == {("all",)}
    assert summary["measurement"]["frame"]["left_out"] == {"promotional": 1}


# ---- statistics (drivers.py, language.py) -------------------------------------

def dummy_codes(n: int) -> dict:
    """Fixed, varied codes by position: test data, not coding."""
    aspects = {} if n % 5 == 0 else {["sync", "search", "pricing", "offline"][n % 4]: [-1, 1, -2][n % 3]}
    if n % 7 == 3:
        aspects["templates"] = 2
    return {"overall": [-2, -1, -1, 0, 1, 2][n % 6], "aspects": aspects, "stance": [-2, None, 1, 0, 2][n % 5]}


@pytest.fixture
def same_sample(study, no_ocr, tmp_path):
    """The Reddit threads' measurement sample, coded the same way for crp and for drivers.py."""
    import datetime as dt
    from crp.stats import Record
    d = crp_study(tmp_path, study, "reddit")
    sample(d, seed=7, thread_cap_pct=100)
    work = tmp_path / "ref"
    run_reference("parse_reddit.py", d / "raw" / "reddit", "--work", work)
    run_reference("signals.py", "--work", work)
    posts = {p["post_id"]: p for p in read_jsonl(d / "posts.jsonl")}
    ref_of = {pid: ref for ref, pid in ref_post_ids(work, list(posts.values())).items()}
    measured = [r["post_id"] for r in read_jsonl(d / "samples" / "measurement.jsonl")]
    codes = {pid: dummy_codes(n) for n, pid in enumerate(measured)}
    (work / "sentiment").mkdir()
    (work / "sentiment" / "batch1.json").write_text(json.dumps([{"ref": ref_of[p], **codes[p]} for p in measured]))
    (work / "study.json").write_text(json.dumps({"type": "news", "stance_target": "x", "event_date": "2026-06-09"}))
    records = [Record(post_id=p, person=posts[p]["person_code"], thread=posts[p]["thread_id"], source=posts[p]["source"],
                      search_term=posts[p]["search_term"], time=dt.datetime.fromisoformat(posts[p]["timestamp"]),
                      overall=codes[p]["overall"], aspects=codes[p]["aspects"], stance=codes[p]["stance"])
               for p in measured]
    return work, records, posts


def pct_of(share: dict) -> float:
    """drivers.py's pct(), from the share's own k and n (so counts are compared even where D11 hides the %)."""
    return round(100 * share["k"] / share["n"], 1) if share["n"] else 0.0


def test_statistics_match_drivers_py(same_sample):
    from crp import stats
    work, records, _ = same_sample
    run_reference("drivers.py", "--work", work, "--boot", 2000, "--seed", 11)
    ref = json.loads((work / "drivers.json").read_text())
    eng = stats.Engine(records, draws=2000, seed=11)  # the skill's re-draws and seed, to compare like with like
    h = stats.headline(eng)
    o = ref["overall"]
    assert (o["n_comments"], o["n_authors"]) == (h["negative"]["n"], h["people_net_negative"]["n"]) and o["n_authors"] >= 20
    assert [o[k] for k in ("negative_pct", "neutral_pct", "positive_pct", "mean", "authors_net_negative_pct")] == \
        [h["negative"]["pct"], h["neutral"]["pct"], h["positive"]["pct"], h["mean"], h["people_net_negative"]["pct"]]
    # the same re-draws, resampling people, give the same ranges
    assert o["negative_ci_boot"] == list(h["negative"]["range_people"])
    assert o["positive_ci_boot"] == list(h["positive"]["range_people"])
    a = stats.aspects(eng, rule="skill")  # drivers.py's top-driver rule; D12's is tested in test_stats.py
    ours = {x["aspect"]: x for x in a["aspects"]}
    assert set(ours) == {x["aspect"] for x in ref["all_aspects"]}
    for x in ref["all_aspects"]:
        y = ours[x["aspect"]]
        assert (x["mentions"], x["authors"], x["mean"], x["strong_negative"]) == \
            (y["mentions"], y["people"], y["mean"], y["strong_negative"])
        assert (x["negative_rate_pct"], x["share_of_negative_pct"], x["share_of_positive_pct"], x["mention_rate_pct"]) == \
            (pct_of(y["negative_rate"]), pct_of(y["share_of_negative"]), pct_of(y["share_of_positive"]),
             pct_of(y["mention_rate"]))
        assert x["share_of_negative_ci"] == list(y["share_of_negative"]["range_people"])
        assert x["top_driver_prob"] == y["top_driver"]["pct_people"]
    assert [x["aspect"] for x in ref["drivers"]] == a["drivers"]
    assert [x["aspect"] for x in ref["strengths"]] == a["strengths"] and ref["rare_aspects"] == a["rare"]
    st, rs = stats.stance(eng, "x"), ref["stance"]
    assert (rs["n_expressing"], rs["expressing_pct"], rs["for_pct"], rs["against_pct"], rs["neutral_pct"]) == \
        (st["in_favour"]["n"], pct_of(st["expressing"]), pct_of(st["in_favour"]), pct_of(st["against"]), pct_of(st["neither"]))
    assert rs["for_talks_about"] == {k: pct_of(v) for k, v in st["talks_about"]["in_favour"].items()}
    assert rs["against_talks_about"] == {k: pct_of(v) for k, v in st["talks_about"]["against"].items()}
    ev = stats.event(eng, dt_date("2026-06-09"))
    for x, y in zip(ref["event"]["measures"], ev["measures"]):
        assert (x["n_before"], x["n_after"], x["before_pct"], x["after_pct"]) == \
            (y["before"]["n"], y["after"]["n"], pct_of(y["before"]), pct_of(y["after"]))
        assert x["diff_pts"] == round(pct_of(y["after"]) - pct_of(y["before"]), 1)
    rows, _ = stats.by_source(eng)
    assert [(x["n"], x["share_pct"], x["negative_pct"]) for x in ref["by_source"]] == \
        [(y["share_of_sample"]["k"], pct_of(y["share_of_sample"]), pct_of(y["negative"])) for y in rows]
    dr, rd = stats.direction(eng, []), ref["direction"]
    assert (rd["status"], rd.get("unit"), rd.get("span_days")) == (dr["status"], dr.get("unit"), dr.get("span_days"))
    assert [(p["period"], p["n"], p["negative_pct"], p["top_aspects"]) for p in rd.get("periods", [])] == \
        [(p["period"], p["negative"]["n"], pct_of(p["negative"]), {k: pct_of(v) for k, v in p["top_aspects"].items()})
         for p in dr.get("periods", [])]
    assert rd.get("usable_periods", []) == dr.get("usable_periods", [])


def dt_date(s: str):
    import datetime as dt
    return dt.date.fromisoformat(s)


def test_keyness_matches_language_py_under_the_skills_rules(same_sample):
    from crp.keyness import keyness
    work, records, posts = same_sample
    run_reference("language.py", "--work", work)
    ref = json.loads((work / "language.json").read_text())["keyness"]
    ours = keyness([(posts[r.post_id]["text"], r.person, r.overall) for r in records], rule="skill")
    keys = ("term", "freq", "other_freq", "reach", "g2", "log_ratio")
    for side in ("negative", "positive"):
        assert [{k: t[k] for k in keys} for t in ref[side]] == [{k: t[k] for k in keys} for t in ours[side]]
    b = ref["basis"]
    assert (b["negative_docs"], b["positive_docs"], b["negative_words"], b["positive_words"]) == \
        tuple(ours["basis"][k] for k in ("negative_items", "positive_items", "negative_words", "positive_words"))
    assert ref["negative"] or ref["positive"]  # something was compared
