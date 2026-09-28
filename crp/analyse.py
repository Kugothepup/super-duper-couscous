"""crp analyse: every number the outputs will show, from the locked labels, in results/results.json.

Reads the measurement sample through load_measurement (so detail posts can't enter), the locked labels,
the frozen codebook and study.yaml, and writes results.json, validated by the Results schema. The same
seed gives a byte-identical file: it holds input hashes, not a timestamp (the run manifest has the time).
Interviews are counted in their own section and never enter a forum figure (D14).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from crp import hypotheses, language, manifest, stats, synthesis, thresholds
from crp.anonymise import POSTS
from crp.batch import INDEX, labels_file, read_index
from crp.codebook import CODEBOOK, frozen
from crp.io import InputError, atomic_write_text, read_jsonl, read_yaml, sha256_file, validate
from crp.keyness import METHOD as KEYNESS_METHOD
from crp.keyness import keyness
from crp.labels import LABELS_LOCK, labelled, locked
from crp.sample import MEASUREMENT, SUMMARY, candidates, load_detail, load_measurement
from crp.schemas import Codebook, Post, Results, Study
from crp.sensitivity import cap_weights, leave_one_out, without_caps
from crp.signals import SIGNALS
from crp.stats import BOOT_DRAWS, Engine, Record

RESULTS = Path("results") / "results.json"
AGREEMENT = Path("results") / "agreement.json"


def measurement_records(study_dir: Path, codebook: Codebook, coded: dict) -> list[Record]:
    per_aspect = [v.name for v in codebook.variables if v.applies_to == "measurement" and v.kind == "per_aspect"]
    if len(per_aspect) > 1:
        raise InputError(f"The codebook has {len(per_aspect)} per-aspect measurement variables "
                         f"({', '.join(per_aspect)}); the drivers need exactly one.")
    records = []
    for p in load_measurement(study_dir):
        values = coded.get(("measurement", p.post_id))
        if values is None:
            raise InputError(f"{p.post_id} is in the measurement sample but has no label. Run crp batch and code it.")
        records.append(Record(post_id=p.post_id, person=p.person_code, thread=p.thread_id, source=p.source,
                              search_term=p.search_term, time=p.timestamp, overall=values["overall"],
                              aspects=values.get(per_aspect[0], {}) if per_aspect else {}, stance=values.get("stance")))
    return records


def as_text(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def interviews(posts: list[Post], codebook: Codebook, coded: dict) -> dict | None:
    turns = [p for p in posts if p.source_type == "interview"]
    if not turns:
        return None
    said = [p for p in turns if p.role == "participant"]
    codes: dict[str, Counter] = {}
    n_coded = 0
    for p in said:
        values = coded.get(("detail", p.post_id))
        if values is None:
            continue
        n_coded += 1
        for v in codebook.variables:
            value = values.get(v.name)
            if v.applies_to != "detail" or value is None:
                continue
            c = codes.setdefault(v.name, Counter())
            c.update(value.keys() if isinstance(value, dict) else [as_text(value)])
    return {"transcripts": len({p.thread_id for p in turns}), "participants": len({p.person_code for p in said}),
            "turns": len(said), "coded_turns": n_coded, "codes": {k: dict(sorted(c.items())) for k, c in codes.items()}}


def switching(study_dir: Path, posts: list[Post]) -> list[tuple]:
    rows = {}
    for line in (study_dir / SIGNALS).read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["post_id"]] = r
    return [(p.timestamp, p.person_code, "switching_language" in rows[p.post_id]["flags"])
            for p in posts if p.source_type == "forum" and p.role == "participant" and p.timestamp
            and p.post_id in rows and rows[p.post_id]["words"] >= 8]


def agreement(study_dir: Path, lock: dict, codebook: Codebook) -> tuple[dict, dict, str | None]:
    path = study_dir / AGREEMENT
    if not path.exists():
        return {}, {}, None
    rep = json.loads(path.read_text(encoding="utf-8"))
    if rep.get("labels_locked_at") != lock["locked_at"] or rep.get("codebook_version") != codebook.version:
        return {}, {}, "results/agreement.json is from other labels or another codebook version, so it's ignored."
    return ({k: m["status"] for k, m in rep["metrics"].items()},
            {k: None if m["alpha"] is None else round(m["alpha"], 3) for k, m in rep["metrics"].items()}, None)


def thread_flags(study_dir: Path, posts: list[Post]) -> dict[str, dict[str, int]]:
    """Signal flag counts per forum thread, from crp signals' summary."""
    path = study_dir / "results" / "signals_summary.json"
    if not path.exists():
        return {}
    forum = {p.thread_id for p in posts if p.source_type == "forum"}
    return {tid: {k: v for k, v in s["flag_counts"].items() if k != "hesitation_cluster" and k != "long_response_gap"}
            for tid, s in json.loads(path.read_text(encoding="utf-8")).items() if tid in forum}


