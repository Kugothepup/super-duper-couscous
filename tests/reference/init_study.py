#!/usr/bin/env python3
"""Set up what is being studied. Run once per study, before or after parsing.

The study type picks a lens that changes what is coded and shown:
  product  features, jobs to be done, pains, successes, alternatives
  brand    brand associations (strength, favourability, uniqueness), advocacy,
           competitors
  news     a story or event: stance (for/against a proposition) as well as tone,
           framing (problem / cause / moral judgement / remedy), questions people
           ask, actors, and before/after comparison around the event date
  topic    an issue or debate: like news, without a single event

Usage:
  python init_study.py --work WORKDIR --subject "Notion" --type product \\
      --question "Why do researchers leave?" [--question ...]
  python init_study.py --work WORKDIR --subject "Four-day week trial" --type news \\
      --stance-target "The four-day week should be adopted nationally" --event-date 2026-06-01
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import LENSES, save_json  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--subject", required=True, help="what is being studied, as it should appear on the dashboard")
    ap.add_argument("--type", choices=sorted(LENSES), required=True)
    ap.add_argument("--question", action="append", default=[], help="a research question (repeatable)")
    ap.add_argument("--stance-target", help="news/topic: the proposition people are for or against")
    ap.add_argument("--event-date", help="YYYY-MM-DD: when the story broke, a launch, a price change...")
    ap.add_argument("--population", help="who the data represents, e.g. 'posters in r/PKMS'")
    args = ap.parse_args()
    lens = LENSES[args.type]
    if lens["stance"] and not args.stance_target:
        print("! News and topic studies need --stance-target (the proposition people are for or against). "
              "Without it, only tone is measured.")
    study = {"subject": args.subject, "type": args.type, "questions": args.question,
             "stance_target": args.stance_target, "event_date": args.event_date,
             "population": args.population}
    save_json(study, Path(args.work) / "study.json")
    print(f"Study: {args.subject} ({lens['label']} lens)")
    print("Dashboard sections: " + ", ".join(lens["sections"]))
    if args.event_date:
        print(f"Before/after comparison around {args.event_date} will be added by drivers.py")


if __name__ == "__main__":
    main()
