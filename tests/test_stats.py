"""Known-answer tests for the statistics: shares, resampling, top driver, comparisons, G2, BH, sensitivity."""
import datetime as dt
import json
import random

import numpy as np
import pytest
from scipy.stats import false_discovery_control

from conftest import write_labels
from crp import stats
from crp.analyse import analyse
from crp.io import InputError, validate
from crp.keyness import bh, g2, keyness, log_ratio
from crp.labels import lock
from crp.schemas import Results
from crp.sensitivity import cap_weights, leave_one_out, without_caps
from crp.stats import Boot, Engine, Record, nearer_half, pci, wider


def rec(i, person, overall, thread="T1", aspects=None, stance=None, time=None, source="s1", term=None):
    return Record(post_id=f"p{i:03d}", person=person, thread=thread, source=source, search_term=term, time=time,
                  overall=overall, aspects=aspects or {}, stance=stance)


def thirty_people():
    """30 people with 2 comments each, in 10 threads. People 0-11 post -1 and -2; people 12-17 post -1 and +1
    (mean 0); people 18-29 post 0 twice. So 30 of 60 comments are negative (50.0%), 6 positive (10.0%),
    24 neutral (40.0%), the mean is -36/60 = -0.6, and 12 of 30 people are net negative (40.0%)."""
    out = []
    for p in range(30):
        pair = (-1, -2) if p < 12 else (-1, 1) if p < 18 else (0, 0)
        out += [rec(len(out), f"P{p:02d}", s, thread=f"T{p % 10}") for s in pair]
    return out


# ---- shares and resampling ---------------------------------------------------

def test_headline_known_answer():
    h = stats.headline(Engine(thirty_people(), draws=200, seed=1))
    assert (h["negative"]["k"], h["negative"]["n"], h["negative"]["pct"]) == (30, 60, 50.0)
    assert h["positive"]["pct"] == 10.0 and h["neutral"]["pct"] == 40.0 and h["mean"] == -0.6
    assert (h["people_net_negative"]["k"], h["people_net_negative"]["n"], h["people_net_negative"]["pct"]) == (12, 30, 40.0)
    assert h["negative"]["status"] == "full" and h["negative"]["n_people"] == 30
    lo, hi = h["negative"]["range"]
    assert lo < 50.0 < hi and h["negative"]["range_from"] in ("people", "threads")


def test_below_20_people_is_counts_only():
    records = [r for r in thirty_people() if int(r.person[1:]) < 19]
    h = stats.headline(Engine(records, draws=100, seed=1))
    assert h["negative"] == {"k": 30, "n": 38, "n_people": 19, "n_items": 38, "status": "counts-only",
                             "method": "random sample, per comment; count only (fewer than 20 people)"}
    assert "mean" not in h
    for r in records[:4]:
        r.aspects = {"sync": -1}
    a = stats.aspects(Engine(records, draws=100, seed=1))
    assert a["aspects"][0].get("top_driver") is None and a["aspects"][0]["mean"] is None


def test_percentile_interval_is_the_skills():
    assert pci(range(1, 101)) == (3.0, 97.0)  # sorted index int(0.025 * 99) = 2 and int(0.975 * 99) = 96
    assert pci([float("nan")] * 3) is None


def test_bootstrap_draws_match_drivers_py():
    keys = ["a", "b", "a", "c"]
    boot = Boot(keys, draws=3, seed=5)
    rng = random.Random(5)
    for b in range(3):
        drawn = [rng.choice(["a", "b", "c"]) for _ in range(3)]
        assert list(boot.W[b]) == [drawn.count(k) for k in keys]


