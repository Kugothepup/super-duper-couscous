"""crp agreement export / score: how far a human coder agrees with the blind coder (D5).

export: a seeded random sample of coded items (default 100, or all if fewer) to
human/agreement_sheet.csv, with the item text, the context the coder saw, and one empty
column per codebook variable. It never reads the AI's labels. Columns that don't apply to an
item say n/a. human/agreement_guide.md sets out the codebook for the human coder.

score: reads the filled sheet (saved as human/human_labels.csv, one row per item per coder)
and the locked AI labels, and computes Krippendorff's alpha per variable with the krippendorff
package: nominal or ordinal as the codebook says, values in codebook order. A variable that can
be empty is scored twice (D25, proposed): whether it was used at all (nominal), and its value
where both used it. So "aspect_scores (mentioned)" and "aspect_scores", and "stance (expressed)"
and "stance". Each gets a status from the thresholds, and the study's status is the worst of them.
A confusion table compares the AI's and each human's `overall` codes. Writes results/agreement.json.
"""
from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

import krippendorff
import numpy as np

from crp import manifest, thresholds
from crp.batch import BATCHES, read_index, labels_file
from crp.codebook import CODEBOOK, frozen
from crp.io import InputError, atomic_write_text, validate
from crp.labels import LABELS_LOCK, batch_items, check_values, locked, member, read_labels
from crp.schemas import Codebook, HumanLabel, Variable

SHEET = Path("human") / "agreement_sheet.csv"
GUIDE = Path("human") / "agreement_guide.md"
HUMAN = Path("human") / "human_labels.csv"
REPORT = Path("results") / "agreement.json"
AI = "ai"
NA = "n/a"
SAMPLE_SIZE = 100
RANK = {"unverified": 0, "tentative": 1, "verified": 2}


def columns(codebook: Codebook) -> list[str]:
    cols = ["item_id", "coder", "text", "parent_text"]
    for v in codebook.variables:
        cols += [f"{v.name}[{a}]" for a in codebook.aspects] if v.kind == "per_aspect" else [v.name]
    return cols


def batch_texts(study_dir: Path, index: dict) -> dict[str, dict]:
    """item_id -> the item line the coder saw, plus which sample it came from."""
    out = {}
    for entry in index["batches"]:
        batch_items(study_dir, entry)  # checks the file is unchanged
        lines = (study_dir / BATCHES / f"{entry['batch']}.jsonl").read_text(encoding="utf-8").splitlines()
        for line in lines[1:]:
            item = json.loads(line)
            out[item["item_id"]] = item | {"variables": entry["variables"]}
    return out


def guide(codebook: Codebook) -> str:
    lines = [f"# Agreement coding guide (codebook version {codebook.version})", "",
             "Code each row of `agreement_sheet.csv` from its text alone, as the blind coder did. `parent_text` "
             "is context only: never code it. Don't look at the AI's labels until you have finished.", "",
             "## Filling in the sheet", "",
             "- Put your name in `coder` on every row.",
             f"- Fill every variable column that doesn't say {NA}.",
             "- Write values exactly as listed below.",
             "- Leave a cell blank for null: no position expressed, severity when there is no friction.",
             "- Aspect columns (`name[aspect]`): give a score only for aspects the text evaluates. "
             "Leave the others blank.",
             "- Save the finished sheet as `human/human_labels.csv`. For a second coder, add their rows below yours.",
             ""]
    if codebook.instructions:
        lines += ["## Rules", ""] + [f"- {r}" for r in codebook.instructions] + [""]
    if codebook.aspects:
        lines += ["## Aspects", ""] + [f"- `{a}`" + (f": {codebook.aspect_definitions[a]}"
                                                    if a in codebook.aspect_definitions else "")
                                      for a in codebook.aspects] + [""]
    lines += ["## Variables", ""]
    for v in codebook.variables:
        lines += [f"### {v.name}", "", v.description, "", "Values: " + ", ".join(f"`{json.dumps(x)}`" for x in v.values)]
        if v.required_when:
            lines.append(f"Required when `{v.required_when}` is true; blank when it is false.")
        elif v.nullable:
            lines.append("Blank when the text expresses none.")
        for key, d in v.definitions.items():
            lines.append(f"- `{key}`: {d}")
        lines.append("")
    return "\n".join(lines)


