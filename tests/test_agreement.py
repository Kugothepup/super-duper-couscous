"""crp agreement: Krippendorff's alpha, the blind human sheet, and scoring."""
import csv
import json

import krippendorff
import numpy as np
import pytest

from conftest import dummy_values, write_labels
from crp import thresholds
from crp.agreement import AI, columns, export, metrics, parse_cell, reliability_alpha, score
from crp.io import InputError
from crp.labels import lock
from crp.schemas import Codebook

N = None
# Krippendorff (2011), "Computing Krippendorff's alpha-reliability": 4 observers, 12 units, values 1-5.
# Published: nominal 0.743, ordinal 0.815.
REFERENCE = {"A": [1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N],
             "B": [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
             "C": [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N],
             "D": [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N]}


# ---- alpha -------------------------------------------------------------------

@pytest.mark.parametrize("level, published", [("nominal", 0.743), ("ordinal", 0.815)])
def test_alpha_matches_the_krippendorff_package_on_its_reference_example(level, published):
    data = {c: {f"u{j + 1:02d}": v - 1 for j, v in enumerate(vals) if v is not None} for c, vals in REFERENCE.items()}
    ours = reliability_alpha(data, 5, level)
    raw = np.array([[np.nan if v is None else v for v in vals] for vals in REFERENCE.values()], dtype=float)
    assert ours["alpha"] == pytest.approx(krippendorff.alpha(reliability_data=raw, level_of_measurement=level), abs=1e-12)
    assert round(ours["alpha"], 3) == published
    assert ours["units"] == 12 and ours["pairable"] == 11  # unit 12 has one value, so it can't be compared


def test_alpha_is_undefined_without_pairs_or_variation():
    assert reliability_alpha({"a": {"u1": 0}, "b": {"u2": 1}}, 2, "nominal") == \
        {"units": 2, "pairable": 0, "alpha": None, "note": "no item was coded by two coders"}
    same = reliability_alpha({"a": {"u1": 1, "u2": 1}, "b": {"u1": 1, "u2": 1}}, 3, "ordinal")
    assert same["alpha"] is None and "can't be told from chance" in same["note"]
    assert thresholds.agreement_status(same["alpha"]) == "unverified"


def test_empty_values_are_scored_twice():
    codebook = Codebook.model_validate({
        "version": "1", "study_type": "news", "aspects": ["cost", "safety"],
        "variables": [
            {"name": "stance", "description": "d", "applies_to": "measurement", "level": "ordinal",
             "values": [-2, -1, 0, 1, 2], "nullable": True},
            {"name": "aspect_scores", "description": "d", "applies_to": "measurement", "kind": "per_aspect",
             "level": "ordinal", "values": [-2, -1, 0, 1, 2]}]})
    items = {i: {"variables": ["stance", "aspect_scores"]} for i in ("m1", "m2")}
    coded = {AI: {"m1": {"stance": None, "aspect_scores": {"cost": -1}}, "m2": {"stance": 2, "aspect_scores": {}}},
             "H": {"m1": {"stance": 1, "aspect_scores": {"cost": -2}}, "m2": {"stance": 2, "aspect_scores": {}}}}
    m = metrics(codebook, coded, items)
    assert set(m) == {"stance (expressed)", "stance", "aspect_scores (mentioned)", "aspect_scores"}
    assert m["stance (expressed)"][2] == {AI: {"m1": 0, "m2": 1}, "H": {"m1": 1, "m2": 1}}
    assert m["stance"][2] == {AI: {"m2": 4}, "H": {"m1": 3, "m2": 4}}  # null is left out, not a value
    assert m["aspect_scores (mentioned)"][2][AI] == {"m1:cost": 1, "m1:safety": 0, "m2:cost": 0, "m2:safety": 0}
    assert m["aspect_scores"][2] == {AI: {"m1:cost": 1}, "H": {"m1:cost": 0}}


def test_parse_cell():
    codebook = Codebook.model_validate({"version": "1", "study_type": "product", "variables": [
        {"name": "f", "description": "d", "applies_to": "detail", "level": "nominal", "values": [True, False]},
        {"name": "s", "description": "d", "applies_to": "detail", "level": "ordinal", "values": [-2, -1, 0, 1, 2]},
        {"name": "k", "description": "d", "applies_to": "detail", "level": "nominal", "values": ["push", "pull"]}]})
    f, s, k = codebook.variables
    assert parse_cell(f, "TRUE") is True and parse_cell(f, " false ") is False
    assert parse_cell(s, "+2") == 2 and parse_cell(s, "-1") == -1 and parse_cell(s, "") is None
    assert parse_cell(k, "Push") == "push" and parse_cell(k, "null") is None
    for bad_var, bad in ((f, "1"), (s, "2.0"), (s, "3"), (k, "habit")):
        with pytest.raises(ValueError, match="isn't one of"):
            parse_cell(bad_var, bad)


# ---- export ------------------------------------------------------------------

def sheet_rows(d):
    with (d / "human" / "agreement_sheet.csv").open(newline="") as f:
        return list(csv.DictReader(f))


def test_sheet_holds_no_ai_labels(batched):
    marked = lambda sample, n: dummy_values(sample, n)
    index = write_labels(batched, marked)
    for p in (batched / "labels").iterdir():  # give every label a rationale that must not leak
        rows = [json.loads(line) | {"rationale": "ZEBRA rationale"} for line in p.read_text().splitlines()]
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = export(batched, n=50)
    assert out == {"items": 50, "of": 100, "seed": index["seed"]}
    text = (batched / "human" / "agreement_sheet.csv").read_text()
    assert "ZEBRA" not in text
    sample_of = {it["item_id"]: b for b in index["batches"] for it in b["items"]}
    rows = sheet_rows(batched)
    assert len(rows) == 50 and list(rows[0]) == columns(__import__("crp.codebook", fromlist=["x"]).frozen(batched)[0])
    for row in rows:
        applies = sample_of[row["item_id"]]["variables"]
        assert row["coder"] == ""
        for col, cell in row.items():
            name = col.split("[")[0]
            if col in ("item_id", "coder", "text", "parent_text"):
                continue
            assert cell == ("" if name in applies else "n/a")
    guide = (batched / "human" / "agreement_guide.md").read_text()
    assert all(f"### {v}" in guide for v in ("overall", "aspect_scores", "jtbd_force", "severity"))


def test_export_is_seeded_takes_all_when_fewer_and_keeps_a_coded_sheet(batched):
    export(batched, n=30)
    first = (batched / "human" / "agreement_sheet.csv").read_text()
    export(batched, n=30)
    assert (batched / "human" / "agreement_sheet.csv").read_text() == first
    assert export(batched, n=500)["items"] == 100
    export(batched, n=30)
    (batched / "human" / "human_labels.csv").write_text(first)
    with pytest.raises(InputError, match="already holds human codes"):
        export(batched, n=30, seed=5)


# ---- score -------------------------------------------------------------------

def cell(value):
    if value is None:
        return ""
    return str(value).lower() if isinstance(value, bool) else str(value)


def fill(d, coder, values_of, rows=None):
    """Fill the sheet as a human coder would, from values_of(item_id) -> values dict."""
    rows = rows if rows is not None else sheet_rows(d)
    out = []
    for row in rows:
        row = dict(row, coder=coder)
        values = values_of(row["item_id"])
        for col in list(row)[4:]:
            if row[col] == "n/a":
                continue
            name, _, aspect = col.rstrip("]").partition("[")
            row[col] = cell(values[name].get(aspect) if aspect else values[name])
        out.append(row)
    return out


def save(d, rows):
    with (d / "human" / "human_labels.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def ai_values(d):
    out = {}
    for p in (d / "labels").iterdir():
        for line in p.read_text().splitlines():
            r = json.loads(line)
            out[r["item_id"]] = r["values"]
    return out


@pytest.fixture
def locked_study(batched):
    write_labels(batched)
    lock(batched, "claude-opus-5-5")
    export(batched, n=100)
    return batched


def test_score_needs_locked_labels(batched):
    write_labels(batched)
    export(batched, n=10)
    with pytest.raises(InputError, match="aren't locked yet"):
        score(batched)


def test_perfect_agreement_is_verified(locked_study):
    ai = ai_values(locked_study)
    save(locked_study, fill(locked_study, "Steeve", ai.get))
    report = score(locked_study)
    assert report["status"] == "verified" and report["coders"] == [AI, "Steeve"] and report["items"] == 100
    assert all(m["alpha"] == pytest.approx(1.0) and m["status"] == "verified" for m in report["metrics"].values())
    [table] = report["confusion"]
    counts = np.array(table["counts"])
    assert counts.sum() == sum(1 for i in ai if i.startswith("m")) and (counts == np.diag(np.diag(counts))).all()
    saved = json.loads((locked_study / "results" / "agreement.json").read_text())
    assert saved["status"] == "verified" and saved["coder_model"] == "claude-opus-5-5"


def test_disagreement_matches_a_direct_computation(locked_study):
    ai = ai_values(locked_study)
    flip = {i: v for i, v in ai.items() if i.startswith("m")}
    changed = sorted(flip)[::3]
    human = {i: dict(v, overall=(v["overall"] + 2) % 5 - 2) if i in changed else v for i, v in ai.items()}
    save(locked_study, fill(locked_study, "Steeve", human.get))
    report = score(locked_study)
    ids = sorted(flip)
    raw = np.array([[ai[i]["overall"] for i in ids], [human[i]["overall"] for i in ids]], dtype=float)
    expected = krippendorff.alpha(reliability_data=raw, level_of_measurement="ordinal", value_domain=[-2, -1, 0, 1, 2])
    assert report["metrics"]["overall"]["alpha"] == pytest.approx(expected, abs=1e-12)
    assert report["metrics"]["overall"]["status"] == thresholds.agreement_status(expected)
    assert report["status"] == report["metrics"]["overall"]["status"]  # the worst variable sets the study's status
    assert report["metrics"]["jtbd_force"]["status"] == "verified"


@pytest.mark.parametrize("spoil, message", [
    (lambda rows: rows[0].update(coder=AI), "reserved for the blind coder"),
    (lambda rows: rows.append(dict(rows[0])), "coded m"),
    (lambda rows: rows[0].update(item_id="x9999"), "isn't a coded item"),
    (lambda rows: rows[0].update(overall="3"), "overall: '3' isn't one of"),
    (lambda rows: rows[0].update(jtbd_force="push"), "doesn't apply to this item"),
])
def test_bad_human_sheets_are_refused(locked_study, spoil, message):
    ai = ai_values(locked_study)
    rows = fill(locked_study, "Steeve", ai.get)
    first_m = next(i for i, r in enumerate(rows) if r["item_id"].startswith("m"))
    rows.insert(0, rows.pop(first_m))
    spoil(rows)
    save(locked_study, rows)
    with pytest.raises(InputError, match=message):
        score(locked_study)


def test_a_second_human_coder_is_included(locked_study):
    ai = ai_values(locked_study)
    rows = fill(locked_study, "Steeve", ai.get) + fill(locked_study, "Second coder", ai.get)
    save(locked_study, rows)
    report = score(locked_study)
    assert report["coders"] == [AI, "Second coder", "Steeve"] and len(report["confusion"]) == 2
