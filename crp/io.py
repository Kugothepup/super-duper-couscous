"""Reading and writing study files, with validation errors that name the file, line and field."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class InputError(Exception):
    """A problem with a study file, worded for the person who has to fix it."""


def describe(err: ValidationError, where: str) -> str:
    lines = []
    for e in err.errors():
        field = ".".join(str(p) for p in e["loc"])
        msg = e["msg"].removeprefix("Value error, ")
        if e["type"] == "extra_forbidden":
            msg = "unknown field"
        elif e["type"] == "missing":
            msg = "missing"
        lines.append(f"{where}: {field + ': ' if field else ''}{msg}")
    return "\n".join(lines)


def validate(model: type[M], data: object, where: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as err:
        raise InputError(describe(err, where)) from None


def read_yaml(path: Path, model: type[M]) -> M:
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise InputError(f"{path}: not valid YAML ({err})") from None
    return validate(model, data, str(path))


def read_jsonl(path: Path, model: type[M]) -> list[M]:
    path = Path(path)
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as err:
            raise InputError(f"{path} line {n}: not valid JSON ({err.msg})") from None
        rows.append(validate(model, data, f"{path} line {n}"))
    return rows


def read_csv(path: Path, model: type[M], columns: list[str]) -> list[M]:
    """Rows of a CSV whose header must be exactly `columns`. Line numbers count the header as line 1."""
    path = Path(path)
    with path.open(encoding="utf-8-sig", newline="") as f:  # -sig: tolerate the BOM Excel adds
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            raise InputError(f"{path}: the header must be {','.join(columns)} "
                             f"(found {','.join(reader.fieldnames or [])})")
        rows = []
        for row in reader:
            n = reader.line_num
            if None in row:
                raise InputError(f"{path} line {n}: more values than columns")
            data = {k: v for k, v in row.items() if v is not None and v.strip() != ""}
            rows.append(validate(model, data, f"{path} line {n}"))
    return rows


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_yaml(path: Path, model: BaseModel) -> None:
    text = yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    atomic_write_text(path, text)


def write_jsonl(path: Path, rows: Iterable[BaseModel]) -> None:
    text = "".join(json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in rows)
    atomic_write_text(path, text)


def write_csv_header(path: Path, columns: list[str]) -> None:
    atomic_write_text(path, ",".join(columns) + "\n")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