def test_wider_range_and_less_certain_probability():
    assert wider({"people": (40.0, 60.0), "threads": (35.0, 70.0)})["range_from"] == "threads"
    assert wider({"people": (40.0, 60.0), "threads": (45.0, 65.0)})["range_from"] == "people"  # a tie keeps people
    assert wider({"people": (40.0, 60.0), "threads": None})["range"] == (40.0, 60.0)
    assert nearer_half({"people": 91.0, "threads": 72.5}) == {"pct": 72.5, "source": "threads",
                                                              "pct_people": 91.0, "pct_threads": 72.5}
    assert nearer_half({"people": 10.0, "threads": 35.0})["source"] == "threads"


def test_one_thread_is_not_resampled():
    records = [rec(i, f"P{i}", -1 if i % 2 else 0) for i in range(30)]
    sh = stats.headline(Engine(records, draws=100, seed=1))["negative"]
    assert sh["range_threads"] is None if "range_threads" in sh else True
    assert sh["range_from"] == "people"


# ---- aspects and the top driver (D12) ----------------------------------------

def driver_records():
    """25 people. P00 alone posts 3 negative sync comments; 10 people praise search; P01 posts two negative
    'rare' comments (2 mentions, so not ranked)."""
    out = [rec(i, "P00", -1, aspects={"sync": -1}, thread=f"T{i}") for i in range(3)]
    out += [rec(3 + i, f"P{i + 2:02d}", 1, aspects={"search": 1}, thread=f"T{i % 5}") for i in range(10)]
    out += [rec(13 + i, "P01", -1, aspects={"rare": -2}, thread="T9") for i in range(2)]
    out += [rec(15 + i, f"P{i + 12:02d}", 0, thread=f"T{i % 4}") for i in range(13)]
    return out


def test_top_driver_d12_only_ranked_aspects_and_no_top_without_negatives():
    eng = Engine(driver_records(), draws=1000, seed=2)
    new = {a["aspect"]: a for a in stats.aspects(eng)["aspects"]}
    old = {a["aspect"]: a for a in stats.aspects(eng, rule="skill")["aspects"]}
    assert new["rare"]["ranked"] is False and "top_driver" not in new["rare"]
    assert new["search"]["top_driver"]["pct_people"] == 0.0  # never negative, so never the top driver
    # P00 is left out of some re-draws; then no ranked aspect has a negative mention, so there is no top driver
    assert 0 < new["sync"]["top_driver"]["pct_people"] < 100
    # the skill's rule still named a top driver in those re-draws, even though nothing was negative
    assert old["search"]["top_driver"]["pct_people"] > 0 or old["rare"]["top_driver"]["pct_people"] > 0
    assert stats.aspects(eng)["drivers"] == ["sync"] and stats.aspects(eng)["rare"] == ["rare"]


def test_aspect_counts_known_answer():
    a = {x["aspect"]: x for x in stats.aspects(Engine(driver_records(), draws=100, seed=1))["aspects"]}
    s = a["sync"]
    assert (s["mentions"], s["people"], s["mean"], s["strong_negative"]) == (3, 1, -1.0, 0)
    assert (s["share_of_negative"]["k"], s["share_of_negative"]["n"], s["share_of_negative"]["pct"]) == (3, 5, 60.0)
    assert s["negative_rate"]["status"] == "counts-only"  # it rests on 3 comments from 1 person
    assert (a["rare"]["strong_negative"], a["search"]["share_of_positive"]["pct"]) == (2, 100.0)
    assert a["search"]["mention_rate"]["pct"] == 35.7  # 10 of 28 comments


# ---- comparisons -------------------------------------------------------------

def test_before_after_rose_known_answer():
    day = dt.datetime(2026, 6, 1)
    records = [rec(i, f"P{i:02d}", 1, thread=f"T{i % 5}", time=day - dt.timedelta(days=1 + i)) for i in range(20)]
    records += [rec(20 + i, f"P{20 + i:02d}", -1, thread=f"T{i % 5}", time=day + dt.timedelta(days=i)) for i in range(20)]
    ev = stats.event(Engine(records, draws=500, seed=3), dt.date(2026, 6, 1))
    [neg] = ev["measures"]
    assert (neg["before"]["pct"], neg["after"]["pct"], neg["diff_pts"]) == (0.0, 100.0, 100.0)
    assert neg["verdict"] == "rose" and neg["range"][0] > 0


