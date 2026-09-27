"""crp codebook freeze: check codebook.yaml and lock it before any coding.

codebook.lock holds the codebook's version and sha256. Every later stage (batch, labels,
agreement) calls frozen() and refuses to run if codebook.yaml no longer matches the lock.
A locked codebook changes only as a new version, and that is Steeve's call: freeze
--new-version moves the old batches, labels and agreement files to superseded/, so every
item is coded again under the new version.

Checks beyond the schema: the codebook's study type matches study.yaml; a codebook that codes
the measurement sample has `overall` (single, ordinal, -2 to 2), the headline's variable (D8, D13);
news and topic studies also have `stance` (single, ordinal, -2 to 2, null when no position is
expressed) (D13).
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from crp import manifest
from crp.io import InputError, atomic_write_text, read_yaml, sha256_file
from crp.schemas import Codebook, Study

CODEBOOK = Path("codebook.yaml")
LOCK = Path("codebook.lock")
SCALE = [-2, -1, 0, 1, 2]
SUPERSEDED = Path("superseded")
# made under a codebook version: moved aside when a new version is frozen
CODED = [Path("batches"), Path("labels"), Path("labels.lock"), Path("human"), Path("results") / "agreement.json"]


def check_design(codebook: Codebook, study: Study) -> None:
    if codebook.study_type != study.type:
        raise InputError(f"The codebook is for a {codebook.study_type} study, but study.yaml says {study.type}.")
    measured = {v.name: v for v in codebook.variables if v.applies_to == "measurement"}
    need = {"overall": False}
    if study.type in ("news", "topic"):
        need["stance"] = True
    if not measured:
        return
    for name, nullable in need.items():
        v = measured.get(name)
        if v is None:
            raise InputError(f"The codebook codes the measurement sample, so it needs a '{name}' variable "
                             f"(applies_to: measurement).")
        if v.kind != "single" or v.level != "ordinal" or v.values != SCALE or v.nullable != nullable:
            null_rule = "null when no position is expressed" if nullable else "not nullable"
            raise InputError(f"'{name}' must be a single, ordinal variable with values {SCALE}, {null_rule}.")


def read_lock(study_dir: Path) -> dict | None:
    path = study_dir / LOCK
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def frozen(study_dir: Path) -> tuple[Codebook, dict]:
    """The frozen codebook and its lock. Refuses if there is no lock, or codebook.yaml has changed since."""
    study_dir = Path(study_dir)
    lock = read_lock(study_dir)
    if lock is None:
        raise InputError("The codebook isn't frozen yet. Run crp codebook freeze once Steeve has approved it.")
    if not (study_dir / CODEBOOK).exists() or sha256_file(study_dir / CODEBOOK) != lock["sha256"]:
        raise InputError(f"codebook.yaml has changed since version {lock['version']} was frozen. A frozen codebook "
                         "changes only as a new version with every item coded again, and that is Steeve's call "
                         "(crp codebook freeze --new-version).")
    return read_yaml(study_dir / CODEBOOK, Codebook), lock


def _supersede(study_dir: Path, old_version: str) -> list[str]:
    present = [p for p in CODED if (study_dir / p).exists()]
    if not present:
        return []
    dest = study_dir / SUPERSEDED / f"codebook-v{old_version}"
    n = 1
    while dest.exists():
        n += 1
        dest = study_dir / SUPERSEDED / f"codebook-v{old_version}-{n}"
    for p in present:
        (dest / p).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(study_dir / p), str(dest / p))
    return [str(p) for p in present] + [str(dest.relative_to(study_dir))]


def freeze(study_dir: Path, new_version: bool = False) -> dict:
    study_dir = Path(study_dir)
    path = study_dir / CODEBOOK
    if not path.exists():
        raise InputError(f"No {path}. Draft the codebook first.")
    codebook = read_yaml(path, Codebook)
    check_design(codebook, read_yaml(study_dir / "study.yaml", Study))
    digest = sha256_file(path)
    old = read_lock(study_dir)
    if old and old["sha256"] == digest:
        return old | {"unchanged": True}
    if old and not new_version:
        raise InputError(f"The codebook was frozen as version {old['version']} and has changed since. Changing it "
                         "means a new version and coding every item again, which is Steeve's call. If he agrees, "
                         "give it a new version number and run crp codebook freeze --new-version.")
    if old and codebook.version == old["version"]:
        raise InputError(f"The changed codebook still says version {old['version']}. Give it a new version number.")
    with manifest.stage(study_dir, "codebook freeze", inputs=[path], codebook_version=codebook.version) as record:
        moved = _supersede(study_dir, old["version"]) if old else []
        lock = {"version": codebook.version, "sha256": digest,
                "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        if old:
            lock["replaces"] = old["version"]
            record["superseded"] = moved
        atomic_write_text(study_dir / LOCK, json.dumps(lock, indent=2) + "\n")
        record["outputs"] = [str(LOCK)]
    return lock | {"superseded": moved}
