"""crp new: set up a study folder. Safe to re-run; it never overwrites a file."""
from __future__ import annotations

from pathlib import Path

from crp import manifest
from crp.io import InputError, read_csv, read_yaml, write_csv_header, write_yaml
from crp.schemas import COLLECTION_LOG_COLUMNS, CollectionLogRow, Study

STUDY_DIRS = ("raw", "sealed", "samples", "batches", "labels", "human", "results")


def new_study(root: Path, study: Study) -> tuple[Path, list[str]]:
    """Create studies/<id>/ with study.yaml, an empty collection log and the stage folders."""
    study_dir = Path(root) / study.id
    yaml_path = study_dir / "study.yaml"
    log_path = study_dir / "collection_log.csv"
    notes = []

    if yaml_path.exists():
        existing = read_yaml(yaml_path, Study)
        if existing.model_dump(exclude={"created"}) != study.model_dump(exclude={"created"}):
            raise InputError(f"{yaml_path} already exists with different settings. "
                             "Edit it by hand, or choose a new study id.")
        notes.append(f"{study_dir} is already set up; nothing was overwritten.")
    if log_path.exists():
        read_csv(log_path, CollectionLogRow, COLLECTION_LOG_COLUMNS)

    study_dir.mkdir(parents=True, exist_ok=True)
    with manifest.stage(study_dir, "new") as record:
        created = []
        for d in STUDY_DIRS:
            if not (study_dir / d).is_dir():
                (study_dir / d).mkdir()
                created.append(f"{d}/")
        if not log_path.exists():
            write_csv_header(log_path, COLLECTION_LOG_COLUMNS)
            created.append(log_path.name)
        if not yaml_path.exists():
            write_yaml(yaml_path, study)
            created.append(yaml_path.name)
        record["outputs"] = created

    if study.needs_stance_target:
        notes.append("News and topic studies need --stance-target (the proposition people are for or against). "
                     "Without it, only sentiment is measured.")
    return study_dir, notes