def test_a_side_under_20_people_gives_no_difference():
    day = dt.datetime(2026, 6, 1)
    records = [rec(i, f"P{i:02d}", 1, thread=f"T{i % 5}", time=day - dt.timedelta(days=1)) for i in range(10)]
    records += [rec(10 + i, f"P{10 + i:02d}", -1, thread=f"T{i % 5}", time=day) for i in range(20)]
    [neg] = stats.event(Engine(records, draws=200, seed=3), dt.date(2026, 6, 1))["measures"]
    assert neg["before"]["status"] == "counts-only"  # 10 people before: a count only (D11)
    assert neg["verdict"] == "insufficient data" and neg["diff_pts"] is None


# ---- G2, log ratio, Benjamini-Hochberg ---------------------------------------

def test_g2_and_log_ratio_known_answer():
    # a=10 in c=100 words against b=2 in d=100: expected 6 each side, so
    # G2 = 2(10 ln(10/6) + 2 ln(2/6)) = 2(5.108256 - 2.197225) = 5.822063; Log Ratio = log2(10/2) = 2.321928
    assert g2(10, 2, 100, 100) == pytest.approx(5.822063, abs=1e-6)
    assert log_ratio(10, 2, 100, 100) == pytest.approx(2.321928, abs=1e-6)
    assert g2(5, 5, 100, 100) == 0.0
    assert log_ratio(4, 0, 100, 100) == pytest.approx(3.0)  # a zero count is taken as 0.5: log2(4 / 0.5)


def test_benjamini_hochberg_known_answer():
    # sorted: 0.005, 0.01, 0.03, 0.04 (m = 4); step-up adjusted: 0.02, 0.02, 0.04, 0.04
    p = [0.01, 0.04, 0.03, 0.005]
    assert bh(p) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    rng = np.random.default_rng(0)
    many = list(rng.uniform(0, 0.2, 40))
    assert bh(many) == pytest.approx(list(false_discovery_control(many, method="bh")))


def test_keyness_filters_d6_against_the_skill():
    items = [(f"The sync keeps failing badly and sync failing again {i}", f"P{i}", -1) for i in range(8)]
    items += [(f"Lovely templates and quick search make daily planning easy {i}", f"Q{i}", 1) for i in range(8)]
    items += [("Offline mode crashes offline mode crashes offline mode crashes", "R1", -1)] * 3  # one person
    items += [("Export export export broken", "S1", -1), ("Export export export broken", "S2", -1)]  # two people
    new, old = keyness(items), keyness(items, rule="skill")
    kept = {t["term"]: t for t in new["negative"]}
    assert "sync" in kept and all(t["q"] <= 0.05 for t in new["negative"])
    assert "offline" not in kept and "export" not in kept  # D6: 3+ people
    assert "export" in {t["term"] for t in old["negative"]}  # the skill: 2+ people, 3+ uses
    assert new["basis"]["tested"] < old["basis"]["tested"]


# ---- sensitivity -------------------------------------------------------------

def test_leave_one_out_known_answer():
    records = [rec(i, f"A{i}", -1 if i < 10 else 0, source="A", thread=f"a{i % 4}") for i in range(20)]
    records += [rec(20 + i, f"B{i}", -1, source="B", thread=f"b{i % 4}") for i in range(20)]
    records += [rec(40 + i, f"C{i}", 1, source="C", thread=f"c{i % 4}") for i in range(20)]
    out = leave_one_out(records)  # base 30 of 60 = 50.0
    by = {(r["kind"], r["removed"]): r["negative"].get("pct") for r in out["removals"]}
    assert (by[("source", "A")], by[("source", "B")], by[("source", "C")]) == (50.0, 25.0, 75.0)
    assert (out["min_pct"], out["max_pct"]) == (25.0, 75.0)
    assert out["most_moved"] == {"kind": "source", "removed": "B", "change_pts": -25.0}  # tie with C: first wins
    assert sum(r["kind"] == "thread" for r in out["removals"]) == 5


