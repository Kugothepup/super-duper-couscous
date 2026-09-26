#!/usr/bin/env python3
"""Assemble the synthesis report from nuggets, insights, signals and themes.

Every insight is shown with its supporting quotes, coverage (independent voices:
transcripts for interviews, distinct authors for Reddit) and evidence strength, so
claims stay traceable. Also reports:
  - connections: which tags co-occur, and products/alternatives mentioned (product:* tags)
  - flagged moments nobody coded, and wide-coverage clusters no insight uses
  - for Reddit: engagement (score, "same here" echoes) behind each insight

If drivers.json exists (drivers.py), the report opens with sentiment, its drivers
and direction of travel; if outlook.json exists, with a forecast-style outlook.

Usage:
  python build_report.py --work WORKDIR [--title "Study"] [--redact-quotes | --include-quotes]
Reddit reports are quote-free by default: evidence is shown as paraphrased observations
with ids, and thread titles are left out, so nothing can be searched back to a person.
Use --include-quotes for an internal-only version. Interview reports include quotes
unless --redact-quotes is given.
Writes WORKDIR/report.md and WORKDIR/nuggets.csv.
"""
import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (FORCES, LIKELIHOOD, STRONG_EVIDENCE, load_json, load_manifest,  # noqa: E402
                     load_nuggets, load_signals, study_mode, total_units, turn_index,
                     unit_label, unit_of)

FORCE_LABEL = {"push": "Push (pain with current way)", "pull": "Pull (attraction of new way)",
               "anxiety": "Anxiety (worry about switching)", "habit": "Habit (comfort of status quo)"}
CONF_ORDER = {"high": 0, "medium": 1, "low": 2}


def trim(s, n=280):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


class Ctx:
    def __init__(self, work, redact):
        self.work = work
        self.redact = redact
        self.manifest = load_manifest(work)
        self.mode = study_mode(self.manifest)
        self.reddit = self.mode == "reddit"
        self.tindex = turn_index(work)
        self.N = total_units(work, self.mode, self.manifest)
        self.label = unit_label(self.mode)
        self.sig = {}
        for m in self.manifest:
            s = load_signals(work, m["transcript_id"])
            if s:
                self.sig[m["transcript_id"]] = s
        self.sig_turn = {(tid, t["turn_id"]): t for tid, s in self.sig.items() for t in s["turns"]}

    def unit(self, n):
        return unit_of(n, self.mode, self.tindex)

    def turn(self, n):
        return self.tindex.get((n["transcript_id"], n["turn_ids"][0]), {})

    def quote_line(self, n):
        t = self.turn(n)
        if self.reddit:
            who = f"{t.get('author_id', '?')}{' (OP)' if t.get('is_op') else ''}, {n['transcript_id']}, ^{t.get('score', 0)}"
        else:
            who = f"{n['transcript_id']}, turn {n['turn_ids'][0]}"
        if self.redact:
            return f"> _{n['observation']}_  \n> — {n['id']} ({who}) · {n['evidence_type']}"
        return f'> "{trim(n["quote"])}"  \n> — {who} · {n["evidence_type"]}'

    def diverse(self, nuggets, k=3):
        """Up to k nuggets, preferring distinct voices, strong evidence, severity, engagement."""
        ranked = sorted(nuggets, key=lambda n: (n["evidence_type"] not in STRONG_EVIDENCE,
                                                -(n.get("severity") or 0),
                                                -(self.turn(n).get("score") or 0)))
        out, seen = [], set()
        for n in ranked:
            u = self.unit(n)
            if u not in seen:
                out.append(n)
                seen.add(u)
            if len(out) == k:
                return out
        for n in ranked:
            if n not in out:
                out.append(n)
            if len(out) == k:
                break
        return out


