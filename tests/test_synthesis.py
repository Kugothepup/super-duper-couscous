"""The synthesis layer: checks on what the AI writes, the counts, hypothesis scoring and the viewer."""
import json

import pytest

from conftest import write_labels, write_synthesis
from crp import synthesis
from crp.analyse import analyse
from crp.codebook import frozen
from crp.hypotheses import proportion, score
from crp.io import InputError, read_jsonl
from crp.labels import lock, unseal
from crp.schemas import Hypothesis, Post
from crp.stats import Engine, Record
from crp.view import kwic, view_detail, view_posts, view_thread


def next_step():
    return {"method": "interviews", "confirm": "they name it first", "disconfirm": "they never name it"}


@pytest.fixture
def locked(batched):
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    return batched


def check(d):
    codebook, _ = frozen(d)
    return synthesis.check(d, codebook, read_jsonl(d / "posts.jsonl", Post))


def edit_obs(d, change):
    rows = [json.loads(line) for line in (d / "synthesis" / "observations.jsonl").read_text().splitlines()]
    change(rows)
    (d / "synthesis" / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


# ---- checks ------------------------------------------------------------------

def test_placeholder_synthesis_passes(locked):
    write_synthesis(locked)
    rep = check(locked)
    assert rep["ok"], rep["errors"]
    assert rep["counts"] == {"observations": 14, "insights": 1, "jobs": 1, "opportunities": 1, "hypotheses": 0}


@pytest.mark.parametrize("change, message", [
    (lambda r: r[0].update(quote=r[0]["quote"].lower()), "the quote isn't verbatim (tidied)"),
    (lambda r: r[0].update(quote="something nobody wrote in this thread"), "the quote isn't verbatim (failed)"),
    (lambda r: r.append(dict(r[0])), "a post gets one observation (D31)"),
    (lambda r: r.append(dict(r[0], post_id="T02-p12")), "not in the detail selection"),
])
def test_bad_observations_are_errors(locked, change, message):
    write_synthesis(locked)
    edit_obs(locked, change)
    rep = check(locked)
    assert not rep["ok"] and any(message in e for e in rep["errors"]), rep["errors"]


def test_quotes_may_skip_words_with_an_ellipsis(locked):
    write_synthesis(locked)
    posts = {p.post_id: p for p in read_jsonl(locked / "posts.jsonl", Post)}

    def elide(rows):
        words = posts[rows[0]["post_id"]].text.split()
        rows[0]["quote"] = " ".join(words[:3]) + " ... " + " ".join(words[5:8])
    edit_obs(locked, elide)
    assert check(locked)["ok"]


def test_observation_warnings(locked):
    write_synthesis(locked)
    edit_obs(locked, lambda r: r[1].update(observation=r[1]["quote"], quote=" ".join(r[1]["quote"].split()[:2])))
    warnings = check(locked)["warnings"]
    assert any("very short quote" in w for w in warnings)


def test_insight_job_and_opportunity_checks(locked):
    ids = write_synthesis(locked)
    (locked / "synthesis" / "insights.json").write_text(json.dumps({"insights": [
        {"id": "I01", "statement": "s", "post_ids": ids[:1], "confidence": "high"},
        {"id": "I02", "statement": "s", "post_ids": ["T01-p99"], "confidence": "low"}]}))
    (locked / "synthesis" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "J1", "job": "Find notes", "post_ids": ids[:1]}]}))
    (locked / "synthesis" / "opportunities.json").write_text(json.dumps({"opportunities": [
        {"id": "OP1", "statement": "s", "kind": "fix a pain", "aspect": "speed", "insight_ids": ["I09"], "post_ids": ids[:2]}]}))
    rep = check(locked)
    assert "insight I02: cites posts with no observation: ['T01-p99']" in rep["errors"]
    assert "opportunity OP1: unknown insight ids ['I09']" in rep["errors"]
    joined = "\n".join(rep["warnings"])
    for w in ("insight I01: supported by one person", "insight I01: 'high' but", "insight I01: no counter-evidence",
              "job J1: write it as 'When", "job J1: evidence covers fewer than two forces",
              "opportunity OP1: aspect 'speed' isn't in the codebook"):
        assert w in joined, w


def test_stated_hypotheses_need_the_prior_unsealed(locked):
    ids = write_synthesis(locked, [{"id": "H1", "origin": "stated", "statement": "s", "importance": "high",
                                    "signals": [{"id": "H1a", "text": "t", "for": []}], "next_step": next_step()}])
    rep = check(locked)
    assert any("still sealed" in e for e in rep["errors"])
    assert any("No hypotheses formed from the data" in w for w in rep["warnings"])
    (locked / "sealed").mkdir(exist_ok=True)
    (locked / "sealed" / "prior.md").write_text("Test prior, written by the test.\n")
    unseal(locked)
    assert check(locked)["ok"] and ids


