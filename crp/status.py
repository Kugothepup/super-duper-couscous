"""crp status: where a study is up to, stage by stage, and what comes next.

Each stage is one of: done; to do (a crp command can run now); waiting on Steeve (a decision, the prior,
the agreement sheet, more threads); waiting on Claude (captures, the codebook draft, blind coding, the
synthesis); blocked (something must be fixed first); skipped (not needed, e.g. no prior means going in
blind); or stale (an input changed since the command ran, so it must run again). Staleness comes from the
run manifest: each command recorded the sha256 of its inputs, and a changed or missing input means stale.
It only reads files; it never runs a stage. It checks that sealed/prior.md exists, and never opens it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from crp import manifest
from crp.analyse import RESULTS
from crp.anonymise import POSTS
from crp.batch import BATCHES, INDEX, LABELS, labels_file
from crp.codebook import CODEBOOK, LOCK as CODEBOOK_LOCK
from crp.ingest import INGESTED
from crp.io import InputError, read_csv, read_jsonl, sha256_file
from crp.labels import LABELS_LOCK, PRIOR, UNSEALED, locked
from crp.sample import SUMMARY, read_topup
from crp.schemas import COLLECTION_LOG_COLUMNS, CollectionLogRow, Post
from crp.signals import SIGNALS
from crp.synthesis import OBSERVATIONS, SYNTHESIS
from crp.verify import REPORT as VERIFY_REPORT

SOURCE_EXT = {".txt", ".md", ".html", ".htm", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
STATES = ("done", "to do", "waiting on Steeve", "waiting on Claude", "blocked", "stale", "skipped")
DEPENDS = {"ingest": ["sources"], "verify": ["ingest"], "anonymise": ["verify"], "signals": ["anonymise"],
           "sample": ["signals"], "batch": ["sample", "codebook"], "blind coding": ["batch"],
           "labels lock": ["blind coding"], "unseal": ["labels lock"], "agreement": ["labels lock"],
           "synthesis": ["labels lock"], "analyse": ["labels lock"], "build": ["analyse"]}


@dataclass
class Stage:
    name: str
    state: str
    why: str = ""
    next: str = ""  # what to do, when the stage isn't done


def last_run(runs: list[dict], command: str) -> dict | None:
    ok = [r for r in runs if r.get("command") == command and r.get("status") == "ok"]
    return ok[-1] if ok else None


def changed(study_dir: Path, run: dict) -> list[str]:
    """Inputs recorded by a run that have changed or gone since."""
    return [k for k, h in run.get("inputs", {}).items()
            if not (study_dir / k).exists() or sha256_file(study_dir / k) != h]


def ran(study_dir: Path, runs: list[dict], command: str, name: str, next_step: str) -> Stage:
    """done if the command ran and its inputs are unchanged, stale if they changed, to do if it never ran."""
    run = last_run(runs, command)
    if run is None:
        return Stage(name, "to do", next=next_step)
    moved = changed(study_dir, run)
    if moved:
        return Stage(name, "stale", f"changed since it ran: {', '.join(moved[:3])}", next_step)
    return Stage(name, "done")


def sources(study_dir: Path) -> Stage:
    raw = study_dir / "raw"
    if not raw.is_dir():
        return Stage("sources", "waiting on Steeve", "nothing in raw/ yet", "add threads (crp paste), exports or transcripts")
    captured = set()
    for cp in (raw / "capture").glob("*.json") if (raw / "capture").is_dir() else []:
        try:
            captured.add(json.loads(cp.read_text(encoding="utf-8")).get("source_file"))
        except json.JSONDecodeError:
            return Stage("sources", "blocked", f"capture/{cp.name} isn't valid JSON", "fix the capture file")
    originals = [f.name for f in raw.iterdir() if f.is_file() and f.suffix.lower() in SOURCE_EXT]
    uncaptured = sorted(set(originals) - captured)
    exports = [f for sub in ("reddit", "interviews") for f in (raw / sub).rglob("*") if f.is_file()] \
        if raw.is_dir() else []
    if uncaptured:
        return Stage("sources", "waiting on Claude", f"no capture file for {', '.join(uncaptured[:3])}",
                     "write their capture files (reference/capture.md), or use crp paste for Reddit pages")
    if not captured and not exports:
        return Stage("sources", "waiting on Steeve", "nothing in raw/ yet", "add threads (crp paste), exports or transcripts")
    return Stage("sources", "done", f"{len(captured)} capture(s), {len(exports)} export or transcript file(s)")


def ingest_stage(study_dir: Path, runs: list[dict]) -> Stage:
    run = last_run(runs, "ingest")
    if run is None:
        return Stage("ingest", "to do", next="crp ingest")
    raw = study_dir / "raw"
    now = {str(p.relative_to(study_dir)) for sub in ("capture", "reddit", "interviews")
           for p in (raw / sub).rglob("*") if p.is_file()} if raw.is_dir() else set()
    added = sorted(now - set(run.get("inputs", {})))
    moved = changed(study_dir, run)
    if added or moved:
        return Stage("ingest", "stale", f"new or changed in raw/: {', '.join((added + moved)[:3])}", "crp ingest")
    return Stage("ingest", "done")


def verify_stage(study_dir: Path) -> Stage:
    path = study_dir / VERIFY_REPORT
    if not path.exists():
        return Stage("verify", "to do", next="crp verify")
    rep = json.loads(path.read_text(encoding="utf-8"))
    if not (study_dir / INGESTED).exists() or rep.get("ingested_sha256") != sha256_file(study_dir / INGESTED):
        return Stage("verify", "stale", "raw/ingested.jsonl changed since", "crp verify")
    if not rep.get("ok"):
        c = rep.get("counts", {})
        return Stage("verify", "waiting on Claude", f"{c.get('failed', 0)} failed, {c.get('tidied', 0)} tidied",
                     "copy the text exactly in the capture files, then crp ingest and crp verify")
    return Stage("verify", "done", ", ".join(f"{k} {v}" for k, v in sorted(rep.get("counts", {}).items())))


def codebook_stage(study_dir: Path) -> Stage:
    if not (study_dir / CODEBOOK).exists():
        return Stage("codebook", "waiting on Claude", "no codebook.yaml yet", "draft codebook.yaml (reference/codebook.md)")
    if not (study_dir / CODEBOOK_LOCK).exists():
        return Stage("codebook", "waiting on Steeve", "drafted, not approved", "Steeve approves it, then crp codebook freeze")
    lock = json.loads((study_dir / CODEBOOK_LOCK).read_text(encoding="utf-8"))
    if sha256_file(study_dir / CODEBOOK) != lock["sha256"]:
        return Stage("codebook", "blocked", "codebook.yaml changed after it was frozen",
                     "undo the change, or Steeve decides on a new version (crp codebook freeze --new-version)")
    return Stage("codebook", "done", f"version {lock['version']} frozen")


def coding_stages(study_dir: Path, runs: list[dict]) -> list[Stage]:
    if not (study_dir / INDEX).exists():
        return [Stage("batch", "to do", next="crp batch"), Stage("blind coding", "to do", "after crp batch"),
                Stage("labels lock", "to do", "after the blind coding")]
    out = [ran(study_dir, runs, "batch", "batch", "crp batch")]
    index = json.loads((study_dir / INDEX).read_text(encoding="utf-8"))
    todo = [b["batch"] for b in index["batches"] if "reused" not in b and not (study_dir / labels_file(b["batch"])).exists()]
    reused = sum(len(b["items"]) for b in index["batches"] if "reused" in b)
    if todo:
        out.append(Stage("blind coding", "waiting on Claude", f"not coded yet: {', '.join(todo)}",
                         "a blind-coder agent per batch, given only its two paths"))
    else:
        out.append(Stage("blind coding", "done", f"{reused} item(s) reused from the last round" if reused else ""))
    if (study_dir / LABELS_LOCK).exists():
        try:
            data = locked(study_dir)
            out.append(Stage("labels lock", "done", f"coder {data['coder_model']}"))
        except InputError as err:
            out.append(Stage("labels lock", "blocked", str(err), "run crp batch or re-code as the message says"))
    else:
        out.append(Stage("labels lock", "to do", "after the blind coding" if todo else "",
                         "crp labels validate, then crp labels lock --coder-model <model>"))
    return out


def unseal_stage(study_dir: Path) -> Stage:
    if not (study_dir / PRIOR).exists():  # existence only: sealed/ is never opened here
        return Stage("unseal", "skipped", "no sealed prior: Steeve went in blind")
    if (study_dir / UNSEALED).exists():
        return Stage("unseal", "done")
    return Stage("unseal", "to do", next="crp unseal (after the labels are locked)")


def agreement_stage(study_dir: Path) -> Stage:
    human = study_dir / "human"
    if not (human / "agreement_sheet.csv").exists():
        return Stage("agreement", "to do", next="crp agreement export")
    if not (human / "human_labels.csv").exists():
        return Stage("agreement", "waiting on Steeve", "the sheet isn't coded yet",
                     "Steeve codes human/agreement_sheet.csv and saves it as human/human_labels.csv")
    path = study_dir / "results" / "agreement.json"
    if not path.exists():
        return Stage("agreement", "to do", next="crp agreement score")
    statuses = {m.get("status") for m in json.loads(path.read_text(encoding="utf-8")).get("metrics", {}).values()}
    worst = next((s for s in ("unverified", "tentative", "verified") if s in statuses), "unverified")
    return Stage("agreement", "done", f"lowest status: {worst}")


def synthesis_stage(study_dir: Path) -> Stage:
    if not (study_dir / OBSERVATIONS).exists():
        return Stage("synthesis", "waiting on Claude", "no observations yet",
                     "write synthesis/ (reference/synthesis.md), checking with crp validate")
    files = sorted(p.name for p in (study_dir / SYNTHESIS).glob("*") if p.is_file())
    return Stage("synthesis", "done", ", ".join(files))


def status(study_dir: Path) -> dict:
    study_dir = Path(study_dir)
    runs = manifest.read(study_dir)
    stages = [Stage("set up", "done")]
    log_path = study_dir / "collection_log.csv"
    try:
        log = read_csv(log_path, CollectionLogRow, COLLECTION_LOG_COLUMNS) if log_path.exists() else []
        stages.append(Stage("collection log", "done", f"{len(log)} search(es), {sum(r.neutral for r in log)} neutral")
                      if log else Stage("collection log", "waiting on Steeve", "no searches logged",
                                        "log every search in collection_log.csv"))
    except InputError as err:
        stages.append(Stage("collection log", "blocked", str(err).splitlines()[0], "fix collection_log.csv"))
    stages.append(Stage("prior", "done", "sealed") if (study_dir / PRIOR).exists()
                  else Stage("prior", "skipped", "none written: going in blind"))
    stages.append(sources(study_dir))
    stages.append(ingest_stage(study_dir, runs))
    stages.append(verify_stage(study_dir))
    stages.append(ran(study_dir, runs, "anonymise", "anonymise", "crp anonymise"))
    stages.append(ran(study_dir, runs, "signals", "signals", "crp signals"))
    if (study_dir / SUMMARY).exists() and (study_dir / POSTS).exists():
        summary = json.loads((study_dir / SUMMARY).read_text(encoding="utf-8"))
        same = summary["posts_sha256"] == sha256_file(study_dir / POSTS)
        stages.append(Stage("sample", "done", f"seed {summary['seed']}") if same else
                      Stage("sample", "stale", "posts.jsonl changed since", "crp sample"))
    else:
        stages.append(Stage("sample", "to do", next="crp sample"))
    stages.append(codebook_stage(study_dir))
    stages += coding_stages(study_dir, runs)
    stages.append(unseal_stage(study_dir))
    stages.append(agreement_stage(study_dir))
    stages.append(synthesis_stage(study_dir))
    stages.append(ran(study_dir, runs, "analyse", "analyse", "crp analyse") if (study_dir / RESULTS).exists()
                  else Stage("analyse", "to do", next="crp analyse"))
    stages.append(ran(study_dir, runs, "build", "build", "crp build, then crp check-numbers")
                  if (study_dir / "results" / "dashboard.html").exists() else Stage("build", "to do", next="crp build"))
    # a stage isn't done while a stage it depends on isn't (stages come in dependency order)
    by_name = {s.name: s for s in stages}
    for s in stages:
        open_deps = [d for d in DEPENDS.get(s.name, []) if d in by_name and by_name[d].state not in ("done", "skipped")]
        if s.state == "done" and open_deps:
            s.state, s.why = "stale", f"waits on {open_deps[0]}"
    rnd = json.loads((study_dir / "round.json").read_text(encoding="utf-8")) if (study_dir / "round.json").exists() \
        else {"round": 1, "reason": "first round"}
    nxt = next((s for s in stages if s.state not in ("done", "skipped") and s.next), None)
    return {"round": rnd, "topups": len(read_topup(study_dir)), "stages": stages,
            "next": {"stage": nxt.name, "state": nxt.state, "do": nxt.next} if nxt else None,
            "posts": len(read_jsonl(study_dir / POSTS, Post)) if (study_dir / POSTS).exists() else None}
