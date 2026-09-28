"""crp build and crp check-numbers: outputs filled from results.json, banners, safe wording, quote-free by default."""
import json
import re

import pytest

from conftest import write_labels, write_synthesis
from crp import wording
from crp.agreement import export, score
from crp.analyse import analyse
from crp.build import build, quoted_runs, visible_text
from crp.io import InputError, read_jsonl
from crp.labels import lock
from crp.numbers import check_numbers, numbers_in
from crp.schemas import Post, Study
from crp.text import shingles
from test_agreement import ai_values, fill, save

SECTIONS = ["verdict", "drivers", "direction", "themes", "pains", "successes", "jobs", "opportunities", "entities",
            "interviews", "language", "trust"]


@pytest.fixture
def analysed(batched):
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    write_synthesis(batched)
    analyse(batched, seed=3, draws=200)
    return batched


def results(d):
    return json.loads((d / "results" / "results.json").read_text())


# ---- the dashboard renders from results.json ---------------------------------

def test_dashboard_renders_from_results_json_alone(analysed):
    build(analysed)
    html = (analysed / "results" / "dashboard.html").read_text()
    for s in SECTIONS:
        assert f'id="{s}"' in html, s
    assert "{{" not in html and "{%" not in html and "outlook" not in html.lower()
    r = results(analysed)
    neg = r["headline"]["negative"]
    assert f"Negative {neg['pct']}%" in visible_text(html)
    assert f"likely {neg['range'][0]}–{neg['range'][1]}% within this collection" in html  # D28's range, labelled
    sens = r["sensitivity"]
    assert f"{sens['min_pct']}–{sens['max_pct']}% negative" in html  # the leave-one-out range next to it
    assert check_numbers(analysed)["ok"]
    first = html
    build(analysed)
    assert (analysed / "results" / "dashboard.html").read_text() == first


def test_every_section_has_a_verification_banner_and_red_until_checked(analysed):
    build(analysed)
    html = (analysed / "results" / "dashboard.html").read_text()
    for s in SECTIONS:
        if s == "trust":
            continue
        section = html[html.index(f'id="{s}"'):]
        assert 'class="vbanner v-unverified"' in section[:600], s
    assert "the agreement check hasn't been run" in html


def test_banners_follow_each_sections_own_variables(analysed):
    export(analysed)
    ai = ai_values(analysed)
    human = {i: dict(v, jtbd_force="habit" if v.get("jtbd_force") != "habit" else "push") if i.startswith("d") else v
             for i, v in ai.items()}
    save(analysed, fill(analysed, "Steeve", human.get))
    score(analysed)
    analyse(analysed, seed=3, draws=200)
    build(analysed)
    html = (analysed / "results" / "dashboard.html").read_text()

    def banner(sid):
        section = html[html.index(f'id="{sid}"'):]
        return re.search(r'class="vbanner v-(\w+)"', section[:800]).group(1)
    assert banner("drivers") == "verified"  # overall and aspect scores agree
    assert banner("jobs") == "unverified"  # force was coded differently every time
    assert banner("pains") == "verified"  # a weak force code doesn't turn pain points red (D25)
    assert check_numbers(analysed)["ok"]


# ---- check-numbers -----------------------------------------------------------

def test_check_numbers_catches_a_planted_invented_number(analysed):
    (analysed / "synthesis" / "summary.md").write_text(
        "About 73% of people hate sync, while {{ headline.negative.pct }}% of sampled comments were negative.\n")
    build(analysed)
    rep = check_numbers(analysed)
    assert not rep["ok"]
    assert [p.split(": ")[1].split()[0] for p in rep["problems"]] == ["73", "73"]  # at the source and in the report
    (analysed / "synthesis" / "summary.md").write_text("{{ headline.negative.k }} of the sampled comments were negative.\n")
    build(analysed)
    assert check_numbers(analysed)["ok"]


def test_a_typed_number_in_an_insight_is_caught(analysed):
    ins = json.loads((analysed / "synthesis" / "insights.json").read_text())
    ins["insights"][0]["statement"] = "Nearly 40% of forum posters cancel over sync."
    (analysed / "synthesis" / "insights.json").write_text(json.dumps(ins))
    analyse(analysed, seed=3, draws=200)
    build(analysed)
    rep = check_numbers(analysed)
    assert not rep["ok"]
    assert rep["problems"][0].startswith("insight I01: 40")  # caught at the source, even if 40 appears in results