def export(study_dir: Path, n: int = SAMPLE_SIZE, seed: int | None = None) -> dict:
    study_dir = Path(study_dir)
    codebook, _ = frozen(study_dir)
    index = read_index(study_dir)
    if n < 1:
        raise InputError(f"The sample size must be 1 or more (got {n}).")
    seed = index["seed"] if seed is None else seed
    items = batch_texts(study_dir, index)
    chosen = random.Random(seed).sample(sorted(items), min(n, len(items)))
    cols = columns(codebook)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for item_id in chosen:
        item = items[item_id]
        row = [item_id, "", item["text"], item.get("parent_text", "")]
        for v in codebook.variables:
            cell = "" if v.name in item["variables"] else NA
            row += [cell] * (len(codebook.aspects) if v.kind == "per_aspect" else 1)
        w.writerow(row)
    sheet = buf.getvalue()
    old = study_dir / SHEET
    if (study_dir / HUMAN).exists() and old.exists() and old.read_text(encoding="utf-8") != sheet:
        raise InputError(f"{HUMAN} already holds human codes for the current sheet, and a new export would give "
                         "different items. Keep the sheet as it is.")
    with manifest.stage(study_dir, "agreement export", inputs=[study_dir / CODEBOOK], seed=seed,
                        codebook_version=codebook.version) as record:
        atomic_write_text(old, sheet)
        atomic_write_text(study_dir / GUIDE, guide(codebook) + "\n")
        record["items"] = chosen
        record["outputs"] = [str(SHEET), str(GUIDE)]
    return {"items": len(chosen), "of": len(items), "seed": seed}


# ---- reading the human codes -------------------------------------------------

def parse_cell(v: Variable, cell: str) -> object:
    """A sheet cell as a codebook value. Blank means null. Raises ValueError if it isn't one."""
    cell = cell.strip()
    if cell == "" or cell.lower() == "null":
        return None
    for a in v.values:
        if isinstance(a, bool):
            if cell.lower() in ("true", "false") and (cell.lower() == "true") == a:
                return a
        elif isinstance(a, int):
            try:
                if int(cell) == a:
                    return a
            except ValueError:
                pass
        elif cell.lower() == a.lower():
            return a
    raise ValueError(f"'{cell}' isn't one of {json.dumps(v.values)}")


def read_human(study_dir: Path, codebook: Codebook, items: dict[str, dict]) -> list[HumanLabel]:
    path = study_dir / HUMAN
    if not path.exists():
        raise InputError(f"No {HUMAN}. Fill in {SHEET} and save it as {HUMAN}.")
    cols = columns(codebook)
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != cols:
            raise InputError(f"{path}: the header must be the sheet's: {','.join(cols)}")
        rows, seen, errors = [], set(), []
        for raw in reader:
            where = f"{path} line {reader.line_num}"
            if None in raw:
                errors.append(f"{where}: more values than columns")
                continue
            row = {k: v or "" for k, v in raw.items()}
            item = items.get(row["item_id"])
            if item is None:
                errors.append(f"{where}: {row['item_id']!r} isn't a coded item")
                continue
            values: dict = {}
            for v in codebook.variables:
                applies = v.name in item["variables"]
                cells = {a: row[f"{v.name}[{a}]"] for a in codebook.aspects} if v.kind == "per_aspect" \
                    else {None: row[v.name]}
                if not applies:
                    if any(c.strip() not in ("", NA) for c in cells.values()):
                        errors.append(f"{where}: {v.name} doesn't apply to this item (leave it {NA})")
                    continue
                try:
                    parsed = {a: parse_cell(v, c) for a, c in cells.items()}
                except ValueError as err:
                    errors.append(f"{where}: {v.name}: {err}")
                    continue
                values[v.name] = {a: s for a, s in parsed.items() if s is not None} \
                    if v.kind == "per_aspect" else parsed[None]
            variables = [codebook.variable(n) for n in item["variables"]]
            errors += [f"{where}: {p}" for p in check_values(values, variables, codebook.aspects)]
            key = (row["item_id"], row["coder"].strip())
            if key in seen:
                errors.append(f"{where}: {key[1]} coded {key[0]} twice")
            seen.add(key)
            if key[1] == AI:
                errors.append(f"{where}: '{AI}' is reserved for the blind coder; use your name")
            try:
                rows.append(validate(HumanLabel, {"item_id": key[0], "coder": key[1], "values": values}, where))
            except InputError as err:
                errors.append(str(err))
    if errors:
        raise InputError("\n".join(errors))
    return rows


# ---- alpha -------------------------------------------------------------------

