"""crp labels validate / lock, and crp unseal.

validate: every item in every batch has exactly one label line; every value is one the codebook
lists (1 is not true, "2" is not 2); every variable the batch codes is there and nothing else is.
Fails loudly. Warnings (not failures), ported from validate.py: overall and aspect scores pointing
opposite ways, and labels out of the order given.

lock: after a clean validate, records the sha256 of every batch and labels file and the coder
model in labels.lock. From then on the labels can't change, and crp unseal may run. Labels reused
from the last round (D35) must come from the same coder model, and the lock counts them.

unseal: refuses unless the labels are locked and unchanged. Copies sealed/prior.md to
results/prior.md by code and logs the time. Nothing else in the pipeline opens sealed/.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from crp import manifest
from crp.batch import BATCHES, INDEX, LABELS, LABELS_LOCK, labels_file, read_index
from crp.codebook import CODEBOOK, frozen
from crp.io import InputError, atomic_write_text, describe, sha256_file
from pydantic import ValidationError

from crp.schemas import Codebook, Label, Variable

PRIOR = Path("sealed") / "prior.md"
UNSEALED = Path("results") / "prior.md"


def member(value: object, allowed: list) -> bool:
    """`value in allowed`, except that 1 and true, or 2 and 2.0, don't count as the same."""
    return any(type(value) is type(a) and value == a for a in allowed)


def check_values(values: dict, variables: list[Variable], aspects: list[str]) -> list[str]:
    """What's wrong with one item's values, for the variables its batch codes."""
    problems = []
    wanted = {v.name: v for v in variables}
    for extra in sorted(values.keys() - wanted.keys()):
        problems.append(f"'{extra}' isn't a variable this batch codes")
    for v in variables:
        if v.name not in values:
            problems.append(f"'{v.name}' is missing")
            continue
        value = values[v.name]
        if v.kind == "per_aspect":
            if not isinstance(value, dict):
                problems.append(f"'{v.name}' must be an object of aspect: score ({{}} if none)")
                continue
            for a, score in value.items():
                if a not in aspects:
                    problems.append(f"'{v.name}': '{a}' isn't in the codebook's aspect list")
                elif not member(score, v.values):
                    problems.append(f"'{v.name}': {a} is {json.dumps(score)}, not one of {json.dumps(v.values)}")
            continue
        if v.required_when:
            gate = values.get(v.required_when)
            if gate is True and value is None:
                problems.append(f"'{v.name}' is required because {v.required_when} is true")
            elif gate is False and value is not None:
                problems.append(f"'{v.name}' must be null because {v.required_when} is false")
            if value is None:
                continue
        elif value is None:
            if not v.nullable:
                problems.append(f"'{v.name}' can't be null")
            continue
        if not member(value, v.values):
            problems.append(f"'{v.name}' is {json.dumps(value)}, not one of {json.dumps(v.values)}")
    return problems


def opposite_ways(values: dict, variables: list[Variable]) -> bool:
    """validate.py's warning: overall below 0 with every aspect above 0, or the reverse."""
    overall = values.get("overall")
    if not isinstance(overall, int) or isinstance(overall, bool):
        return False
    for v in variables:
        scores = values.get(v.name)
        if v.kind == "per_aspect" and isinstance(scores, dict) and scores:
            nums = [s for s in scores.values() if isinstance(s, int) and not isinstance(s, bool)]
            if nums and (overall < 0 and all(s > 0 for s in nums) or overall > 0 and all(s < 0 for s in nums)):
                return True
    return False


def batch_items(study_dir: Path, entry: dict) -> list[str]:
    """The batch's item ids, after checking the batch file is as crp batch wrote it."""
    path = study_dir / BATCHES / f"{entry['batch']}.jsonl"
    if not path.exists() or sha256_file(path) != entry["sha256"]:
        raise InputError(f"{path} is missing or has been edited since crp batch wrote it. Run crp batch again.")
    return [i["item_id"] for i in entry["items"]]