def test_an_observation_may_repeat_its_own_posts_numbers(analysed):
    posts = {p.post_id: p for p in read_jsonl(analysed / "posts.jsonl", Post)}
    rows = [json.loads(line) for line in (analysed / "synthesis" / "observations.jsonl").read_text().splitlines()]
    with_number = next(r for r in rows if numbers_in(posts[r["post_id"]].text))
    own = numbers_in(posts[with_number["post_id"]].text)[0][1]
    with_number["observation"] = f"Mentions {own} directly."
    (analysed / "synthesis" / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    analyse(analysed, seed=3, draws=200)
    build(analysed)
    assert check_numbers(analysed)["ok"]
    with_number["observation"] = "Mentions 987654 directly."
    (analysed / "synthesis" / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    analyse(analysed, seed=3, draws=200)
    build(analysed)
    rep = check_numbers(analysed)
    assert not rep["ok"] and rep["problems"][0].startswith("observation ") and "987654" in rep["problems"][0]


def test_numbers_in_skips_ids_and_dates():
    text = "T01-p02 and I01, H1, C07 on 2026-06-09 in 2026-W23: 64.3% of 1,234 (−2 to +2)"
    assert [t for _, t in numbers_in(text)] == ["64.3", "1,234", "2", "2"]
    assert numbers_in("(T01-p02, P-68388532, opinion) and P-0a1b2c3d") == []  # an all-digit person code is an id


# ---- quote-free by default (D33) ----------------------------------------------

def test_default_build_has_no_quotes_titles_or_person_codes(analysed):
    build(analysed)
    d = analysed / "results"
    text = visible_text((d / "dashboard.html").read_text()) + "\n" + (d / "report.md").read_text()
    posts = read_jsonl(analysed / "posts.jsonl", Post)
    assert not quoted_runs(text, posts)
    everything = (d / "dashboard.html").read_text() + (d / "report.md").read_text()
    assert not re.search(r"\bP-[0-9a-f]{8}\b", everything)
    assert not {p.thread_title for p in posts if p.thread_title} & set(re.split(r"[:|\n]", everything))
    assert "Internal build" not in everything
    # while the internal build, kept apart, does quote posts and says so
    build(analysed, with_quotes=True)
    internal = (analysed / "results" / "internal" / "dashboard.html").read_text()
    assert quoted_runs(visible_text(internal), posts) and "Internal build: it quotes posts" in internal
    assert "Internal build" in (analysed / "results" / "internal" / "report.md").read_text()
    assert (analysed / "results" / "dashboard.html").read_text() == (d / "dashboard.html").read_text()  # untouched


def test_build_refuses_an_observation_that_copies_its_post(analysed):
    posts = {p.post_id: p for p in read_jsonl(analysed / "posts.jsonl", Post)}
    rows = [json.loads(line) for line in (analysed / "synthesis" / "observations.jsonl").read_text().splitlines()]
    rows[0]["observation"] = posts[rows[0]["post_id"]].text  # copied, not paraphrased
    (analysed / "synthesis" / "observations.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    analyse(analysed, seed=3, draws=200)
    with pytest.raises(InputError, match="six words quoted from posts"):
        build(analysed)
    assert not (analysed / "results" / "dashboard.html").exists()
    build(analysed, with_quotes=True)  # the internal version may quote


# ---- safe wording (D8, D11) --------------------------------------------------

def study(kind="product"):
    return Study.model_validate({"id": "s", "subject": "Quillnote", "type": kind, "stance_target": "x",
                                 "created": "2026-09-01"})


def share(k, n, people, status, pct=None, rng=None):
    out = {"k": k, "n": n, "n_people": people, "n_items": n, "status": status}
    if pct is not None:
        out |= {"pct": pct, "range": rng}
    return out


def test_safe_wording_by_status():
    full = {"headline": {"negative": share(90, 150, 96, "full", 60.0, [52.1, 67.9]),
                         "positive": share(30, 150, 96, "full", 20.0, [14.0, 26.1])},
            "drivers": ["pricing", "sync"], "collection": {"window": ["2026-04-01", "2026-08-31"]}}
    s = wording.safe_wording(full, study(), ["r/notetaking"])
    assert s == ("In a random sample of 150 comments from 96 people posting in r/notetaking between 2026-04-01 and "
                 "2026-08-31, 60.0% of the comments were negative (likely 52.1–67.9% within this collection), "
                 "most often about pricing.")
    assert wording.verdict(full, study()) == "Mostly negative, driven by pricing and sync"
    early = {"headline": {"negative": share(30, 40, 25, "early-signal", 75.0, [60.0, 88.0]),
                          "positive": share(4, 40, 25, "early-signal", 10.0, [2.5, 20.0])}, "drivers": ["sync"]}
    assert "30 of the 40 comments were negative" in wording.safe_wording(early, study(), [])
    assert "early signal" in wording.safe_wording(early, study(), [])
    assert wording.verdict(early, study()) == "Leaning negative, mostly about sync, in a small sample"
    few = {"headline": {"negative": share(9, 12, 8, "counts-only"), "positive": share(1, 12, 8, "counts-only")}}
    assert "fewer than 20 people, this is a count" in wording.safe_wording(few, study(), []).lower()
    assert wording.verdict(few, study()) == "Too few people to measure: 9 of 12 sampled comments were negative"
    for sentence in (s, wording.safe_wording(early, study(), [])):
        assert "% of people" not in sentence  # one unit: comments (D8)


# ---- CLI ---------------------------------------------------------------------

def test_cli_build_and_check_numbers(analysed, capsys):
    from crp.cli import main
    assert main(["build", str(analysed)]) == 0 and "safe to share" in capsys.readouterr().out
    assert main(["check-numbers", str(analysed)]) == 0
    (analysed / "synthesis" / "summary.md").write_text("Roughly 12.5% said so.\n")
    main(["build", str(analysed)])
    capsys.readouterr()
    assert main(["check-numbers", str(analysed)]) == 1 and "UNTRACED synthesis/summary.md line 1: 12.5" in capsys.readouterr().out


def test_one_day_window_and_no_screenshots(analysed):
    r = results(analysed)
    assert wording.who(r | {"collection": {"window": ["2026-09-28", "2026-09-28"]}}, ["r/x"]) == "posting in r/x on 2026-09-28"
    r["collection"]["transcription"].pop("unverified", None)  # a study with no screenshots
    (analysed / "results" / "results.json").write_text(json.dumps(r))
    build(analysed)
    assert "Screenshot posts not cross-checked" not in (analysed / "results" / "dashboard.html").read_text()
