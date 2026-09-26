#!/usr/bin/env python3
"""Flag linguistic signals in participant turns: hedging, fillers, repairs, pause
markers, constraint/agency-loss language, implicit requests, workaround and switching
language, and long response gaps. For Reddit studies it also counts "echo" replies
(short "same here" / "this" agreements and short disagreements) and flags
high-engagement comments; spoken-hesitation flags are skipped for written text.

These are POINTERS for a human or Claude to look at, not measures of cognitive load.
Flags are relative to each participant's own baseline, because people differ a lot
in how much they hedge or say "um".

Usage:
  python signals.py --work WORKDIR [--gap 2.0]
Writes WORKDIR/signals/Txx.json and WORKDIR/signals/summary.csv.
"""
import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import clean_quotes, load_manifest, load_turns, save_json, study_mode  # noqa: E402

LEX = {
    "hedge": [
        r"\bi think\b", r"\bi guess\b", r"\bi suppose\b", r"\bi assume\b", r"\bi believe\b",
        r"\bprobably\b", r"\bmaybe\b", r"\bperhaps\b", r"\bpossibly\b", r"\bkind of\b",
        r"\bkinda\b", r"\bsort of\b", r"\bsorta\b",
        r"\b(?:i'?m )?not (?:really |entirely |totally |100% )?sure\b",
        r"\bi (?:don'?t|do not) know\b", r"\bi dunno\b", r"\bmight\b", r"\bi feel like\b",
        r"\bi'?d say\b", r"\bseems?\b", r"\bsomewhat\b",
    ],
    "filler": [r"\bu+m+\b", r"\bu+h+\b", r"\berm+\b", r"\ber\b", r"\bhm+\b", r"\bah+\b", r"\byou know\b"],
    "repair": [
        r"\b(\w+)[\s,]+\1\b", r"\b\w+-(?=\s|$)", r"\w\s?(?:\u2014|--)\s?",
        r"\bi mean\b", r"\bor rather\b", r"\bno,? wait\b", r"\bsorry,", r"\bwhat i mean(?:t)? is\b",
        r"\blet me (?:rephrase|start again|think)\b", r"\bactually,? no\b",
    ],
    "pause_marker": [
        r"\.\.\.", "\u2026",
        r"[\[(](?:pause|silence|long pause|\d+(?:\.\d+)?\s*s(?:ec(?:onds?)?)?)[\])]",
    ],
    "constraint": [
        r"\b(?:forced|forces|wouldn'?t let|won'?t let|doesn'?t let|didn'?t let|does not let|"
        r"did not let|won'?t allow|doesn'?t allow|didn'?t allow)\s+(?:me|us)\b",
        r"\bi (?:had|have|needed|need) to\b", r"\bi (?:was|got|am|'m) stuck\b",
        r"\bi (?:couldn'?t|can'?t|could not|cannot)\b", r"\bno way to\b", r"\bit kept\b",
        r"\bgave up\b",
    ],
    "implicit_request": [
        r"\bis there (?:a|any) way\b", r"\bcan (?:it|you|i)\b(?=[^.!?]*\?)",
        r"\bcould (?:it|you|i)\b(?=[^.!?]*\?)", r"\bi wish\b",
        r"\b(?:it )?(?:would|'d) be (?:so |really )?(?:nice|great|good|helpful|handy|useful|easier)\b",
        r"\bwhy (?:can'?t|doesn'?t|won'?t|isn'?t)\b", r"\bif only\b",
    ],
    "workaround": [
        r"\bwork[- ]?arounds?\b", r"\bi ended up\b", r"\bwhat i do is\b",
        r"\bmy (?:solution|fix|hack) (?:is|was)\b", r"\bthe (?:only )?way i (?:got|get|managed)\b",
        r"\bi just use\b", r"\bmanually\b", r"\bspreadsheet\b",
    ],
    "switching": [
        r"\bswitch(?:ed|ing)? (?:to|from|over|back)\b", r"\bmov(?:ed|ing) (?:to|from|over|back)\b",
        r"\bwent back to\b", r"\b(?:cancell?ed|unsubscribed|uninstalled|churned)\b",
        r"\balternatives?\b", r"\breplacement for\b", r"\bgave up on\b",
    ],
}
ECHO_AGREE = re.compile(
    r"^\W*(?:this|same|same here|me too|\+1|exactly|agreed|agree|100%|yep|yes|seconded|so much this|"
    r"came here to say this|this right here|same issue|same problem|same experience|"
    r"i have the same|i had the same|happening to me too|same for me)\b", re.I)
ECHO_DISAGREE = re.compile(
    r"^\W*(?:no|nah|nope|disagree|i disagree|hard disagree|not really|not true|wrong|"
    r"that's not|that isn't|not my experience)\b", re.I)
RX = {k: [re.compile(p, re.I) for p in v] for k, v in LEX.items()}
HESITATION = ("hedge", "filler", "repair", "pause_marker")


