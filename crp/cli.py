"""Command line: python -m crp <command> ..."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from crp.anonymise import anonymise
from crp.ingest import ingest
from crp import agreement, labels, thresholds
from crp.batch import make_batches
from crp.codebook import freeze
from crp.io import InputError, validate
from crp.sample import sample
from crp.scaffold import new_study
from crp.schemas import Study
from crp.signals import signals
from crp.verify import verify


def cmd_new(args: argparse.Namespace) -> int:
    settings = {"id": args.study_id, "subject": args.subject, "type": args.type, "questions": args.question,
                "stance_target": args.stance_target, "event_date": args.event_date,
                "population": args.population, "owner": args.owner, "created": dt.date.today()}
    study = validate(Study, {k: v for k, v in settings.items() if v is not None}, "study settings")
    study_dir, notes = new_study(Path(args.root), study)
    print(f"Study folder ready: {study_dir}/ ({study.type} lens)")
    for note in notes:
        print(f"! {note}")
    print(f"Next: write your prior belief yourself in {study_dir}/sealed/prior.md (Claude can't read it), "
          f"and log every search in {study_dir}/collection_log.csv.")
    return 0


def study_dir(arg: str) -> Path:
    d = Path(arg)
    if not (d / "study.yaml").exists():
        raise InputError(f"{d} isn't a study folder (no study.yaml). Set one up with crp new.")
    return d


def cmd_ingest(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = ingest(d, interviewer=args.interviewer, keep_bots=args.keep_bots)
    print(f"Ingested {rep['forum_posts']} forum posts and {rep['interview_turns']} interview turns "
          f"in {len(rep['threads'])} threads into {d}/raw/ingested.jsonl")
    cap, red = rep["captures"], rep["reddit"]
    if cap.get("duplicates_dropped"):
        print(f"Duplicates dropped from captures: {cap['duplicates_dropped']}")
    if cap.get("promotional_flagged"):
        print(f"Promotional posts flagged (left out of sampling): {cap['promotional_flagged']}")
    if red.get("bots_removed"):
        print(f"Bot comments removed: {red['bots_removed']}")
    for w in cap.get("warnings", []) + red.get("warnings", []):
        print(f"! {w}")
    for iv in rep["interview_speakers"]:
        roles = ", ".join(f"{s} = {r}" for s, r in iv["speakers"].items())
        print(f"{iv['file']}: {roles} (by {iv['role_method']})")
        for w in iv["warnings"]:
            print(f"   ! {w}")
    if rep["interview_speakers"]:
        print('Check the interviewer and participant roles above. If any are wrong, re-run with '
              '--interviewer "Name1,Name2".')
    print("Next: crp verify")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    rep = verify(study_dir(args.study))
    print("Transcription checks: " + ", ".join(f"{k} {v}" for k, v in sorted(rep["counts"].items())))
    unverified: dict[str, int] = {}
    for d in rep["details"]:
        if d["status"] == "unverified":
            src = d["raw_ref"].split("#")[0]
            unverified[src] = unverified.get(src, 0) + 1
            continue
        line = f"{d['status'].upper():<11} {d['raw_ref']}"
        if d.get("diff"):
            line += f"\n            {d['diff']}"
        if d.get("missing"):
            line += f"\n            not seen by OCR: {', '.join(d['missing'])}"
        if d.get("note"):
            line += f"  ({d['note']})"
        print(line)
    for src, n in unverified.items():
        print(f"UNVERIFIED  {src}: {n} post(s) not checked, because OCR (Tesseract) isn't available")
    if not rep["ok"]:
        print("Fix the capture files (copy the text exactly; don't tidy wording), then re-run crp ingest "
              "and crp verify.")
        return 1
    if rep["counts"].get("ocr_flagged"):
        print("Look at each OCR-flagged post against its image before going on.")
    print("Next: crp anonymise")
    return 0


def cmd_anonymise(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = anonymise(d, Path(args.secrets_dir) if args.secrets_dir else None)
    print(f"Wrote {d}/posts.jsonl: {rep['posts']} posts from {rep['forum_people']} people in forum threads and "
          f"{rep['interview_participants']} interview participant(s), names replaced by person codes.")
    print("Next: crp signals")
    return 0


def cmd_signals(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    summary = signals(d, gap_s=args.gap, sd_mult=args.sd)
    for tid, s in summary.items():
        flags = " ".join(f"{k.split('_')[0]}={v}" for k, v in s["flag_counts"].items() if v)
        print(f"{tid}: {flags or 'no flags'}")
        for w in s["warnings"]:
            print(f"   ! {w}")
    print("Next: crp sample")
    return 0


def left_out_text(left_out: dict[str, int], min_words: int) -> str:
    words = {"promotional": "promotional", "echo_reply": "short echo replies",
             "short": f"comments under {min_words} words", "removed_or_unknown": "removed or unattributed"}
    return ", ".join(f"{words[k]} {n}" for k, n in left_out.items())


def cmd_sample(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    s = sample(d, seed=args.seed, size=args.size, person_cap=args.person_cap, thread_cap_pct=args.thread_cap_pct,
               budget=args.budget, per_person=args.per_person, min_words=args.min_words)
    m, fr = s["measurement"], s["measurement"]["frame"]
    how = {"given": "given", "reused": "reused from the last run", "generated": "generated"}[s["seed_source"]]
    print(f"Seed {s['seed']} ({how}). Re-running crp sample without --seed reuses it.")
    if not fr["eligible"]:
        print("No forum posts to measure, so there is no measurement sample (interviews never enter it).")
    else:
        print(f"Measurement sample: {m['drawn']} forum posts drawn (target {m['target']}), "
              f"written to {d}/samples/measurement.jsonl")
        print(f"  Frame: {fr['forum_posts']} forum posts, {fr['eligible']} eligible"
              + (f" (left out: {left_out_text(fr['left_out'], args.min_words)})" if fr["left_out"] else ""))
        if fr["people_capped"]:
            print(f"  Person cap {fr['person_cap']}: {fr['people_capped']} person(s) over it, {fr['posts_capped']} "
                  f"post(s) left out at random, {fr['after_person_cap']} in the frame")
        print(f"  Thread cap {m['thread_cap_pct']}%: at most {m['thread_cap']} post(s) from any one thread")
        for tid, t in m["threads"].items():
            print(f"    {tid}  eligible {t['eligible']:>3}  after person cap {t['after_person_cap']:>3}  "
                  f"sampled {t['sampled']:>3}")
        if m["drawn"] < min(m["target"], fr["after_person_cap"]):
            print(f"  ! The thread cap limited the sample to {m['drawn']} posts. More threads would allow a larger one.")
        if m["thread_cap_pct"] != thresholds.THREAD_CAP_PCT:
            print(f"  ! The thread cap is {m['thread_cap_pct']}%, not the method's {thresholds.THREAD_CAP_PCT}%. "
                  "Outputs will say so.")
    det = s["detail"]
    f = det["forum"]
    if f:
        if f["all_kept"]:
            print(f"Detail selection: all {f['candidates']} forum candidates kept (within the budget of {f['budget']})")
        else:
            print(f"Detail selection: {f['selected']} of {f['candidates']} forum candidates "
                  f"(budget {f['budget']}, at most {f['per_person']} comments per person)")
            print("  First reason for selection: " + ", ".join(f"{k} {v}" for k, v in f["first_reason"].items()))
            if f["people_at_cap"]:
                print(f"  {f['people_at_cap']} person(s) reached the per-person cap of {f['per_person']}")
            print(f"  Topic clusters ({f['cluster_method']}), size -> selected:")
            for c in sorted(f["clusters"], key=lambda c: -c["size"]):
                print(f"    {c['cluster_id']} {c['size']:>4} -> {c['selected']:<3} {', '.join(c['top_terms'][:5])}")
    if det["interview_turns"]:
        print(f"  Interviews are read in full: {det['interview_turns']} participant turn(s) added")
    print(f"Written to {d}/samples/detail.jsonl (purposive: never used for percentages)")
    print("Stop here: show Steeve the selection. If a topic cluster got few picks, re-run with a larger --budget.")
    print("Then: draft codebook.yaml. Once Steeve approves it: crp codebook freeze")
    return 0


def cmd_codebook_freeze(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    lock = freeze(d, new_version=args.new_version)
    if lock.get("unchanged"):
        print(f"Codebook version {lock['version']} is already frozen, unchanged.")
        return 0
    print(f"Froze codebook version {lock['version']} (codebook.lock). From now on it can't change "
          "without a new version and coding everything again.")
    if lock.get("superseded"):
        print(f"Moved the version {lock['replaces']} files to {lock['superseded'][-1]}/: "
              + ", ".join(lock["superseded"][:-1]))
    print("Next: crp batch")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = make_batches(d, size=args.size, seed=args.seed)
    state = "unchanged" if rep["unchanged"] else "written"
    print(f"Batches {state} (items shuffled with seed {rep['seed']}):")
    for b in rep["batches"]:
        print(f"  {b['batch']}  {b['sample']:<11}  {b['items']:>3} items")
    print("Next: for each batch, delegate to the blind-coder agent with only two paths:")
    print(f"  {d}/batches/batch_NNN.jsonl  and  {d}/labels/batch_NNN.labels.jsonl")
    print("Then: crp labels validate")
    return 0


def cmd_labels_validate(args: argparse.Namespace) -> int:
    rep = labels.validate(study_dir(args.study), args.batch)
    for b in rep["batches"]:
        mark = "ok  " if not b["errors"] else "FAIL"
        print(f"{mark} {b['batch']}: {b['coded']} of {b['items']} items labelled")
        for e in b["errors"]:
            print(f"     ! {e}")
        for w in b["warnings"]:
            print(f"     ~ {w}")
    if not rep["ok"]:
        print("Fix the problems above (re-run the blind coder on a batch if needed), then validate again.")
        return 1
    print("Next: crp labels lock --coder-model <model the blind coder ran on>")
    return 0


def cmd_labels_lock(args: argparse.Namespace) -> int:
    data = labels.lock(study_dir(args.study), args.coder_model)
    if data.get("unchanged"):
        print(f"The labels were already locked at {data['locked_at']}, unchanged.")
    else:
        print(f"Locked {data['items']} labelled items (codebook version {data['codebook_version']}, "
              f"coder {data['coder_model']}) in labels.lock.")
    print("Next: crp unseal, then crp agreement export")
    return 0


def cmd_unseal(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = labels.unseal(d)
    print(f"Copied the sealed prior to {d}/results/prior.md (labels locked at {rep['labels_locked_at']}).")
    if rep["prior_modified_after_first_ingest"]:
        print(f"! The prior was last changed at {rep['prior_modified']}, after the first crp ingest. "
              "The report must say so.")
    return 0


def cmd_agreement_export(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = agreement.export(d, n=args.n, measurement_n=args.measurement_n, seed=args.seed)
    print(f"Wrote {d}/human/agreement_sheet.csv: {rep['items']} of {rep['of']} coded items ({rep['measurement']} "
          f"measurement, then {rep['detail']} detail), seed {rep['seed']}, no AI labels. The codebook for the "
          "human coder is in human/agreement_guide.md.")
    print("Stop here: Steeve codes the sheet and saves it as human/human_labels.csv. Then: crp agreement score")
    return 0


def cmd_agreement_score(args: argparse.Namespace) -> int:
    d = study_dir(args.study)
    rep = agreement.score(d)
    print(f"Agreement between {', '.join(rep['coders'])} on {rep['items']} items "
          f"(verified at {rep['thresholds']['verified']}, tentative from {rep['thresholds']['tentative']}):")
    for name, m in rep["metrics"].items():
        alpha = "  n/a" if m["alpha"] is None else f"{m['alpha']:.3f}"
        note = f"  ({m['note']})" if m.get("note") else ""
        print(f"  {name:<28} alpha {alpha}  {m['status']:<10}  {m['pairable']} compared ({m['level']}){note}")
    for t in rep["confusion"]:
        print(f"  {t['variable']}: rows {t['rows']}, columns {t['columns']}, values {t['values']}")
        for v, row in zip(t["values"], t["counts"]):
            print(f"    {v:>3}  " + " ".join(f"{c:>3}" for c in row))
    print("Each section of the outputs shows the status of the variables it rests on (D25). "
          f"Written to {d}/results/agreement.json")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m crp",
                                     description="Community research pipeline: the code that counts.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("new", help="set up a study folder", description="Set up studies/<id>/. Safe to re-run.")
    p.add_argument("study_id", help="lowercase letters, digits and hyphens, e.g. notion-research-teams")
    p.add_argument("--subject", required=True, help="what is being studied, as it should appear in outputs")
    p.add_argument("--type", required=True, choices=["product", "brand", "news", "topic"])
    p.add_argument("--question", action="append", default=[], help="a neutral research question (repeatable)")
    p.add_argument("--stance-target", help="news and topic: the proposition people are for or against")
    p.add_argument("--event-date", help="YYYY-MM-DD: a launch, a price change, when a story broke")
    p.add_argument("--population", help="who the data represents, e.g. 'posters in r/PKMS'")
    p.add_argument("--owner")
    p.add_argument("--root", default="studies", help="folder that holds the studies (default: studies)")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("ingest", help="parse raw/ into raw/ingested.jsonl")
    p.add_argument("study", help="the study folder, e.g. studies/notion-teams")
    p.add_argument("--interviewer", help="comma-separated interviewer name fragments")
    p.add_argument("--keep-bots", action="store_true", help="keep AutoModerator and *bot comments")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("verify", help="check transcriptions against their sources")
    p.add_argument("study")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("anonymise", help="replace names with person codes: writes posts.jsonl")
    p.add_argument("study")
    p.add_argument("--secrets-dir", help="folder holding the salt (default: .secrets/ in the project)")
    p.set_defaults(func=cmd_anonymise)

    p = sub.add_parser("signals", help="flag language signals in posts.jsonl")
    p.add_argument("study")
    p.add_argument("--gap", type=float, default=2.0, help="response gap in seconds to flag (default 2.0)")
    p.add_argument("--sd", type=float, default=1.0, help="hesitation cluster at the speaker's mean + N SD")
    p.set_defaults(func=cmd_signals)

    p = sub.add_parser("sample", help="draw the measurement sample and the detail selection",
                       description="Draw samples/measurement.jsonl (random, capped) and samples/detail.jsonl "
                                   "(purposive). Same seed, same samples.")
    p.add_argument("study")
    p.add_argument("--seed", type=int, help="random seed (default: the last run's, or a new one, logged)")
    p.add_argument("--size", type=int, default=thresholds.MEASUREMENT_SIZE,
                   help=f"measurement sample size (default {thresholds.MEASUREMENT_SIZE})")
    p.add_argument("--person-cap", type=int, default=thresholds.PERSON_CAP,
                   help=f"most posts per person in the measurement frame (default {thresholds.PERSON_CAP})")
    p.add_argument("--thread-cap-pct", type=int, default=thresholds.THREAD_CAP_PCT,
                   help=f"most %% of the measurement sample from one thread (default {thresholds.THREAD_CAP_PCT})")
    p.add_argument("--budget", type=int, default=thresholds.DETAIL_BUDGET,
                   help=f"forum posts in the detail selection (default {thresholds.DETAIL_BUDGET})")
    p.add_argument("--per-person", type=int, default=thresholds.DETAIL_PER_PERSON,
                   help=f"most comments per person in the detail selection (default {thresholds.DETAIL_PER_PERSON})")
    p.add_argument("--min-words", type=int, default=thresholds.MIN_WORDS,
                   help=f"leave out comments shorter than this (default {thresholds.MIN_WORDS})")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("codebook", help="freeze the codebook")
    csub = p.add_subparsers(dest="action", required=True, metavar="action")
    q = csub.add_parser("freeze", help="check codebook.yaml and write codebook.lock")
    q.add_argument("study")
    q.add_argument("--new-version", action="store_true",
                   help="replace a frozen codebook with a new version (Steeve's call): old batches and labels "
                        "move to superseded/")
    q.set_defaults(func=cmd_codebook_freeze)

    p = sub.add_parser("batch", help="write blinded batch files for the blind coder")
    p.add_argument("study")
    p.add_argument("--size", type=int, default=40, help="items per batch (default 40)")
    p.add_argument("--seed", type=int, help="seed for the item order (default: the sample's)")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("labels", help="validate and lock the blind coder's labels")
    lsub = p.add_subparsers(dest="action", required=True, metavar="action")
    q = lsub.add_parser("validate", help="check every item is labelled with codebook values")
    q.add_argument("study")
    q.add_argument("--batch", action="append", help="only this batch, e.g. batch_001 (repeatable)")
    q.set_defaults(func=cmd_labels_validate)
    q = lsub.add_parser("lock", help="hash the labels so they can't change; allows crp unseal")
    q.add_argument("study")
    q.add_argument("--coder-model", required=True, help="the model the blind-coder agent ran on")
    q.set_defaults(func=cmd_labels_lock)

    p = sub.add_parser("unseal", help="after the labels are locked, copy sealed/prior.md to results/")
    p.add_argument("study")
    p.set_defaults(func=cmd_unseal)

    p = sub.add_parser("agreement", help="human agreement check")
    asub = p.add_subparsers(dest="action", required=True, metavar="action")
    q = asub.add_parser("export", help="write a blind sheet for a human coder")
    q.add_argument("study")
    q.add_argument("--n", type=int, default=agreement.SAMPLE_SIZE,
                   help=f"items on the sheet (default {agreement.SAMPLE_SIZE})")
    q.add_argument("--measurement-n", type=int, default=agreement.MEASUREMENT_ITEMS,
                   help=f"of which from the measurement sample (default {agreement.MEASUREMENT_ITEMS}); "
                        "if either sample is short, the other fills the rest")
    q.add_argument("--seed", type=int, help="seed for choosing items (default: the batches' seed)")
    q.set_defaults(func=cmd_agreement_export)
    q = asub.add_parser("score", help="Krippendorff's alpha, human against blind coder")
    q.add_argument("study")
    q.set_defaults(func=cmd_agreement_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
