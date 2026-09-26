#!/usr/bin/env python3
"""Validate coded nuggets, and insights, sentiment records and outlook if present.

Checks every nugget quote really appears verbatim in the turns it cites (ignoring
case and punctuation; "..." marks an elision), that fields use the allowed values,
and that insight confidence matches how many transcripts support it.

Usage:
  python validate.py --work WORKDIR [--id T03]
Exit code 1 if there are errors.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (CONFIDENCE, EVIDENCE, FORCES, FRAMES, LIKELIHOOD, STRONG_EVIDENCE, load_json,  # noqa: E402
                     load_study,
                     load_manifest, load_nuggets, load_turns, norm, study_mode, total_units,
                     turn_index, unit_label, unit_of)

ELISION = re.compile(r"\.\.\.|\u2026|\[\s*\.\.\.\s*\]|\[\s*\u2026\s*\]")


def quote_ok(quote, text):
    """True if each elided fragment of quote appears, in order, in text."""
    hay = norm(text)
    pos = 0
    for frag in ELISION.split(quote):
        f = norm(frag)
        if not f:
            continue
        i = hay.find(f, pos)
        if i < 0:
            return False
        pos = i + len(f)
    return True


def validate_nuggets(work, only=None):
    errors, warnings = [], []
    manifest = {m["transcript_id"]: m for m in load_manifest(work)}
    mode = study_mode(list(manifest.values()))
    lens = load_study(work)["lens"]
    nuggets = load_nuggets(work)
    seen = set()
    stats = {}
    for tid in manifest:
        if tid not in nuggets and (only is None or only == tid) and mode != "reddit":
            warnings.append(f"{tid}: no nuggets file yet (nuggets/{tid}.json)")
    for tid, ns in nuggets.items():
        if only and tid != only:
            continue
        if tid not in manifest:
            errors.append(f"nuggets/{tid}.json does not match any transcript in manifest")
            continue
        turns = {t["turn_id"]: t for t in load_turns(work, tid)["turns"]}
        full = " ".join(t["text"] for t in turns.values())
        for n in ns:
            nid = n.get("id", "?")
            where = f"{tid}/{nid}"
            for k in ("id", "transcript_id", "turn_ids", "quote", "observation",
                      "evidence_type", "friction"):
                if k not in n:
                    errors.append(f"{where}: missing field '{k}'")
            if nid in seen:
                errors.append(f"{where}: duplicate nugget id")
            seen.add(nid)
            if n.get("transcript_id") != tid:
                errors.append(f"{where}: transcript_id '{n.get('transcript_id')}' != file {tid}")
            if n.get("jtbd_force") not in FORCES:
                errors.append(f"{where}: jtbd_force must be one of {FORCES}")
            if "frame" in n and n["frame"] not in FRAMES:
                errors.append(f"{where}: frame must be one of {FRAMES}")
            if "frame" in n and not lens["frames"]:
                warnings.append(f"{where}: 'frame' is only used by the news and topic lenses")
            if "stance" in n and n["stance"] not in (-2, -1, 0, 1, 2):
                errors.append(f"{where}: stance must be an integer -2..2 (against..for)")
            if n.get("evidence_type") not in EVIDENCE:
                errors.append(f"{where}: evidence_type must be one of {EVIDENCE}")
            if not isinstance(n.get("friction"), bool):
                errors.append(f"{where}: friction must be true/false")
            if n.get("friction") and n.get("severity") not in (1, 2, 3):
                errors.append(f"{where}: friction nuggets need severity 1-3")
            ids = n.get("turn_ids") or []
            if not ids or not all(isinstance(i, int) for i in ids):
                errors.append(f"{where}: turn_ids must be a non-empty list of integers")
                continue
            missing = [i for i in ids if i not in turns]
            if missing:
                errors.append(f"{where}: turn_ids {missing} do not exist")
                continue
            if all(turns[i]["role"] == "interviewer" for i in ids):
                warnings.append(f"{where}: cites only interviewer turns")
            q = n.get("quote", "")
            if len(q.split()) < 3:
                warnings.append(f"{where}: very short quote")
            if n.get("evidence_type") == "observed" and mode == "reddit":
                warnings.append(f"{where}: 'observed' is for behaviour seen in a session; "
                                "forum posts are usually specific_incident, habitual or opinion")
            # Reddit: the quote must come from the first cited turn (the author credited)
            scope = [ids[0]] if mode == "reddit" else ids
            if not quote_ok(q, " ".join(turns[i]["text"] for i in scope)):
                hint = ""
                if quote_ok(q, full):
                    near = [t for t, v in turns.items() if quote_ok(q, v["text"])]
                    hint = f" (found in turn {near[0]})" if near else " (spans other turns)"
                errors.append(f"{where}: quote not verbatim in turn(s) {scope}{hint}")
            if "sentiment" in n and n["sentiment"] not in (-2, -1, 0, 1, 2):
                errors.append(f"{where}: sentiment must be an integer -2..2")
            if "success" in n and not isinstance(n["success"], bool):
                errors.append(f"{where}: success must be true/false")
            if n.get("success") and n.get("friction"):
                warnings.append(f"{where}: marked both success and friction; usually it's one or the other")
            if "aspect" in n and not isinstance(n["aspect"], str):
                errors.append(f"{where}: aspect must be a string")
            if norm(n.get("observation", "")) == norm(q):
                warnings.append(f"{where}: observation just repeats the quote; interpret it")
        stats[tid] = (len(ns), Counter(n.get("jtbd_force") for n in ns),
                      Counter(n.get("evidence_type") for n in ns))
    return errors, warnings, stats


def validate_insights(work):
    p = Path(work) / "insights.json"
    if not p.exists():
        return [], [], None
    errors, warnings = [], []
    data = load_json(p)
    insights = data.get("insights", data) if isinstance(data, dict) else data
    by_id = {n["id"]: n for ns in load_nuggets(work).values() for n in ns if "id" in n}
    manifest = load_manifest(work)
    mode = study_mode(manifest)
    tindex = turn_index(work)
    N = total_units(work, mode, manifest)
    label = unit_label(mode)
    high_min = 5 if mode == "reddit" else max(3, N // 3)
    for ins in insights:
        iid = ins.get("id", "?")
        for k in ("id", "statement", "nugget_ids", "confidence"):
            if k not in ins:
                errors.append(f"insight {iid}: missing '{k}'")
        if ins.get("confidence") not in CONFIDENCE:
            errors.append(f"insight {iid}: confidence must be one of {CONFIDENCE}")
        refs = list(ins.get("nugget_ids", [])) + list(ins.get("counter_nugget_ids", []))
        bad = [r for r in refs if r not in by_id]
        if bad:
            errors.append(f"insight {iid}: unknown nugget ids {bad}")
        sup = [by_id[r] for r in ins.get("nugget_ids", []) if r in by_id]
        cov = len({unit_of(n, mode, tindex) for n in sup})
        strong = sum(n.get("evidence_type") in STRONG_EVIDENCE for n in sup)
        if cov == 1:
            warnings.append(f"insight {iid}: supported by a single {label[:-1]}; keep confidence low or frame as a lead")
        if ins.get("confidence") == "high" and (cov < high_min or strong == 0):
            warnings.append(f"insight {iid}: 'high' but only {cov} {label} (want {high_min}+) "
                            f"and {strong} observed/specific-incident nuggets")
        if not ins.get("counter_nugget_ids"):
            warnings.append(f"insight {iid}: no counter-evidence listed (fine if none exists; say so)")
    return errors, warnings, len(insights)


def validate_sentiment(work):
    d = Path(work) / "sentiment"
    if not d.exists():
        return [], [], None
    errors, warnings = [], []
    tindex = turn_index(work)
    tri = Path(work) / "triage.json"
    sample = set(load_json(tri).get("sentiment_sample", [])) if tri.exists() else set()
    seen, aspects = set(), Counter()
    study = load_study(work)
    needs_stance = study["lens"]["stance"] and bool(study.get("stance_target"))
    missing_stance = 0
    for p in sorted(d.glob("*.json")):
        data = load_json(p)
        for r in (data.get("records", data) if isinstance(data, dict) else data):
            ref = r.get("ref", "?")
            where = f"sentiment/{p.name} {ref}"
            try:
                tid, t = ref.split("#")
                ok = (tid, int(t)) in tindex
            except ValueError:
                ok = False
            if not ok:
                errors.append(f"{where}: ref does not exist (use T01#23 form)")
                continue
            if sample and ref not in sample:
                warnings.append(f"{where}: not in the random sample; it will bias the estimate")
            if ref in seen:
                warnings.append(f"{where}: coded twice (last one wins)")
            seen.add(ref)
            if r.get("overall") not in (-2, -1, 0, 1, 2):
                errors.append(f"{where}: overall must be an integer -2..2")
            if "stance" in r and r["stance"] not in (-2, -1, 0, 1, 2, None):
                errors.append(f"{where}: stance must be an integer -2..2 (against..for) or null if not expressed")
            elif needs_stance and "stance" not in r:
                missing_stance += 1
            asp = r.get("aspects", {})
            if not isinstance(asp, dict) or any(v not in (-2, -1, 0, 1, 2) for v in asp.values()):
                errors.append(f"{where}: aspects must map aspect -> integer -2..2")
                continue
            aspects.update(a.lower() for a in asp)
            if asp and isinstance(r.get("overall"), int):
                if r["overall"] < 0 and all(v > 0 for v in asp.values()) or \
                        r["overall"] > 0 and all(v < 0 for v in asp.values()):
                    warnings.append(f"{where}: overall and aspect scores point opposite ways")
    if missing_stance:
        warnings.append(f"sentiment: {missing_stance} records have no 'stance' (use null when no position is expressed)")
    if sample:
        missing = len(sample - seen)
        if missing:
            warnings.append(f"sentiment: {missing} of {len(sample)} sampled comments not coded yet")
    return errors, warnings, (len(seen), aspects)


def validate_outlook(work):
    p = Path(work) / "outlook.json"
    if not p.exists():
        return [], [], None
    errors, warnings = [], []
    data = load_json(p)
    items = data.get("outlook", data) if isinstance(data, dict) else data
    by_id = {n["id"] for ns in load_nuggets(work).values() for n in ns if "id" in n}
    dp = Path(work) / "drivers.json"
    drv = load_json(dp) if dp.exists() else None
    aspects = {a["aspect"] for a in drv["all_aspects"]} if drv else set()
    trend_ok = bool(drv) and drv["direction"].get("status") == "ok" and \
        drv["direction"].get("negative_trend") not in (None, "insufficient data")
    for o in items:
        oid = o.get("id", "?")
        for k in ("id", "statement", "likelihood", "horizon", "basis", "would_change_if"):
            if not o.get(k):
                errors.append(f"outlook {oid}: missing '{k}'")
        if o.get("likelihood") not in LIKELIHOOD:
            errors.append(f"outlook {oid}: likelihood must be one of {list(LIKELIHOOD)}")
        if any(ch.isdigit() for ch in str(o.get("likelihood", ""))):
            errors.append(f"outlook {oid}: use a likelihood phrase, not a number")
        for b in o.get("basis", []):
            if b.startswith("driver:") and b.split(":", 1)[1] not in aspects:
                errors.append(f"outlook {oid}: unknown driver '{b}' (run drivers.py; check aspect name)")
            elif b.startswith("trend") and not trend_ok:
                errors.append(f"outlook {oid}: cites a trend but drivers.py found no usable trend")
            elif not b.startswith(("driver:", "trend", "strength:")) and b not in by_id:
                errors.append(f"outlook {oid}: basis '{b}' is not a nugget id, driver:<aspect> or trend")
        if o.get("likelihood") in ("likely", "very likely", "almost certain") and not trend_ok:
            warnings.append(f"outlook {oid}: '{o.get('likelihood')}' with no time trend in the data; "
                            "a snapshot rarely supports strong forecasts")
        if not o.get("review_by"):
            warnings.append(f"outlook {oid}: add review_by (YYYY-MM-DD) so the call can be checked later")
    return errors, warnings, len(items)


def validate_jobs_opps(work):
    errors, warnings, counts = [], [], {}
    by_id = {n["id"]: n for ns in load_nuggets(work).values() for n in ns if "id" in n}
    ip = Path(work) / "insights.json"
    ins_ids = set()
    if ip.exists():
        d = load_json(ip)
        ins_ids = {i["id"] for i in (d.get("insights", d) if isinstance(d, dict) else d)}
    jp = Path(work) / "jobs.json"
    if jp.exists():
        d = load_json(jp)
        jobs = d.get("jobs", d) if isinstance(d, dict) else d
        counts["jobs"] = len(jobs)
        for j in jobs:
            jid = j.get("id", "?")
            if not j.get("job"):
                errors.append(f"job {jid}: missing 'job'")
            elif not re.match(r"(?i)^when\b.+\bi want\b.+\bso\b", j["job"]):
                warnings.append(f"job {jid}: write as 'When <situation>, I want to <motivation>, so I can <outcome>'")
            bad = [r for r in j.get("nugget_ids", []) if r not in by_id]
            if bad:
                errors.append(f"job {jid}: unknown nugget ids {bad}")
            forces = {by_id[r]["jtbd_force"] for r in j.get("nugget_ids", []) if r in by_id}
            if len(forces - {"none"}) < 2:
                warnings.append(f"job {jid}: evidence covers fewer than two forces; the forces balance will be thin")
    op = Path(work) / "opportunities.json"
    if op.exists():
        d = load_json(op)
        opps = d.get("opportunities", d) if isinstance(d, dict) else d
        counts["opportunities"] = len(opps)
        kinds = {"fix a pain", "reduce anxiety", "amplify a strength", "serve an unmet job", "implication"}
        for o in opps:
            oid = o.get("id", "?")
            if not o.get("statement"):
                errors.append(f"opportunity {oid}: missing 'statement'")
            if o.get("kind") not in kinds:
                errors.append(f"opportunity {oid}: kind must be one of {sorted(kinds)}")
            bad = [r for r in o.get("nugget_ids", []) if r not in by_id]
            bad += [r for r in o.get("insight_ids", []) if r not in ins_ids]
            if bad:
                errors.append(f"opportunity {oid}: unknown ids {bad}")
            if not o.get("nugget_ids"):
                errors.append(f"opportunity {oid}: needs nugget_ids as evidence")
    return errors, warnings, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--id", help="validate only this transcript's nuggets")
    args = ap.parse_args()

    errors, warnings, stats = validate_nuggets(args.work, args.id)
    ie, iw, n_ins = ([], [], None) if args.id else validate_insights(args.work)
    se, sw, sent = ([], [], None) if args.id else validate_sentiment(args.work)
    oe, ow, n_out = ([], [], None) if args.id else validate_outlook(args.work)
    je, jw, jcounts = ([], [], {}) if args.id else validate_jobs_opps(args.work)
    errors += ie + se + oe + je
    warnings += iw + sw + ow + jw

    for tid, (n, forces, ev) in stats.items():
        print(f"{tid}: {n} nuggets | forces {dict(forces)} | evidence {dict(ev)}")
    if n_ins is not None:
        print(f"insights.json: {n_ins} insights")
    if sent is not None:
        n_s, asp = sent
        print(f"sentiment: {n_s} records; aspects: " + ", ".join(f"{a}({c})" for a, c in asp.most_common(25)))
    if n_out is not None:
        print(f"outlook.json: {n_out} statements")
    for k, v in jcounts.items():
        print(f"{k}.json: {v}")
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
