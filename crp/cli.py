"""Command line: python -m crp <command> ..."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from crp.anonymise import anonymise
from crp.ingest import ingest
from crp.io import InputError, validate
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
