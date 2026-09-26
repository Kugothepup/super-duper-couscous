"""The run manifest: one record per command run, so any result can be traced and reproduced.

Each record holds the command, start and end time, time taken, seed, sha256 of every input,
package versions, codebook version and coder model. Records are appended to
studies/<id>/results/run_manifest.json and never rewritten.
"""
from __future__ import annotations

import datetime as dt
import json
import platform
import time
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Iterator, Sequence

from crp.io import InputError, atomic_write_text, sha256_file

MANIFEST = Path("results") / "run_manifest.json"
PACKAGES = ("crp", "numpy", "pandas", "pydantic", "PyYAML", "rapidfuzz", "krippendorff", "scipy",
            "Jinja2", "scikit-learn")


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {"python": platform.python_version()}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def read(study_dir: Path) -> list[dict]:
    path = Path(study_dir) / MANIFEST
    if not path.exists():
        return []
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise InputError(f"{path}: not valid JSON ({err.msg})") from None
    if not isinstance(records, list):
        raise InputError(f"{path}: expected a list of stage records")
    return records


def append(study_dir: Path, record: dict) -> None:
    records = read(study_dir)
    records.append(record)
    atomic_write_text(Path(study_dir) / MANIFEST, json.dumps(records, indent=2, ensure_ascii=False) + "\n")


@contextmanager
def stage(study_dir: Path, command: str, *, inputs: Sequence[Path] = (), seed: int | None = None,
          codebook_version: str | None = None, coder_model: str | None = None) -> Iterator[dict]:
    """Record one command run. Callers may add keys (e.g. "outputs") to the yielded record."""
    study_dir = Path(study_dir)
    hashes = {}
    for p in inputs:
        p = Path(p)
        key = str(p.relative_to(study_dir)) if p.is_relative_to(study_dir) else str(p)
        hashes[key] = sha256_file(p)
    record = {"command": command, "started": _now(), "ended": None, "seconds": None, "status": "running",
              "seed": seed, "inputs": hashes, "codebook_version": codebook_version, "coder_model": coder_model,
              "packages": package_versions()}
    t0 = time.perf_counter()
    try:
        yield record
        record["status"] = "ok"
    except BaseException as err:
        record["status"] = "failed"
        record["error"] = f"{type(err).__name__}: {err}"
        raise
    finally:
        record["ended"] = _now()
        record["seconds"] = round(time.perf_counter() - t0, 3)
        if study_dir.exists():
            append(study_dir, record)