def collection_summary(study_dir: Path, posts: list[Post], summary: dict) -> dict:
    """How the material was found and checked: counts from the posts, the collection log, crp ingest,
    crp verify and crp sample, so the trust section shows only numbers in results.json."""
    from crp.io import read_csv
    from crp.schemas import COLLECTION_LOG_COLUMNS, CollectionLogRow
    forum = [p for p in posts if p.source_type == "forum"]
    log_path = study_dir / "collection_log.csv"
    log = read_csv(log_path, CollectionLogRow, COLLECTION_LOG_COLUMNS) if log_path.exists() else []
    sources = []
    for src in dict.fromkeys(p.source for p in forum):
        ps = [p for p in forum if p.source == src]
        sources.append({"source": src, "threads": len({p.thread_id for p in ps}), "posts": len(ps),
                        "capture": sorted({p.capture_method for p in ps}),
                        "search_terms": sorted({p.search_term for p in ps if p.search_term}),
                        "searches_logged": sum(r.source == src for r in log)})
    out: dict = {"forum_posts": len(forum), "forum_people": len({p.person_code for p in forum if p.role == "participant"}),
                 "forum_threads": len({p.thread_id for p in forum}),
                 "interview_turns": sum(p.source_type == "interview" for p in posts), "sources": sources}
    times = sorted(p.timestamp.date() for p in forum if p.timestamp)
    if times:
        out["window"] = (times[0], times[-1])
    if log:
        seen = [r.results_seen for r in log if r.results_seen is not None]
        kept = [r.kept for r in log if r.kept is not None]
        out["searches"] = {"logged": len(log), "neutral": sum(r.neutral for r in log),
                           "results_seen": sum(seen) if seen else None, "kept": sum(kept) if kept else None,
                           "kept_nothing": sum(r.kept == 0 for r in log)}
    verify_path, ingest_path = study_dir / "results" / "verify_report.json", study_dir / "results" / "ingest_report.json"
    if verify_path.exists():
        out["transcription"] = json.loads(verify_path.read_text(encoding="utf-8"))["counts"]
    if ingest_path.exists():
        rep = json.loads(ingest_path.read_text(encoding="utf-8"))
        cap, red = rep.get("captures", {}), rep.get("reddit", {})
        out["ingest"] = {"duplicates_dropped": sum((cap.get("duplicates_dropped") or {}).values()),
                         "promotional_flagged": cap.get("promotional_flagged", 0), "bots_removed": red.get("bots_removed", 0)}
    d = summary["detail"]
    if d.get("forum"):
        f = d["forum"]
        out["detail"] = {"candidates": f["candidates"], "selected": f["selected"], "budget": f["budget"],
                         "per_person": f["per_person"], "all_kept": f["all_kept"],
                         "echo_replies": summary["measurement"]["frame"]["left_out"].get("echo_reply", 0),
                         "interview_turns": d["interview_turns"]}
    return out


def themes_summary(study_dir: Path, checked: dict | None) -> dict | None:
    """results/themes.json, with each cluster linked to the insights that draw on it (build_report.py)."""
    from crp.themes import THEMES
    path = study_dir / THEMES
    if not path.exists():
        return None
    t = json.loads(path.read_text(encoding="utf-8"))
    insights = checked["files"]["insights"] if checked else []
    clusters, gaps = [], []
    for c in t["clusters"]:
        members = set(c["members"])
        linked = sorted(i.id for i in insights if members & set(i.post_ids))
        clusters.append({"cluster_id": c["cluster_id"], "size": c["size"], "coverage": c["coverage"],
                         "top_terms": c["top_terms"][:5], "dominated": c["dominated_by"] is not None,
                         "linked_insights": linked, "representative": c["representative"]})
        if not linked and c["coverage"] >= 5:
            gaps.append(c["cluster_id"])
    return {"source": t["source"], "method": t["method"], "silhouette": t["silhouette"], "n_items": t["n_items"],
            "clusters": clusters, "gaps": gaps}


def min_words(study_dir: Path, measurement: dict) -> int:
    """The sample's minimum words, from its summary, or from the run manifest for samples drawn before
    the summary recorded it."""
    if "min_words" in measurement["frame"]:
        return measurement["frame"]["min_words"]
    runs = [r for r in manifest.read(study_dir) if r.get("command") == "sample" and r.get("status") == "ok"]
    if not runs:
        raise InputError("Can't tell which minimum words the sample used. Run crp sample again.")
    return runs[-1]["settings"]["min_words"]