def read_labels(path: Path) -> tuple[list[Label], list[str]]:
    labels, errors = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            labels.append(Label.model_validate(json.loads(line)))
        except json.JSONDecodeError as err:
            errors.append(f"line {n}: not valid JSON ({err.msg})")
        except ValidationError as err:
            bad_values = sorted({str(e["loc"][1]) for e in err.errors() if e["loc"][0] == "values" and len(e["loc"]) > 1})
            errors += [f"line {n}: values.{v}: must be true/false, a whole number, text, an object of aspect: "
                       "whole number, or null" for v in bad_values]
            rest = [e for e in err.errors() if not (e["loc"][0] == "values" and len(e["loc"]) > 1)]
            if rest:
                errors.append(describe(ValidationError.from_exception_data(err.title, rest), f"line {n}"))
    return labels, errors


def validate_batch(study_dir: Path, entry: dict, codebook: Codebook) -> dict:
    ids = batch_items(study_dir, entry)
    variables = [codebook.variable(n) for n in entry["variables"]]
    path = study_dir / labels_file(entry["batch"])
    out = {"batch": entry["batch"], "items": len(ids), "coded": 0, "errors": [], "warnings": []}
    if not path.exists():
        out["errors"].append(f"not coded yet: no {labels_file(entry['batch'])}")
        return out
    if "reused" in entry and sha256_file(path) != entry["reused"]["labels_sha256"]:
        out["errors"].append(f"{labels_file(entry['batch'])} has been edited since crp batch copied it from "
                             f"{entry['reused']['from']}. Run crp batch again.")
        return out
    labels, out["errors"] = read_labels(path)
    known, seen = set(ids), []
    for lab in labels:
        where = f"item {lab.item_id}"
        if lab.item_id not in known:
            out["errors"].append(f"{where}: not an item in this batch")
            continue
        if lab.item_id in seen:
            out["errors"].append(f"{where}: labelled more than once")
            continue
        seen.append(lab.item_id)
        out["errors"] += [f"{where}: {p}" for p in check_values(lab.values, variables, codebook.aspects)]
        if opposite_ways(lab.values, variables):
            out["warnings"].append(f"{where}: overall and aspect scores point opposite ways")
    missing = [i for i in ids if i not in seen]
    if missing:
        out["errors"].append(f"{len(missing)} item(s) not labelled: {', '.join(missing[:10])}"
                             + (" ..." if len(missing) > 10 else ""))
    elif seen != ids:
        out["warnings"].append("labels aren't in the order the items were given")
    out["coded"] = len(seen)
    return out


def validate(study_dir: Path, only: list[str] | None = None) -> dict:
    study_dir = Path(study_dir)
    codebook, lock = frozen(study_dir)
    index = read_index(study_dir)
    if index["codebook_sha256"] != lock["sha256"]:
        raise InputError("The batches were made under a different codebook. Run crp batch again.")
    entries = index["batches"]
    if only:
        unknown = set(only) - {e["batch"] for e in entries}
        if unknown:
            raise InputError(f"No such batch: {', '.join(sorted(unknown))}")
        entries = [e for e in entries if e["batch"] in only]
    reports = [validate_batch(study_dir, e, codebook) for e in entries]
    return {"ok": not any(r["errors"] for r in reports), "batches": reports}


def labelled(study_dir: Path, index: dict) -> dict[tuple[str, str], dict]:
    """(sample, post id) -> label values, for every coded item. A post can be in both samples."""
    out = {}
    for entry in index["batches"]:
        post_of = {it["item_id"]: it["post_id"] for it in entry["items"]}
        if not (study_dir / labels_file(entry["batch"])).exists():  # not coded yet
            continue
        labels, _ = read_labels(study_dir / labels_file(entry["batch"]))
        for lab in labels:
            out[(entry["sample"], post_of[lab.item_id])] = lab.values
    return out


# ---- lock --------------------------------------------------------------------

def _files(study_dir: Path, index: dict) -> dict[str, str]:
    paths = [INDEX] + [BATCHES / f"{e['batch']}.jsonl" for e in index["batches"]] + \
        [labels_file(e["batch"]) for e in index["batches"]]
    return {str(p): sha256_file(study_dir / p) for p in paths}