def mermaid_id(tag):
    return "t_" + re.sub(r"\W", "_", tag)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--title", default="Synthesis")
    ap.add_argument("--redact-quotes", action="store_true")
    ap.add_argument("--include-quotes", action="store_true", help="Reddit: include verbatim quotes (internal only)")
    args = ap.parse_args()
    work = Path(args.work)
    C = Ctx(work, False)
    C.redact = args.redact_quotes or (C.reddit and not args.include_quotes)
    args.redact_quotes = C.redact

    nuggets = [n for ns in load_nuggets(work).values() for n in ns]
    by_id = {n["id"]: n for n in nuggets}
    ip = work / "insights.json"
    insights = []
    if ip.exists():
        d = load_json(ip)
        insights = d.get("insights", d) if isinstance(d, dict) else d
    themes = load_json(work / "themes.json") if (work / "themes.json").exists() else None
    triage = load_json(work / "triage.json") if (work / "triage.json").exists() else None

    L = [f"# {args.title}", ""]
    words = sum(m["participant_words"] for m in C.manifest)
    if C.reddit:
        subs = sorted({m.get("subreddit") for m in C.manifest if m.get("subreddit")})
        n_items = sum(m["n_turns"] for m in C.manifest)
        coded = triage["n_selected"] if triage else n_items
        L.append(f"{len(C.manifest)} Reddit threads ({', '.join('r/' + s for s in subs)}) · "
                 f"{n_items} posts+comments from {C.N} authors · {coded} read in detail · "
                 f"{len(nuggets)} nuggets · {len(insights)} insights")
    else:
        L.append(f"{len(C.manifest)} transcripts · {len(nuggets)} nuggets · {len(insights)} insights · "
                 f"{words:,} participant words")
    L.append("")

    # ---- Sentiment, drivers, direction, outlook
    drv = load_json(work / "drivers.json") if (work / "drivers.json").exists() else None
    outlook = []
    if (work / "outlook.json").exists():
        d = load_json(work / "outlook.json")
        outlook = d.get("outlook", d) if isinstance(d, dict) else d
    if drv:
        o = drv["overall"]
        gap = o["negative_pct"] - o["positive_pct"]
        mood = "net negative" if gap > 15 else "net positive" if gap < -15 else "mixed"
        top = drv["drivers"][:3]
        L += ["## Sentiment and what drives it", ""]
        head = (f"Sentiment is **{mood}**: {o['negative_pct']}% of sampled comments are negative "
                f"(95% range {o['negative_ci'][0]}–{o['negative_ci'][1]}%) and {o['positive_pct']}% positive")
        if top:
            head += (". Negativity comes mainly from " +
                     ", ".join(f"**{a['aspect']}** ({a['share_of_negative_pct']}% of negative mentions)" for a in top))
        L += [head + ".", ""]
        L += [f"Measured on a random sample of {o['n_comments']} comments from {o['n_authors']} authors"
              + (f" (out of {o['sample_of']})" if o.get("sample_of") else "")
              + f". By author rather than comment, {o['authors_net_negative_pct']}% lean negative.", ""]
        if drv["drivers"]:
            L += ["| Driver | Share of negative mentions | How often negative when raised | Authors | Mean (−2 to +2) |",
                  "|---|---|---|---|---|"]
            for a in drv["drivers"][:8]:
                L.append(f"| {a['aspect']} | {a['share_of_negative_pct']}% | {a['negative_rate_pct']}% | "
                         f"{a['authors']} | {a['mean']} |")
            L.append("")
        if drv["strengths"]:
            L += ["**What people value:** " + ", ".join(
                f"{a['aspect']} ({a['share_of_positive_pct']}% of positive mentions)" for a in drv["strengths"][:4]), ""]
        # why: link drivers to coded nuggets
        whys = []
        for a in top:
            rel = [n for n in nuggets if n.get("aspect", "").lower() == a["aspect"]
                   or a["aspect"] in [t.lower() for t in n.get("tags", [])]]
            if rel:
                whys.append((a["aspect"], C.diverse(rel, 3)))
        if whys:
            L += ["**Why these drive negativity** (from coded comments):", ""]
            for asp, ns in whys:
                L.append(f"- **{asp}:** " + "; ".join(f"{n['observation']} ({n['id']})" for n in ns))
            L.append("")
        unexplained = [a["aspect"] for a in top if a["aspect"] not in {w[0] for w in whys}]
        if unexplained:
            L += [f"⚠ No coded comments yet explain: {', '.join(unexplained)}. "
                  "Code comments on these (kwic.py helps find them) before drawing conclusions.", ""]
        dr = drv["direction"]
        L += ["### Direction of travel", ""]
        if dr.get("status") == "ok":
            L += [f"Across {len(dr['periods'])} {dr['unit']}s, the share of negative comments shows "
                  f"**{dr['negative_trend']}**"
                  + (" (only periods with enough comments are compared)." if dr["negative_trend"] != "insufficient data" else "."), "",
                  f"| {dr['unit'].capitalize()} | Sampled | Negative | Top aspects | Switching talk per 100 comments |",
                  "|---|---|---|---|---|"]
            for pr in dr["periods"]:
                ta = ", ".join(list(pr["top_aspects"])[:3])
                L.append(f"| {pr['period']} | {pr['n']} | {pr['negative_pct']}% | {ta} | "
                         f"{dr['switching_rate_per_100'].get(pr['period'], '—')} |")
            L.append("")
        else:
            L += [dr.get("note", "No timestamps, so direction can't be assessed."), ""]
    if outlook:
        L += ["### Outlook", "",
              "Judgements, not measurements. Likelihood words follow the ICD 203 scale "
              "(e.g. likely = 55–80%). Each has a date to check it against what happened.", ""]
        for ob in outlook:
            rng = LIKELIHOOD.get(ob.get("likelihood"), "?")
            L += [f"**{ob['id']}. {ob['statement']}**  ",
                  f"{str(ob.get('likelihood', '')).capitalize()} ({rng}) · horizon: {ob.get('horizon')}"
                  + (f" · review by {ob['review_by']}" if ob.get("review_by") else "") + "  ",
                  f"Basis: {', '.join(ob.get('basis', []))}  ",
                  f"Would change if: {ob.get('would_change_if')}", ""]

    # ---- Insights
    L += ["## Insights", ""]
    if not insights:
        L += ["_No insights.json yet._", ""]
    for ins in sorted(insights, key=lambda i: CONF_ORDER.get(i.get("confidence"), 3)):
        sup = [by_id[r] for r in ins.get("nugget_ids", []) if r in by_id]
        con = [by_id[r] for r in ins.get("counter_nugget_ids", []) if r in by_id]
        cov = len({C.unit(n) for n in sup})
        strong = sum(n["evidence_type"] in STRONG_EVIDENCE for n in sup)
        L.append(f"### {ins['id']}. {ins['statement']}")
        meta = (f"**Confidence:** {ins.get('confidence')} · **Coverage:** {cov} "
                + ((C.label if cov != 1 else C.label[:-1]) if C.reddit else f"/{C.N} {C.label}")
                + f" · **Strong evidence:** {strong}/{len(sup)} nuggets")
        if C.reddit:
            turns = {(n["transcript_id"], n["turn_ids"][0]) for n in sup}
            score = sum((C.tindex.get(k, {}).get("score") or 0) for k in turns)
            agree = sum((C.sig_turn.get(k, {}).get("echo_agree") or 0) for k in turns)
            dis = sum((C.sig_turn.get(k, {}).get("echo_disagree") or 0) for k in turns)
            meta += f" · **Engagement:** ^{score}, +{agree} agree / -{dis} disagree replies"
        if cov == 1:
            meta += " · ⚠ single source"
        L += [meta, ""]
        for n in C.diverse(sup):
            L += [C.quote_line(n), ""]
        if con:
            L += ["**Counter-evidence:**", ""]
            for n in con[:2]:
                L += [C.quote_line(n), ""]
        for r in ins.get("recommendations", []):
            L.append(f"- **Recommendation:** {r}")
        if ins.get("recommendations"):
            L.append("")

    # ---- JTBD forces
    L += ["## Forces of progress (JTBD)", "", f"| Force | Nuggets | {C.label.capitalize()} |", "|---|---|---|"]
    for f in FORCES[:-1]:
        fn = [n for n in nuggets if n["jtbd_force"] == f]
        units = len({C.unit(n) for n in fn})
        L.append(f"| {FORCE_LABEL[f]} | {len(fn)} | {units}{'' if C.reddit else f'/{C.N}'} |")
    L.append("")
    for f in FORCES[:-1]:
        fn = [n for n in nuggets if n["jtbd_force"] == f]
        if fn:
            L += [f"**{FORCE_LABEL[f]}**", ""]
            L += [f"- {n['observation']} ({n['id']})" for n in C.diverse(fn)]
            L.append("")

    # ---- Connections
    tags_per = [sorted({t for t in n.get("tags", []) if not t.startswith("product:")}) for n in nuggets]
    pairs = Counter(p for ts in tags_per for p in combinations(ts, 2))
    products = defaultdict(Counter)
    for n in nuggets:
        for t in n.get("tags", []):
            if t.startswith("product:"):
                products[t.split(":", 1)[1]][n["jtbd_force"]] += 1
    strong_pairs = [(p, c) for p, c in pairs.most_common(15) if c >= 2]
    if strong_pairs or products:
        L += ["## Connections", ""]
    if strong_pairs:
        L += ["Tags that keep appearing together (edge = number of nuggets sharing both):", "",
              "```mermaid", "graph LR"]
        for (a, b), c in strong_pairs:
            L.append(f'  {mermaid_id(a)}["{a}"] ---|{c}| {mermaid_id(b)}["{b}"]')
        L += ["```", ""]
    if products:
        L += ["**Products and alternatives mentioned** (by force of the nuggets that mention them):", "",
              "| Product | Mentions | Push | Pull | Anxiety | Habit |", "|---|---|---|---|---|---|"]
        for p, c in sorted(products.items(), key=lambda kv: -sum(kv[1].values())):
            L.append(f"| {p} | {sum(c.values())} | {c['push']} | {c['pull']} | {c['anxiety']} | {c['habit']} |")
        L.append("")

    # ---- Friction
    fr = sorted([n for n in nuggets if n.get("friction")],
                key=lambda n: (-(n.get("severity") or 0), -(C.turn(n).get("score") or 0)))
    L += ["## Friction points", ""]
    if fr:
        tag_ct = Counter(t for n in fr for t in n.get("tags", []))
        if tag_ct:
            L += ["Most frequent friction tags: " + ", ".join(f"{t} ({c})" for t, c in tag_ct.most_common(8)), ""]
        for n in fr[:10]:
            L += [f"**Severity {n.get('severity')}:** {n['observation']}", "", C.quote_line(n), ""]
    else:
        L += ["_No friction nuggets coded._", ""]

    # ---- Signals
    cited = defaultdict(set)
    for n in nuggets:
        cited[n["transcript_id"]].update(n["turn_ids"])
    selected = None
    if triage:
        selected = {(tid, t) for tid, ts in triage["by_thread"].items() for t in ts}
    look = {"hesitation_cluster", "constraint_language", "implicit_request",
            "workaround_language", "switching_language", "high_engagement"}
    L += ["## Language signals", ""]
    if C.reddit:
        L += ["Keyword-based flags in written posts. Pointers for reading, not measurements.", "",
              "| Thread | Constraint | Requests | Workarounds | Switching | High engagement |",
              "|---|---|---|---|---|---|"]
    else:
        L += ["Relative to each participant's own baseline. These point to moments worth re-reading, "
              "they do not measure cognitive load.", "",
              "| Transcript | Hedges/100w | Fillers/100w | Repairs/100w | Hesitation clusters | "
              "Constraint | Requests | Workarounds | Switching |", "|---|---|---|---|---|---|---|---|---|"]
    unexamined, sig_warn = [], []
    for m in C.manifest:
        tid = m["transcript_id"]
        s = C.sig.get(tid)
        if not s:
            continue
        p, fc = s["summary"]["per_100_words"], s["summary"]["flag_counts"]
        if C.reddit:
            L.append(f"| {tid} | {fc['constraint_language']} | {fc['implicit_request']} | "
                     f"{fc['workaround_language']} | {fc['switching_language']} | {fc['high_engagement']} |")
        else:
            L.append(f"| {tid} | {p['hedge']} | {p['filler']} | {p['repair']} | {fc['hesitation_cluster']} | "
                     f"{fc['constraint_language']} | {fc['implicit_request']} | {fc['workaround_language']} | "
                     f"{fc['switching_language']} |")
        sig_warn += [f"{tid}: {w}" for w in s["summary"]["warnings"] if "cleaned" in w]
        for ft in s["flagged_turns"]:
            if selected is not None and (tid, ft["turn_id"]) not in selected:
                continue
            if ft["turn_id"] not in cited[tid] and look & set(ft["flags"]):
                unexamined.append((tid, ft))
    L.append("")
    L += [f"⚠ {w}" for w in sig_warn] + ([""] if sig_warn else [])
    if unexamined:
        unexamined.sort(key=lambda x: -(x[1].get("score") or 0))
        L += ["### Flagged moments with no nugget (worth a human look)", ""]
        for tid, ft in unexamined[:12]:
            txt = "" if C.redact else " " + trim(ft["excerpt"], 160)
            sc = f" ^{ft['score']}" if C.reddit else ""
            L.append(f"- **{tid}#{ft['turn_id']}**{sc} [{', '.join(ft['flags'])}]{txt}")
        if len(unexamined) > 12:
            L.append(f"- …and {len(unexamined) - 12} more")
        L.append("")

    # ---- Themes
    gaps = []
    if themes:
        turn_to_nug = defaultdict(set)
        for n in nuggets:
            for t in n["turn_ids"]:
                turn_to_nug[f"{n['transcript_id']}#{t}"].add(n["id"])
        nug_to_ins = defaultdict(set)
        for ins in insights:
            for r in ins.get("nugget_ids", []):
                nug_to_ins[r].add(ins["id"])
        n_units = themes.get("n_units", themes.get("n_transcripts", C.N))
        L += ["## Clusters", "",
              f"Clustered {themes['n_items']} {themes['source']} with {themes['method']} "
              f"(silhouette {themes['silhouette']}). A second opinion on the synthesis, not a replacement.", "",
              f"| Cluster | Size | {C.label.capitalize()} | Top terms | Linked insights |", "|---|---|---|---|---|"]
        for c in themes["clusters"]:
            nids = set()
            for ref in c["members"]:
                nids |= {ref} if ref in by_id else turn_to_nug.get(ref, set())
            linked = sorted({i for nid in nids for i in nug_to_ins.get(nid, ())})
            dom = f" (mostly {c['dominated_by']})" if c.get("dominated_by") else ""
            cov = f"{c['coverage']}" if C.reddit else f"{c['coverage']}/{n_units}"
            L.append(f"| {c['cluster_id']} | {c['size']} | {cov}{dom} | "
                     f"{', '.join(c['top_terms'][:5])} | {', '.join(linked) or '—'} |")
            wide = c["coverage"] >= (5 if C.reddit else max(2, n_units // 3))
            if not linked and wide:
                gaps.append(c)
        L.append("")
        if gaps:
            L += ["### Possible synthesis gaps", "", "Wide-coverage clusters that no insight draws on:", ""]
            for c in gaps:
                ex = "" if C.redact else f": e.g. \"{trim(c['representative'][0]['text'], 140)}\""
                L.append(f"- **{c['cluster_id']}** ({', '.join(c['top_terms'][:4])}){ex}")
            L.append("")

    # ---- Hypotheses for discovery (the handover)
    hyp = load_json(work / "hypotheses_result.json") if (work / "hypotheses_result.json").exists() else None
    if hyp:
        origin = {"stated": "your belief, written down before reading", "formed": "suggested by this data"}
        L += ["## Hypotheses for discovery", "",
              "Starting points for proper research. These findings can suggest and prioritise hypotheses, "
              "not prove them; ones suggested by this data are not tested by it.", ""]
        for w in hyp.get("warnings", []):
            L += [f"⚠ {w}", ""]
        for h in hyp["hypotheses"]:
            L += [f"### {h['id']}: {h['statement']}",
                  f"_{origin.get(h['origin'], h['origin'])}, {h['importance']} importance._ "
                  f"**{h['lean'].capitalize()}**" + (f", {h['strength']} evidence" if h['lean'] != "can't tell from this data" else "")
                  + f" ({h['voices']} people). **Priority: {h['priority']}.**", ""]
            for g in h["signals"]:
                if "prob" in g:
                    val = f"{g['prob']}% of re-draws" if g.get("prob") is not None else g.get("note", "")
                elif "k" in g:
                    val = f"{g['k']} of {g['n']} (likely {g['ci'][0]}–{g['ci'][1]}%)"
                else:
                    val = f"{g['voices_for']} for, {g['voices_against']} against"
                L.append(f"- {g['text']}: {val} ({g['lean']})")
            ns = h.get("next_step", {})
            L += ["", f"**Test it:** {ns.get('method', '')}" + (f" Recruit: {ns['recruit']}." if ns.get("recruit") else ""),
                  f"Would support it: {ns.get('confirm', '')}. Would count against it: {ns.get('disconfirm', '')}.", ""]
            if ns.get("questions"):
                L += ["Starting questions: " + " / ".join(ns["questions"]), ""]

    # ---- Method
    L += ["## Method and caveats", ""]
    if C.reddit:
        L += ["- Reddit threads were parsed into reply trees with anonymised authors. "
              + (f"{triage['n_selected']} of {triage['n_candidates']} substantive posts/comments were selected for "
                 f"detailed coding (every post, top-scored, signal-flagged, and a spread across topic clusters; "
                 f"max {triage['per_author_cap']} per author). {triage['n_echo_replies']} short agree/disagree "
                 "replies were counted as echoes rather than coded." if triage else "All posts/comments were read."),
              "- Coverage counts distinct authors, so one prolific poster counts once.",
              "- Forum posters are self-selected and skew towards people with strong feelings, often "
              "complaints. Treat findings as what an engaged, vocal segment says, not what all users think. "
              "Upvotes reflect visibility and community taste as well as agreement.",
              "- Coding was AI-assisted. Spot-check nuggets against the threads before acting on them.",
              "- Sentiment figures come from a separate random sample, because the comments chosen for "
              "detailed coding deliberately over-represent complaints. Aspect sentiment was coded by AI "
              "(handling negation, sarcasm and implied opinions better than word lists, but not perfectly). "
              "Ranges are 95% intervals; small differences between drivers may not be real.",
              "- The outlook is reasoned judgement from forum signals, which lead or lag real behaviour "
              "unevenly. Check each call on its review date to learn how far to trust the next one.",
              "- Ethics: posts are public but written for a community, not for research. Keep "
              "authors_private.json private, and paraphrase rather than quote in anything published "
              "(`--redact-quotes` produces a shareable version).", ""]
        if not args.redact_quotes:
            L.append("Threads: " + "; ".join(f"{m['transcript_id']} = r/{m.get('subreddit')}: {trim(m.get('title'), 70)}"
                                             for m in C.manifest))
            L.append("")
    else:
        L += ["- Transcripts were parsed into speaker turns and coded one at a time into nuggets "
              "(verbatim quote + interpretation), each checked to appear verbatim in the cited turn.",
              "- Evidence types, strongest first: observed in session, specific past incident, habitual "
              "practice, opinion, hypothetical. Insights leaning on opinion or hypotheticals are weaker.",
              "- Coding was AI-assisted. Spot-check a sample of nuggets against the transcripts before "
              "acting on high-stakes findings.",
              "- Hesitation signals depend on verbatim transcription and vary by person, culture and "
              "interview rapport. Treat them as pointers.",
              "- Clusters depend on method and k. Low coverage or single-transcript dominance means the "
              "cluster may reflect one talkative participant.", ""]
        if not args.redact_quotes:
            L += ["Source files: " + ", ".join(f"{m['transcript_id']}={m['source_file']}" for m in C.manifest), ""]

    (work / "report.md").write_text("\n".join(L), encoding="utf-8")

    fields = ["id", "transcript_id", "author_id", "turn_ids", "quote", "observation", "jtbd_force",
              "evidence_type", "friction", "severity", "speech_act", "tags", "score"]
    with open(work / "nuggets.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for n in nuggets:
            t = C.turn(n)
            row = dict(n)
            row.update({"turn_ids": ";".join(map(str, n["turn_ids"])), "tags": ";".join(n.get("tags", [])),
                        "author_id": t.get("author_id", ""), "score": t.get("score", "")})
            if args.redact_quotes:
                row["quote"] = ""
            w.writerow(row)
    print(f"Wrote {work}/report.md and {work}/nuggets.csv ({len(insights)} insights, "
          f"{len(unexamined)} unexamined flagged moments, {len(gaps)} possible gaps)"
          + (" [quotes redacted]" if args.redact_quotes else ""))


if __name__ == "__main__":
    main()
