"""crp round and crp topup: add to a study after coding, in rounds (D35, D37).

crp round closes the current round once its labels are locked. It keeps the round whole in rounds/<n>/:
the coded state moves there (samples, batches, labels, labels.lock, the agreement sheet and codes, and
results/agreement.json), and the results, posts, signals, synthesis and codebook lock are copied there for
comparison. raw/, the codebook, the sealed prior and the synthesis stay where they are. Then new threads
go into raw/ as usual and the stages run again from crp ingest: crp sample keeps the seed, and crp batch
reuses the last round's labels for items the coder would see unchanged, so only new picks are coded.

crp reset starts a study over from its sources, when Steeve asks: every generated file moves into
archive/<time>/, and raw/, the sealed prior, study.yaml, the collection log and the codebook draft stay.
The codebook lock moves too, so the draft can change; the run manifest stays and records the reset. A prior
already unsealed stays seen: the manifest keeps that unseal.

crp topup names posts to add to the detail selection, with a reason, for example to explain a driver few
coded posts cover (D37). It only works before this round's batches exist, so after coding it needs a new
round first. The top-ups are kept in topup.jsonl, and every later sample adds them to the detail
selection. The measurement sample, and so every percentage, is unaffected.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from crp import manifest
from crp.anonymise import POSTS
from crp.batch import BATCHES, LABELS, LABELS_LOCK
from crp.codebook import LOCK as CODEBOOK_LOCK
from crp.io import InputError, atomic_write_text, read_jsonl
from crp.labels import locked
from crp.sample import ROUNDS, SUMMARY, TOPUP, read_topup
from crp.schemas import Post
from crp.signals import SIGNALS

CURRENT = Path("round.json")  # this round's number and why it started
MOVED = [Path("samples"), BATCHES, LABELS, LABELS_LOCK, Path("human")]  # made in the round, redone in the next
AGREEMENT = Path("results") / "agreement.json"
COPIED = [POSTS, SIGNALS, CODEBOOK_LOCK, Path("synthesis")]


def current(study_dir: Path) -> dict:
    path = Path(study_dir) / CURRENT
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"round": 1, "reason": "first round"}


def closed(study_dir: Path) -> list[dict]:
    """Every closed round's round.json, oldest first."""
    folder = Path(study_dir) / ROUNDS
    dirs = sorted((d for d in folder.glob("*") if (d / "round.json").exists()), key=lambda d: int(d.name)) \
        if folder.is_dir() else []
    return [json.loads((d / "round.json").read_text(encoding="utf-8")) for d in dirs]


def last_sample_settings(study_dir: Path) -> dict:
    runs = [r for r in manifest.read(study_dir) if r.get("command") == "sample" and r.get("status") == "ok"]
    return runs[-1].get("settings", {}) if runs else {}