def analyse(study_dir: Path, seed: int | None = None, draws: int = BOOT_DRAWS) -> dict:
    study_dir = Path(study_dir)
    codebook, _ = frozen(study_dir)
    lock = locked(study_dir)
    study = read_yaml(study_dir / "study.yaml", Study)
    summary = json.loads((study_dir / SUMMARY).read_text(encoding="utf-8"))
    seed = int(summary["seed"]) if seed is None else seed
    if draws < 1:
        raise InputError(f"The number of re-draws must be 1 or more (got {draws}).")
    posts = read_jsonl(study_dir / POSTS, Post)
    coded = labelled(study_dir, read_index(study_dir))
    records = measurement_records(study_dir, codebook, coded)
    status_by, alpha, note = agreement(study_dir, lock, codebook)
    checked = synthesis.check(study_dir, codebook, posts) if (study_dir / synthesis.SYNTHESIS).is_dir() else None
    if checked and not checked["ok"]:
        raise InputError(f"The synthesis has {len(checked['errors'])} error(s). Run crp validate, fix them, "
                         "then analyse again.")
    inputs = [study_dir / f for f in (POSTS, MEASUREMENT, SUMMARY, INDEX, LABELS_LOCK, CODEBOOK, Path("study.yaml"), SIGNALS)]
    inputs += sorted(p for p in (study_dir / synthesis.SYNTHESIS).glob("*") if p.is_file()) if checked else []
    with manifest.stage(study_dir, "analyse", inputs=inputs, seed=seed, codebook_version=codebook.version,
                        coder_model=lock["coder_model"]) as record:
        m = summary["measurement"]
        n_people = len({r.person for r in records})
        sample_status = thresholds.result_status(n_people, len(records))
        data: dict = {"study_id": study.id, "seed": seed, "bootstrap_draws": draws,
                      "inputs": {str(p.relative_to(study_dir)): sha256_file(p) for p in inputs},
                      "codebook_version": codebook.version, "coder_model": lock["coder_model"],
                      "agreement_status": status_by, "alpha": alpha,
                      "sample": {"n_items": len(records), "n_people": n_people,
                                 "n_threads": len({r.thread for r in records}), "status": sample_status,
                                 "target": m["target"], "eligible": m["frame"]["eligible"],
                                 "person_cap": m["frame"]["person_cap"], "thread_cap_pct": m["thread_cap_pct"],
                                 "thread_cap_loosened": m["thread_cap_pct"] != thresholds.THREAD_CAP_PCT},
                      "interviews": interviews(posts, codebook, coded)}
        eng = None
        signal_rows = {r["post_id"]: r for r in (json.loads(line) for line in
                       (study_dir / SIGNALS).read_text(encoding="utf-8").splitlines() if line.strip())}
        forum_said = [p for p in posts if p.source_type == "forum" and p.role == "participant"]
        data["language"] = {"phrases": language.phrases([(p.text, p.person_code) for p in forum_said]),
                            "signal_rates": language.signal_rates(posts, signal_rows),
                            "threads": thread_flags(study_dir, posts)}
        data["collection"] = collection_summary(study_dir, posts, summary)
        data["themes"] = themes_summary(study_dir, checked)
        if records:
            eng = Engine(records, draws, seed)
            data["headline"] = stats.headline(eng)
            data |= stats.aspects(eng)
            data["stance"] = stats.stance(eng, study.stance_target)
            data["event"] = stats.event(eng, study.event_date)
            data["direction"] = stats.direction(eng, switching(study_dir, posts))
            data["by_source"], data["dominant_source"] = stats.by_source(eng)
            eligible = Counter(p.person_code for p in candidates(posts, min_words(study_dir, m))[0])
            weights = cap_weights(records, eligible, m["frame"]["person_cap"], m["threads"])
            data["sensitivity"] = leave_one_out(records) | {"without_caps": without_caps(records, weights)}
            text = {p.post_id: p.text for p in posts}
            if sample_status == "full":
                data["keyness"] = {"shown": True, "method": KEYNESS_METHOD} | keyness(
                    [(text[r.post_id], r.person, r.overall) for r in records])
            else:
                data["keyness"] = {"shown": False, "method": KEYNESS_METHOD,
                                   "reason": f"hidden: the sample is below the early-signal threshold "
                                             f"({thresholds.MIN_ITEMS_FOR_FULL} comments from "
                                             f"{thresholds.MIN_PEOPLE_FOR_RANGES} people) (D6)"}
        warnings = checked["warnings"] if checked else []
        if checked:
            neg_rate = {a["aspect"]: a["negative_rate"].get("pct") for a in data.get("aspects", [])}
            detail_posts = [post for _, post in load_detail(study_dir)]
            data["synthesis"] = synthesis.summarise(checked, neg_rate, codebook, data.get("drivers", [])[:3],
                                                    detail_posts, {k: v["flags"] for k, v in signal_rows.items()})
            if checked["files"]["hypotheses"]:
                scored = hypotheses.score(checked["files"]["hypotheses"], checked["nuggets"], eng, len(records),
                                          n_people, draws, seed)
                if scored["errors"]:
                    raise InputError("Hypothesis signals don't fit the sample:\n" + "\n".join(scored["errors"]))
                data["hypotheses"] = scored["hypotheses"]
                warnings += scored["warnings"]
        results = validate(Results, data, "results.json")
        atomic_write_text(study_dir / RESULTS, json.dumps(results.model_dump(mode="json", exclude_none=True),
                                                          indent=2, ensure_ascii=False) + "\n")
        record["outputs"] = [str(RESULTS)]
        record["settings"] = {"draws": draws}
    return {"results": results, "agreement_note": note, "warnings": warnings}