def test_hypothesis_signal_checks(locked):
    ids = write_synthesis(locked)
    (locked / "synthesis" / "hypotheses.json").write_text(json.dumps({"hypotheses": [
        {"id": "H1", "origin": "formed", "statement": "s", "importance": "high", "signals": [
            {"id": "a", "text": "t", "test": {"type": "proportion", "k_ids": ids[:3], "n_ids": ids[1:5]}},
            {"id": "b", "text": "t", "test": {"type": "top_driver", "aspect": "speed"}}], "next_step": next_step()}]}))
    errors = check(locked)["errors"]
    assert "hypothesis H1/a: every k_id must also be in n_ids" in errors
    assert "hypothesis H1/b: aspect 'speed' isn't in the codebook" in errors


# ---- counts ------------------------------------------------------------------

def test_counts_known_answer(locked):
    ids = write_synthesis(locked)
    rep = check(locked)
    codebook, _ = frozen(locked)
    out = synthesis.summarise(rep, {"sync": 40.0}, codebook)
    nuggets = rep["nuggets"]
    friction = [n for n in nuggets.values() if n.codes.get("friction") is True]
    assert sum(g["n"] for g in out["pains"]) == len(friction)
    for g in out["pains"]:
        sev = [nuggets[i].codes["severity"] for i in g["post_ids"]]
        assert (g["max_sev"], g["mean_sev"]) == (max(sev), round(sum(sev) / len(sev), 1))
        assert g["voices"] == len({nuggets[i].person for i in g["post_ids"]})
    ranks = [(g["voices"] * g["max_sev"], g["n"]) for g in out["pains"]]
    assert ranks == sorted(ranks, reverse=True)
    [opp] = out["opportunities"]
    assert opp["negative_rate_pct"] == 40.0 and opp["rank_score"] == round(opp["voices"] * (1 + opp["mean_sev"]), 2)
    [ins] = out["insights"]
    assert (ins["n"], ins["counter_n"]) == (6, 1)
    [job] = out["jobs"]
    assert sum(job["forces"].values()) == sum(nuggets[i].codes["jtbd_force"] != "none" for i in ids[:8])
    [paper] = out["products"]
    assert paper["name"] == "paper" and paper["n"] == 4  # observations 0, 4, 8 and 12 are tagged product:paper
    assert sum(q["n"] for q in out["questions"]) == 3  # 0, 5 and 10 are tagged question


# ---- hypothesis scoring ------------------------------------------------------

def hyp(signals, origin="formed", importance="high"):
    return Hypothesis.model_validate({"id": "H1", "origin": origin, "statement": "s", "importance": importance,
                                      "signals": signals, "next_step": next_step()})


class FakeNugget:
    def __init__(self, person):
        self.person = person


def test_voices_lean_strength_and_priority_rules():
    nuggets = {f"p{i}": FakeNugget(f"P{i}") for i in range(20)}
    for_ids, against = [f"p{i}" for i in range(4)], ["p10"]
    out = score([hyp([{"id": "a", "text": "t", "for": for_ids, "against": against}])], nuggets, None, 150, 96, 100, 1)
    [h] = out["hypotheses"]
    assert h["signals"][0] == {"id": "a", "kind": "voices", "voices_for": 4, "voices_against": 1, "lean": "for"}
    assert (h["lean"], h["voices"], h["strength"], h["priority"]) == ("leans for", 5, "moderate", "test first")
    stated = score([hyp([{"id": "a", "text": "t", "for": for_ids, "against": against}], origin="stated")],
                   nuggets, None, 150, 96, 100, 1)
    assert stated["hypotheses"][0]["priority"] == "build on it, keep checking"
    assert "Only your own hypotheses" in stated["warnings"][0]
    parked = score([hyp([{"id": "a", "text": "t", "for": for_ids}], importance="low")], nuggets, None, 150, 96, 100, 1)
    assert parked["hypotheses"][0]["priority"] == "park for now"
    small = score([hyp([{"id": "a", "text": "t", "for": for_ids}])], nuggets, None, 40, 30, 100, 1)
    assert small["hypotheses"][0]["strength"] == "weak"  # a sample under 60 comments
    mixed = score([hyp([{"id": "a", "text": "t", "for": for_ids}, {"id": "b", "text": "t", "against": for_ids}])],
                  nuggets, None, 150, 96, 100, 1)
    assert mixed["hypotheses"][0]["lean"] == "mixed"
    two_one = score([hyp([{"id": "a", "text": "t", "for": for_ids[:2], "against": for_ids[2:3]}])],
                    nuggets, None, 150, 96, 100, 1)
    assert two_one["hypotheses"][0]["lean"] == "leans for"  # 2 people, and at least twice the other side
    tie = score([hyp([{"id": "a", "text": "t", "for": for_ids[:2], "against": for_ids[2:4]}])], nuggets, None, 150, 96, 100, 1)
    assert tie["hypotheses"][0]["lean"] == "can't tell from this data"