def lock(study_dir: Path, coder_model: str) -> dict:
    study_dir = Path(study_dir)
    if not coder_model.strip():
        raise InputError("Give the coder model (the model the blind-coder agent ran on), e.g. --coder-model claude-opus-5-5.")
    report = validate(study_dir)
    if not report["ok"]:
        n = sum(len(r["errors"]) for r in report["batches"])
        raise InputError(f"The labels have {n} problem(s). Run crp labels validate, fix them, then lock.")
    codebook, cb_lock = frozen(study_dir)
    index = read_index(study_dir)
    reused = [e for e in index["batches"] if "reused" in e]
    others = sorted({e["reused"]["coder_model"] for e in reused} - {coder_model})
    if others:
        n = sum(len(e["items"]) for e in reused)
        raise InputError(f"{n} label(s) were reused from {reused[0]['reused']['from']}, where {others[0]} coded them, "
                         f"but this round's coder is {coder_model}. Labels from two models can't be mixed. If "
                         f"{others[0]} coded this round too, lock with --coder-model {others[0]}; otherwise run "
                         "crp batch --no-reuse and have everything coded again.")
    files = _files(study_dir, index)
    existing = study_dir / LABELS_LOCK
    if existing.exists():
        old = json.loads(existing.read_text(encoding="utf-8"))
        if old["files"] == files and old["coder_model"] == coder_model:
            return old | {"unchanged": True}
        raise InputError("The labels are already locked, with different files or coder model.")
    with manifest.stage(study_dir, "labels lock", inputs=[study_dir / CODEBOOK] + [study_dir / f for f in files],
                        codebook_version=codebook.version, coder_model=coder_model) as record:
        data = {"locked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "codebook_version": codebook.version, "codebook_sha256": cb_lock["sha256"],
                "coder_model": coder_model, "items": sum(len(e["items"]) for e in index["batches"]),
                "reused_items": sum(len(e["items"]) for e in reused), "files": files}
        if reused:
            data["reused_from"] = reused[0]["reused"]["from"]
        record["reused_items"] = data["reused_items"]
        atomic_write_text(existing, json.dumps(data, indent=2) + "\n")
        record["outputs"] = [str(LABELS_LOCK)]
    return data


def locked(study_dir: Path) -> dict:
    """The labels lock, after checking the codebook, batches and labels are all as they were locked."""
    study_dir = Path(study_dir)
    _, cb_lock = frozen(study_dir)
    path = study_dir / LABELS_LOCK
    if not path.exists():
        raise InputError("The labels aren't locked yet. Run crp labels lock after crp labels validate passes.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["codebook_sha256"] != cb_lock["sha256"]:
        raise InputError("The labels were locked under a different codebook version.")
    changed = [f for f, h in data["files"].items() if not (study_dir / f).exists() or sha256_file(study_dir / f) != h]
    if changed:
        raise InputError(f"Locked files have changed since the lock: {', '.join(changed)}.")
    return data


# ---- unseal ------------------------------------------------------------------

def unseal(study_dir: Path) -> dict:
    study_dir = Path(study_dir)
    data = locked(study_dir)
    src = study_dir / PRIOR
    if not src.exists():
        raise InputError(f"No {PRIOR}: Steeve went in blind. There is nothing to unseal, so skip this step; "
                         "every hypothesis will be formed from the data.")
    runs = manifest.read(study_dir)
    ingests = [r["started"] for r in runs if r.get("command") == "ingest" and r.get("status") == "ok"]
    modified = dt.datetime.fromtimestamp(src.stat().st_mtime, dt.timezone.utc)
    late = bool(ingests) and modified > dt.datetime.fromisoformat(ingests[0])
    with manifest.stage(study_dir, "unseal", inputs=[src]) as record:
        (study_dir / UNSEALED).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, study_dir / UNSEALED)
        record["labels_locked_at"] = data["locked_at"]
        record["prior_modified"] = modified.isoformat(timespec="seconds")
        record["prior_modified_after_first_ingest"] = late
        record["outputs"] = [str(UNSEALED)]
    return {"labels_locked_at": data["locked_at"], "prior_modified": record["prior_modified"],
            "prior_modified_after_first_ingest": late}
