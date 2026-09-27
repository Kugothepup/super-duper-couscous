"""crp signals: flag language signals in participant posts, ported from signals.py.

Flags hedges, fillers, repairs and pause markers (hesitation, interviews only), constraint,
request, workaround and switching language, and long response gaps. In forum threads it also
counts short "same here" echo replies and flags high-engagement posts. Each thread uses the
rules for its own source type (D14): forum threads the skill's Reddit rules, interviews its
interview rules. These are pointers for a closer look, not measurements.

Writes signals.jsonl (one row per participant post) and results/signals_summary.json.
"""
from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from crp import manifest
from crp.anonymise import POSTS
from crp.io import InputError, atomic_write_text, read_jsonl
from crp.schemas import Post
from crp.text import clean_quotes

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
        r"\b(\w+)[\s,]+\1\b", r"\b\w+-(?=\s|$)", r"\w\s?(?:—|--)\s?",
        r"\bi mean\b", r"\bor rather\b", r"\bno,? wait\b", r"\bsorry,", r"\bwhat i mean(?:t)? is\b",
        r"\blet me (?:rephrase|start again|think)\b", r"\bactually,? no\b",
    ],
    "pause_marker": [
        r"\.\.\.", "…",
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
FLAG_NAMES = ["hesitation_cluster", "constraint_language", "implicit_request", "workaround_language",
              "switching_language", "long_response_gap", "high_engagement"]
ECHO_MAX_WORDS = 15
SIGNALS = Path("signals.jsonl")
SUMMARY = Path("results") / "signals_summary.json"


def scan(text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    text = clean_quotes(text)
    counts, hits = {}, {}
    for cat, pats in RX.items():
        found = []
        for rx in pats:
            found += [m.group(0) for m in rx.finditer(text)]
        counts[cat] = len(found)
        hits[cat] = found[:6]
    return counts, hits


def is_echo(text: str) -> bool:
    return len(text.split()) <= ECHO_MAX_WORDS and bool(ECHO_AGREE.search(text) or ECHO_DISAGREE.search(text))


def thread_signals(turns: list[Post], gap_s: float = 2.0, sd_mult: float = 1.0) -> tuple[list[dict], dict]:
    forum = turns[0].source_type == "forum"
    replies = defaultdict(list)
    for t in turns:
        if t.parent_id:
            replies[t.parent_id].append(t)
    per_turn = []
    for i, t in enumerate(turns):
        if t.role != "participant":
            continue
        words = len(t.text.split())
        counts, hits = scan(t.text)
        hes = sum(counts[c] for c in HESITATION)
        gap = None
        prev = turns[i - 1] if i > 0 else None
        if prev is not None and t.start_s is not None and prev.end_s is not None and prev.role != "participant":
            gap = round(t.start_s - prev.end_s, 2)
        rec = {"post_id": t.post_id, "thread_id": t.thread_id, "words": words, "counts": counts,
               "hits": {k: v for k, v in hits.items() if v}, "hesitation": hes,
               "density": round(100 * hes / max(words, 20), 2), "response_gap_s": gap}
        if forum:
            rs = [r for r in replies[t.post_id] if r.role == "participant"]
            short = [r for r in rs if len(r.text.split()) <= ECHO_MAX_WORDS]
            rec.update({"score": t.score or 0, "n_replies": len(rs),
                        "echo_agree": sum(bool(ECHO_AGREE.search(r.text)) for r in short),
                        "echo_disagree": sum(bool(ECHO_DISAGREE.search(r.text)) for r in short)})
        per_turn.append(rec)

    dens = [p["density"] for p in per_turn if p["words"] >= 8]
    mean = statistics.mean(dens) if dens else 0
    sd = statistics.pstdev(dens) if len(dens) > 1 else 0
    cutoff = mean + sd_mult * sd
    scores = sorted(p.get("score", 0) for p in per_turn)
    score_cut = max(5, scores[int(0.9 * (len(scores) - 1))]) if scores else 5
    for p in per_turn:
        flags = []
        if not forum and p["words"] >= 8 and p["hesitation"] >= 3 and p["density"] >= cutoff and sd > 0:
            flags.append("hesitation_cluster")
        for cat, flag in (("constraint", "constraint_language"), ("implicit_request", "implicit_request"),
                          ("workaround", "workaround_language"), ("switching", "switching_language")):
            if p["counts"][cat]:
                flags.append(flag)
        if p["response_gap_s"] is not None and p["response_gap_s"] >= gap_s:
            flags.append("long_response_gap")
        if forum and p["words"] >= 5 and (p["score"] >= score_cut or p["echo_agree"] >= 2):
            flags.append("high_engagement")
        p["flags"] = flags

    tot_words = sum(p["words"] for p in per_turn) or 1
    totals = {c: sum(p["counts"][c] for p in per_turn) for c in LEX}
    warnings = []
    if not forum:
        if tot_words > 500 and totals["filler"] == 0 and totals["repair"] < 2:
            warnings.append("No fillers and almost no repairs: the transcript looks cleaned or edited. "
                            "Hesitation signals will be unreliable; a verbatim transcript is better.")
        if not any(t.end_s is not None for t in turns):
            warnings.append("No end timestamps, so response gaps were not computed.")
    summary = {"source_type": turns[0].source_type, "participant_words": tot_words, "participant_turns": len(per_turn),
               "per_100_words": {c: round(100 * totals[c] / tot_words, 2) for c in LEX},
               "hesitation_density_mean": round(mean, 2), "hesitation_density_sd": round(sd, 2),
               "flag_counts": {f: sum(f in p["flags"] for p in per_turn) for f in FLAG_NAMES},
               "warnings": warnings}
    return per_turn, summary


def signals(study_dir: Path, gap_s: float = 2.0, sd_mult: float = 1.0) -> dict:
    study_dir = Path(study_dir)
    posts_path = study_dir / POSTS
    if not posts_path.exists():
        raise InputError(f"No {posts_path}. Run crp anonymise first.")
    posts = read_jsonl(posts_path, Post)
    with manifest.stage(study_dir, "signals", inputs=[posts_path]) as record:
        threads: dict[str, list[Post]] = defaultdict(list)
        for p in posts:
            threads[p.thread_id].append(p)
        rows, summary = [], {}
        for tid, turns in threads.items():
            per_turn, summary[tid] = thread_signals(turns, gap_s, sd_mult)
            rows += per_turn
        atomic_write_text(study_dir / SIGNALS, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        atomic_write_text(study_dir / SUMMARY, json.dumps(summary, indent=2) + "\n")
        record["outputs"] = [str(SIGNALS), str(SUMMARY)]
        record["settings"] = {"gap_s": gap_s, "sd": sd_mult}
    return summary