def test_cap_weights_and_the_uncapped_estimate_known_answer():
    records = [rec(0, "P1", -1, thread="T1")]
    threads = {"T1": {"after_person_cap": 10, "sampled": 4}}
    # 12 eligible posts, 5 kept by the person cap: 12/5 = 2.4; 10 in the thread's frame, 4 sampled: 2.5
    assert cap_weights(records, {"P1": 12}, 5, threads) == [pytest.approx(6.0)]
    people = [rec(i, f"P{i}", -1 if i < 10 else 1) for i in range(20)]
    est = without_caps(people, [3.0] * 10 + [1.0] * 10)  # 30 of 40 weighted
    assert est["pct"] == 75.0 and est["status"] == "early-signal"


# ---- crp analyse -------------------------------------------------------------

@pytest.fixture
def analysed_study(batched):
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    return batched


def test_analyse_needs_locked_labels(batched):
    write_labels(batched)
    with pytest.raises(InputError, match="aren't locked yet"):
        analyse(batched)


def test_same_seed_gives_identical_results(analysed_study):
    analyse(analysed_study, seed=3, draws=300)
    first = (analysed_study / "results" / "results.json").read_bytes()
    analyse(analysed_study, seed=3, draws=300)
    assert (analysed_study / "results" / "results.json").read_bytes() == first
    analyse(analysed_study, seed=4, draws=300)
    assert (analysed_study / "results" / "results.json").read_bytes() != first


def test_analyse_uses_the_measurement_sample_only(analysed_study):
    out = analyse(analysed_study, seed=3, draws=300)["results"]
    measured = [json.loads(line) for line in (analysed_study / "samples" / "measurement.jsonl").read_text().splitlines()]
    assert out.headline.negative.n == len(measured) == out.sample.n_items == 28
    assert out.sample.status == "early-signal" and out.sample.thread_cap_loosened
    assert out.interviews.transcripts == 1 and out.interviews.coded_turns == 4  # counted apart (D14)
    assert out.keyness.shown is False and "early-signal" in out.keyness.reason
    assert not out.agreement_status  # not scored yet, so every section is unverified


def test_a_hand_edited_number_fails_the_schema(analysed_study):
    analyse(analysed_study, seed=3, draws=300)
    data = json.loads((analysed_study / "results" / "results.json").read_text())
    data["headline"]["negative"]["pct"] = 12.3
    with pytest.raises(InputError, match="pct is 12.3, but"):
        validate(Results, data, "results.json")


def test_top_driver_ties_go_to_the_alphabetically_first_aspect():
    # every comment is negative on both, so every re-draw ties; "zeta" is mentioned first, "alpha" wins (drivers.py)
    records = [rec(i, f"P{i:02d}", -1, thread=f"T{i % 5}", aspects={"zeta": -1, "alpha": -1}) for i in range(25)]
    eng = Engine(records, draws=200, seed=1)
    for rule in ("d12", "skill"):
        a = {x["aspect"]: x for x in stats.aspects(eng, rule=rule)["aspects"]}
        assert a["alpha"]["top_driver"]["pct_people"] == 100.0 and a["zeta"]["top_driver"]["pct_people"] == 0.0


def test_cli_analyse(analysed_study, capsys):
    from crp.cli import main
    assert main(["analyse", str(analysed_study), "--draws", "200"]) == 0
    out = capsys.readouterr().out
    assert "Sample: 28 comments from 21 people in 4 threads (early-signal)" in out
    assert "thread cap was loosened to 30%" in out and "every section is unverified" in out
    assert "Interviews (own section, counts only): 1 transcript(s)" in out