def reliability_alpha(data: dict[str, dict[str, int]], n_values: int, level: str) -> dict:
    """Krippendorff's alpha from {coder: {unit: value index}}. Units coded by fewer than two coders
    can't be compared and are left out, as the method says. Undefined (None) with no variation."""
    units = sorted({u for coded in data.values() for u in coded})
    coders = sorted(data)
    matrix = np.full((len(coders), len(units)), np.nan)
    for i, c in enumerate(coders):
        for j, u in enumerate(units):
            if u in data[c]:
                matrix[i, j] = data[c][u]
    pairable = matrix[:, (~np.isnan(matrix)).sum(axis=0) >= 2]
    out = {"units": len(units), "pairable": int(pairable.shape[1]), "alpha": None}
    if out["pairable"] == 0:
        out["note"] = "no item was coded by two coders"
    elif len(np.unique(pairable[~np.isnan(pairable)])) < 2:
        out["note"] = "every code was the same, so agreement can't be told from chance"
    else:
        out["alpha"] = float(krippendorff.alpha(reliability_data=pairable, level_of_measurement=level,
                                                value_domain=list(range(n_values))))
    return out


def metrics(codebook: Codebook, coded: dict[str, dict[str, dict]], items: dict[str, dict]) -> dict:
    """{metric: (level, number of values, {coder: {unit: value index}})} for every variable."""
    out: dict[str, tuple[str, int, dict]] = {}
    for v in codebook.variables:
        def add(name: str, level: str, n: int, unit: str, coder: str, value: int | None) -> None:
            data = out.setdefault(name, (level, n, {}))[2].setdefault(coder, {})
            if value is not None:
                data[unit] = value
        for coder, labels in coded.items():
            for item_id, values in labels.items():
                if v.name not in items[item_id]["variables"] or v.name not in values:
                    continue
                value = values[v.name]
                if v.kind == "per_aspect":
                    for a in codebook.aspects:
                        score = value.get(a)
                        add(f"{v.name} (mentioned)", "nominal", 2, f"{item_id}:{a}", coder, int(score is not None))
                        add(v.name, v.level, len(v.values), f"{item_id}:{a}", coder,
                            None if score is None else index_of(score, v.values))
                    continue
                if v.nullable:
                    add(f"{v.name} (expressed)", "nominal", 2, item_id, coder, int(value is not None))
                add(v.name, v.level, len(v.values), item_id, coder, None if value is None else index_of(value, v.values))
    return out


def index_of(value: object, allowed: list) -> int:
    return next(i for i, a in enumerate(allowed) if member(value, [a]))


def confusion(codebook: Codebook, coded: dict[str, dict[str, dict]]) -> list[dict]:
    try:
        v = codebook.variable("overall")
    except KeyError:
        return []
    tables = []
    for coder in sorted(c for c in coded if c != AI):
        counts = [[0] * len(v.values) for _ in v.values]
        for item_id, values in coded[coder].items():
            ai = coded[AI].get(item_id, {}).get("overall")
            if ai is not None and values.get("overall") is not None:
                counts[index_of(ai, v.values)][index_of(values["overall"], v.values)] += 1
        tables.append({"variable": "overall", "rows": AI, "columns": coder, "values": v.values, "counts": counts})
    return tables


def score(study_dir: Path) -> dict:
    study_dir = Path(study_dir)
    codebook, _ = frozen(study_dir)
    lock = locked(study_dir)
    index = read_index(study_dir)
    items = batch_texts(study_dir, index)
    human = read_human(study_dir, codebook, items)
    wanted = {h.item_id for h in human}
    coded: dict[str, dict[str, dict]] = {AI: {}}
    for entry in index["batches"]:
        labels, _ = read_labels(study_dir / labels_file(entry["batch"]))
        coded[AI].update({lab.item_id: lab.values for lab in labels if lab.item_id in wanted})
    for h in human:
        coded.setdefault(h.coder, {})[h.item_id] = h.values
    with manifest.stage(study_dir, "agreement score", inputs=[study_dir / CODEBOOK, study_dir / LABELS_LOCK, study_dir / HUMAN],
                        codebook_version=codebook.version, coder_model=lock["coder_model"]) as record:
        results = {}
        for name, (level, n_values, data) in metrics(codebook, coded, items).items():
            r = reliability_alpha(data, n_values, level)
            results[name] = {"level": level, **r, "status": thresholds.agreement_status(r["alpha"])}
        worst = min((r["status"] for r in results.values()), key=RANK.get, default="unverified")
        report = {"codebook_version": codebook.version, "labels_locked_at": lock["locked_at"],
                  "coder_model": lock["coder_model"], "coders": [AI] + sorted(c for c in coded if c != AI),
                  "items": len(wanted),
                  "thresholds": {"verified": thresholds.ALPHA_VERIFIED, "tentative": thresholds.ALPHA_TENTATIVE},
                  "status": worst, "metrics": results, "confusion": confusion(codebook, coded)}
        atomic_write_text(study_dir / REPORT, json.dumps(report, indent=2) + "\n")
        record["outputs"] = [str(REPORT)]
    return report