def scan(text):
    text = clean_quotes(text)
    counts, hits = {}, {}
    for cat, pats in RX.items():
        found = []
        for rx in pats:
            found += [m.group(0) for m in rx.finditer(text)]
        counts[cat] = len(found)
        hits[cat] = found[:6]
    return counts, hits


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--gap", type=float, default=2.0,
                    help="response gap (s) to flag when end times exist; ASR cue timing is noisy, so default is 2.0")
    ap.add_argument("--sd", type=float, default=1.0, help="flag hesitation at participant mean + N SD")
    args = ap.parse_args()
    work = Path(args.work)
    manifest = load_manifest(work)
    mode = study_mode(manifest)
    rows = []

    for m in manifest:
        tid = m["transcript_id"]
        doc = load_turns(work, tid)
        turns = doc["turns"]
        replies = defaultdict(list)
        for t in turns:
            if t.get("parent_turn"):
                replies[t["parent_turn"]].append(t)
        per_turn = []
        for i, t in enumerate(turns):
            if t["role"] != "participant":
                continue
            words = len(t["text"].split())
            counts, hits = scan(t["text"])
            hes = sum(counts[c] for c in HESITATION)
            gap = None
            if i > 0 and t.get("start") is not None and turns[i - 1].get("end") is not None \
                    and turns[i - 1]["role"] != "participant":
                gap = round(t["start"] - turns[i - 1]["end"], 2)
            rec = {"turn_id": t["turn_id"], "words": words, "counts": counts, "hits": hits,
                   "hesitation": hes, "density": round(100 * hes / max(words, 20), 2),
                   "response_gap_s": gap, "text": t["text"]}
            if mode == "reddit":
                rs = [r for r in replies[t["turn_id"]] if r["role"] == "participant"]
                short = [r for r in rs if len(r["text"].split()) <= 15]
                rec.update({"score": t.get("score", 0), "n_replies": len(rs),
                            "echo_agree": sum(bool(ECHO_AGREE.search(r["text"])) for r in short),
                            "echo_disagree": sum(bool(ECHO_DISAGREE.search(r["text"])) for r in short)})
            per_turn.append(rec)

        dens = [p["density"] for p in per_turn if p["words"] >= 8]
        mean = statistics.mean(dens) if dens else 0
        sd = statistics.pstdev(dens) if len(dens) > 1 else 0
        cutoff = mean + args.sd * sd
        scores = sorted(p.get("score", 0) for p in per_turn)
        score_cut = max(5, scores[int(0.9 * (len(scores) - 1))]) if scores else 5
        flagged = []
        for p in per_turn:
            flags = []
            if mode != "reddit" and p["words"] >= 8 and p["hesitation"] >= 3 and p["density"] >= cutoff and sd > 0:
                flags.append("hesitation_cluster")
            for cat, flag in (("constraint", "constraint_language"), ("implicit_request", "implicit_request"),
                              ("workaround", "workaround_language"), ("switching", "switching_language")):
                if p["counts"][cat]:
                    flags.append(flag)
            if p["response_gap_s"] is not None and p["response_gap_s"] >= args.gap:
                flags.append("long_response_gap")
            if mode == "reddit" and p["words"] >= 5 and (p["score"] >= score_cut or p["echo_agree"] >= 2):
                flags.append("high_engagement")
            p["flags"] = flags
            if flags:
                fl = {"turn_id": p["turn_id"], "flags": flags, "density": p["density"],
                      "hits": {k: v for k, v in p["hits"].items() if v},
                      "response_gap_s": p["response_gap_s"],
                      "excerpt": p["text"][:200] + ("..." if len(p["text"]) > 200 else "")}
                if mode == "reddit":
                    fl.update({k: p[k] for k in ("score", "n_replies", "echo_agree", "echo_disagree")})
                flagged.append(fl)

        tot_words = sum(p["words"] for p in per_turn) or 1
        totals = {c: sum(p["counts"][c] for p in per_turn) for c in LEX}
        warnings = []
        if mode != "reddit":
            if tot_words > 500 and totals["filler"] == 0 and totals["repair"] < 2:
                warnings.append("No fillers and almost no repairs: transcript looks cleaned/edited. "
                                "Hesitation signals will be unreliable; prefer a verbatim transcript.")
            if not doc["has_end_times"]:
                warnings.append("No end timestamps, so response gaps were not computed.")
        flag_names = ["hesitation_cluster", "constraint_language", "implicit_request", "workaround_language",
                      "switching_language", "long_response_gap", "high_engagement"]
        summary = {"participant_words": tot_words, "participant_turns": len(per_turn),
                   "per_100_words": {c: round(100 * totals[c] / tot_words, 2) for c in LEX},
                   "hesitation_density_mean": round(mean, 2), "hesitation_density_sd": round(sd, 2),
                   "flag_counts": {f: sum(f in p["flags"] for p in per_turn) for f in flag_names},
                   "warnings": warnings}
        keep = ("turn_id", "words", "counts", "density", "response_gap_s", "flags",
                "score", "n_replies", "echo_agree", "echo_disagree")
        save_json({"transcript_id": tid, "mode": mode, "summary": summary, "flagged_turns": flagged,
                   "turns": [{k: p[k] for k in keep if k in p} for p in per_turn]},
                  work / "signals" / f"{tid}.json")
        rows.append({"transcript_id": tid, "participant_words": tot_words,
                     **{f"{c}_per100": summary["per_100_words"][c] for c in LEX},
                     **{f"n_{f}": n for f, n in summary["flag_counts"].items()},
                     "warnings": " | ".join(warnings)})
        fc = summary["flag_counts"]
        print(f"{tid}: " + " ".join(f"{k.split('_')[0]}={v}" for k, v in fc.items() if v))
        for w in warnings:
            print(f"     ! {w}")

    with open(work / "signals" / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {work}/signals/ (per-transcript JSON + summary.csv)")


if __name__ == "__main__":
    main()