def start_round(study_dir: Path, reason: str) -> dict:
    study_dir = Path(study_dir)
    if not reason.strip():
        raise InputError("Say why the new round starts, e.g. --reason \"added three threads from r/notetaking\".")
    if not (study_dir / LABELS_LOCK).exists():
        raise InputError("This round's labels aren't locked yet, so there's nothing to close. To add threads before "
                         "coding, put them in raw/ and run the stages again from crp ingest; no new round is needed.")
    lock = locked(study_dir)
    this = current(study_dir)
    dest = study_dir / ROUNDS / str(this["round"])
    if dest.exists():
        raise InputError(f"{dest} already exists. Rounds are never overwritten.")
    settings = last_sample_settings(study_dir)
    with manifest.stage(study_dir, "round", inputs=[study_dir / LABELS_LOCK]) as record:
        dest.mkdir(parents=True)
        if (study_dir / "results").is_dir():
            shutil.copytree(study_dir / "results", dest / "results",
                            ignore=shutil.ignore_patterns("internal", "run_manifest.json"))
        for rel in COPIED:
            src = study_dir / rel
            if src.is_dir():
                shutil.copytree(src, dest / rel)
            elif src.exists():
                shutil.copy2(src, dest / rel)
        for rel in MOVED:
            if (study_dir / rel).exists():
                shutil.move(study_dir / rel, dest / rel)
        if (study_dir / AGREEMENT).exists():
            (study_dir / AGREEMENT).unlink()  # its copy went to dest/results/ with the other results
        summary = {**this, "closed": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "labels_locked_at": lock["locked_at"], "coder_model": lock["coder_model"],
                   "codebook_version": lock["codebook_version"], "items": lock["items"],
                   "reused_items": lock.get("reused_items", 0),
                   "posts": len(read_jsonl(dest / POSTS, Post)) if (dest / POSTS).exists() else None,
                   "sample_settings": settings}
        atomic_write_text(dest / "round.json", json.dumps(summary, indent=2) + "\n")
        nxt = {"round": this["round"] + 1, "reason": reason.strip(),
               "started": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        atomic_write_text(study_dir / CURRENT, json.dumps(nxt, indent=2) + "\n")
        record["closed_round"] = this["round"]
        record["reason"] = nxt["reason"]
        record["outputs"] = [str(dest.relative_to(study_dir)), str(CURRENT)]
    return {"closed": this["round"], "next": nxt["round"], "folder": str(dest.relative_to(study_dir)),
            "settings": settings}


def topup(study_dir: Path, post_ids: list[str], reason: str) -> dict:
    study_dir = Path(study_dir)
    if not reason.strip():
        raise InputError("Say why these posts are added, e.g. --reason \"explain the sync driver\".")
    if (study_dir / BATCHES).is_dir() and any((study_dir / BATCHES).iterdir()):
        raise InputError("This round's batches already exist, so its detail selection is fixed. Start a new round "
                         "first (crp round --reason \"top-up: ...\"), then add the posts.")
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    have = {t["post_id"] for t in read_topup(study_dir)}
    bad = [i for i in post_ids if i not in posts or posts[i].source_type != "forum"]
    if bad:
        raise InputError(f"Not forum posts in posts.jsonl: {', '.join(bad)}. Top-ups are forum posts; interviews "
                         "are read in full already.")
    new = [i for i in dict.fromkeys(post_ids) if i not in have]
    if not new:
        raise InputError("Those posts are already top-ups.")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with manifest.stage(study_dir, "topup") as record:
        with (study_dir / TOPUP).open("a", encoding="utf-8") as f:
            for i in new:
                f.write(json.dumps({"post_id": i, "reason": reason.strip(), "added": now}) + "\n")
        record["posts"] = new
        record["reason"] = reason.strip()
        record["outputs"] = [str(TOPUP)]
    stale = (study_dir / SUMMARY).exists()
    return {"added": new, "already": [i for i in post_ids if i in have], "sample_stale": stale}


GENERATED = [POSTS, SIGNALS, Path("samples"), BATCHES, LABELS, LABELS_LOCK, Path("human"), Path("synthesis"),
             CODEBOOK_LOCK, ROUNDS, CURRENT, TOPUP]


def reset(study_dir: Path) -> dict:
    """Move every generated file into archive/<time>/; keep the sources, the prior and the codebook draft."""
    study_dir = Path(study_dir)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = study_dir / "archive" / stamp
    moved = [rel for rel in GENERATED if (study_dir / rel).exists()]
    results = study_dir / "results"
    kept_results = [f for f in results.iterdir() if f.name != manifest.MANIFEST.name] if results.is_dir() else []
    if not moved and not kept_results:
        raise InputError("Nothing to reset: the study has no generated files yet.")
    with manifest.stage(study_dir, "reset") as record:
        dest.mkdir(parents=True)
        for rel in moved:
            shutil.move(study_dir / rel, dest / rel)
        if kept_results:
            (dest / "results").mkdir()
            for f in kept_results:
                shutil.move(f, dest / "results" / f.name)
            if (results / manifest.MANIFEST.name).exists():  # the history stays live; the archive gets a copy
                shutil.copy2(results / manifest.MANIFEST.name, dest / "results" / manifest.MANIFEST.name)
        record["archived_to"] = str(dest.relative_to(study_dir))
        record["moved"] = [str(r) for r in moved] + [f"results/{f.name}" for f in kept_results]
    return {"archive": str(dest.relative_to(study_dir)), "moved": record["moved"]}