def test_proportion_is_a_count_below_20_people_and_ranged_above():
    small = proportion({"P1", "P2"}, {f"P{i}" for i in range(10)}, 10, 200, 1)
    assert small["status"] == "counts-only" and (small["k"], small["n"]) == (2, 10) and "range" not in small
    big = proportion({f"P{i}" for i in range(18)}, {f"P{i}" for i in range(24)}, 24, 500, 1)
    assert (big["k"], big["n"], big["pct"]) == (18, 24, 75.0) and big["range"][0] < 75.0 < big["range"][1]
    assert big["range_from"] == "people"


def test_probability_signals_use_both_resamplings_and_show_the_less_certain():
    records = [Record(post_id=f"r{i}", person=f"P{i:02d}", thread=f"T{i % 6}", source="s", search_term=None,
                      time=None, overall=-1, aspects={"sync": -1} if i % 3 else {"search": -1}) for i in range(30)]
    eng = Engine(records, draws=400, seed=2)
    out = score([hyp([{"id": "a", "text": "t", "test": {"type": "top_driver", "aspect": "sync"}},
                      {"id": "b", "text": "t", "test": {"type": "greater", "a": "sync", "b": "search"}},
                      {"id": "c", "text": "t", "test": {"type": "above", "aspect": "search", "measure": "mention_rate",
                                                        "threshold": 90}}])], {}, eng, 30, 30, 400, 2)
    a, b, c = out["hypotheses"][0]["signals"]
    # Resampling people, sync (20 of 30 negative mentions) nearly always wins. But all the search comments sit in
    # 2 of the 6 threads, so resampling threads, sync wins only when 4+ of the 6 drawn threads are sync threads.
    # That figure is nearer 50%, so it's the one shown (D29), and the signal is unclear.
    for sg in (a, b):
        p = sg["probability"]
        assert p["pct_people"] > 90 and p["source"] == "threads" and 50 < p["pct"] < 80 and sg["lean"] == "unclear"
    assert c["probability"]["pct"] == 0.0 and c["lean"] == "against"  # search is mentioned in a third of comments
    none = score([hyp([{"id": "a", "text": "t", "test": {"type": "top_driver", "aspect": "sync"}}])],
                 {}, Engine(records[:15], draws=100, seed=2), 15, 15, 100, 2)
    assert "too few people" in none["hypotheses"][0]["signals"][0]["note"]
    missing = score([hyp([{"id": "a", "text": "t", "test": {"type": "top_driver", "aspect": "pricing"}}])],
                    {}, eng, 30, 30, 100, 2)
    assert missing["errors"] == ["H1/a: ['pricing'] isn't mentioned in the measurement sample"]


# ---- viewer ------------------------------------------------------------------

def test_viewer(locked):
    lines = view_thread(locked, "T03", 1, 3)
    assert lines[0].startswith("# T03") and lines[1].startswith("[p01] POST P-") and len(lines) == 4
    assert "hit(s) in" in kwic(locked, "sync")[-1]
    assert view_detail(locked)[0].startswith("The detail selection has 72 posts in 2 batch(es)")
    assert view_detail(locked, 2)[0] == "## Detail batch 2/2 (32 posts)"
    assert any("T01-p02"[4:] in line for line in view_posts(locked, ["T01-p02"]))
    with pytest.raises(InputError, match="No such post"):
        view_posts(locked, ["T09-p01"])


# ---- analyse with a synthesis ------------------------------------------------

def test_analyse_counts_the_synthesis_and_refuses_errors(locked):
    ids = write_synthesis(locked, [{"id": "H1", "origin": "formed", "statement": "s", "importance": "high", "signals": [
        {"id": "a", "text": "t", "test": {"type": "top_driver", "aspect": "sync"}},
        {"id": "b", "text": "t", "for": ids_for(locked)}], "next_step": next_step()}])
    out = analyse(locked, seed=3, draws=300)["results"]
    assert out.synthesis.observations == 14 and out.synthesis.insights[0].n == 6 and len(out.hypotheses) == 1
    assert out.language.signal_rates["switching_language"].n > 0
    first = (locked / "results" / "results.json").read_bytes()
    analyse(locked, seed=3, draws=300)
    assert (locked / "results" / "results.json").read_bytes() == first
    edit_obs(locked, lambda r: r[0].update(quote="words nobody wrote"))
    with pytest.raises(InputError, match="The synthesis has 1 error"):
        analyse(locked, seed=3, draws=300)
    assert ids


def ids_for(d):
    detail = [json.loads(line) for line in (d / "samples" / "detail.jsonl").read_text().splitlines()]
    return [i["post_id"] for i in detail if i["source_type"] == "forum"][:4]
