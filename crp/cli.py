"""Command line: python -m crp <command> ..."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from crp.io import InputError, validate
from crp.scaffold import new_study
from crp.schemas import Study


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2
