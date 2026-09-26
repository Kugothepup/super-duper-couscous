#!/usr/bin/env python3
"""Measure sentiment, rank its drivers, and show direction of travel.

Input: WORK/sentiment/*.json, written while coding the RANDOM sample from triage.py.
Each file is a list of {"ref": "T01#23", "overall": -2..2, "aspects": {"pricing": -2, ...}}.

Output (WORK/drivers.json, and a printed summary):
  - overall sentiment: % negative / neutral / positive with 95% intervals, both per
    comment and per author (so prolific posters don't dominate)
  - drivers: each aspect's share of all negative aspect mentions, its negativity rate,
    and how many authors raised it; strengths likewise for positive mentions
  - uncertainty by resampling authors (a cluster bootstrap, 2,000 re-draws): ranges for the
    headline figures and each driver's share that respect one person posting many times,
    and the probability that each aspect is the top driver. Replicates are saved to
    drivers_boot.json so hypotheses.py can compute the probability of any measurable signal.
  - direction: if comments span several periods, % negative per period, per-aspect
    share over time, and the rate of switching language across the full corpus
  - stance (news/topic lens): % for / against the study's proposition, and what each
    side talks about
  - before/after (if study.json has event_date): change in % negative (and % for),
    with a Newcombe interval for the difference, and which aspects rose or fell

Usage:
  python drivers.py --work WORKDIR [--period auto|week|month] [--min-mentions 3]
"""
import argparse
import datetime as dt
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_json, load_manifest, load_signals, load_study, save_json, turn_index  # noqa: E402


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h) * 100, 1), round(min(1, c + h) * 100, 1))


def newcombe(k1, n1, k2, n2):
    """95% interval (percentage points) for p2 - p1, Newcombe (1998) method 10."""
    if not n1 or not n2:
        return None
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = [x / 100 for x in wilson(k1, n1)]
    l2, u2 = [x / 100 for x in wilson(k2, n2)]
    d = p2 - p1
    lo = d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    hi = d + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    return [round(100 * lo, 1), round(100 * hi, 1)]


def compare(name, k1, n1, k2, n2):
    ci = newcombe(k1, n1, k2, n2)
    verdict = "insufficient data"
    if ci and n1 >= 15 and n2 >= 15:
        verdict = "rose" if ci[0] > 0 else "fell" if ci[1] < 0 else "no clear change"
    return {"measure": name, "before_pct": pct(k1, n1), "after_pct": pct(k2, n2), "n_before": n1, "n_after": n2,
            "diff_pts": round(pct(k2, n2) - pct(k1, n1), 1), "diff_ci": ci, "verdict": verdict}


def pct(k, n):
    return round(100 * k / n, 1) if n else 0.0


def load_records(work):
    recs = {}
    d = Path(work) / "sentiment"
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        data = load_json(p)
        for r in (data.get("records", data) if isinstance(data, dict) else data):
            recs[r["ref"]] = r
    return list(recs.values())


def parse_time(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def period_key(t, unit):
    if unit == "month":
        return t.strftime("%Y-%m")
    iso = t.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--period", choices=["auto", "week", "month"], default="auto")
    ap.add_argument("--min-mentions", type=int, default=3)
    ap.add_argument("--min-per-period", type=int, default=15)
    ap.add_argument("--boot", type=int, default=2000, help="bootstrap re-draws (0 to skip)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    work = Path(args.work)

    recs = load_records(work)
    if not recs:
        raise SystemExit("No sentiment records in WORK/sentiment/. Code the random sample first.")
    tindex = turn_index(work)
    tri = load_json(work / "triage.json") if (work / "triage.json").exists() else {}
    for r in recs:
        tid, t = r["ref"].split("#")
        turn = tindex.get((tid, int(t)), {})
        r["_author"] = turn.get("author_id")
        r["_time"] = parse_time(turn.get("created"))
    n = len(recs)

    # overall
    neg = sum(r["overall"] < 0 for r in recs)
    pos = sum(r["overall"] > 0 for r in recs)
    by_author = defaultdict(list)
    for r in recs:
        by_author[r["_author"]].append(r["overall"])
    a_means = [sum(v) / len(v) for v in by_author.values()]
    a_neg = sum(m < 0 for m in a_means)
    overall = {
        "n_comments": n, "n_authors": len(by_author),
        "sample_of": tri.get("sentiment_population"),
        "negative_pct": pct(neg, n), "negative_ci": wilson(neg, n),
        "neutral_pct": pct(n - neg - pos, n),
        "positive_pct": pct(pos, n), "positive_ci": wilson(pos, n),
        "mean": round(sum(r["overall"] for r in recs) / n, 2),
        "authors_net_negative_pct": pct(a_neg, len(a_means)),
        "authors_net_negative_ci": wilson(a_neg, len(a_means)),
    }

    # aspects
    mentions = defaultdict(list)
    for r in recs:
        for a, s in (r.get("aspects") or {}).items():
            mentions[a.strip().lower()].append((s, r["_author"]))
    tot_neg = sum(1 for v in mentions.values() for s, _ in v if s < 0) or 1
    tot_pos = sum(1 for v in mentions.values() for s, _ in v if s > 0) or 1
    aspects = []
    for a, v in mentions.items():
        k_neg = sum(s < 0 for s, _ in v)
        k_pos = sum(s > 0 for s, _ in v)
        aspects.append({
            "aspect": a, "mentions": len(v), "authors": len({au for _, au in v}),
            "mean": round(sum(s for s, _ in v) / len(v), 2),
            "negative_rate_pct": pct(k_neg, len(v)), "negative_rate_ci": wilson(k_neg, len(v)),
            "share_of_negative_pct": pct(k_neg, tot_neg), "share_of_positive_pct": pct(k_pos, tot_pos),
            "mention_rate_pct": pct(len(v), n), "strong_negative": sum(s <= -2 for s, _ in v),
        })
    ranked = [a for a in aspects if a["mentions"] >= args.min_mentions]
    drivers = sorted([a for a in ranked if a["share_of_negative_pct"] > 0],
                     key=lambda a: (-a["share_of_negative_pct"], a["mean"]))
    strengths = sorted([a for a in ranked if a["share_of_positive_pct"] > 0],
                       key=lambda a: -a["share_of_positive_pct"])
    rare = sorted(a["aspect"] for a in aspects if a["mentions"] < args.min_mentions)

    # cluster bootstrap over authors
    boot = None
    if args.boot and len(by_author) >= 20:
        rng = random.Random(args.seed)
        groups = defaultdict(list)
        for r in recs:
            groups[r["_author"]].append(r)
        keys = list(groups)
        names = sorted(mentions)
        reps = {"negative_pct": [], "positive_pct": [], "top": [],
                "share_of_negative": {a: [] for a in names}, "negative_rate": {a: [] for a in names},
                "mention_rate": {a: [] for a in names}}
        for _ in range(args.boot):
            draw = [r for k in (rng.choice(keys) for _ in keys) for r in groups[k]]
            m = len(draw)
            reps["negative_pct"].append(100 * sum(r["overall"] < 0 for r in draw) / m)
            reps["positive_pct"].append(100 * sum(r["overall"] > 0 for r in draw) / m)
            negc, tot = Counter(), Counter()
            for r in draw:
                for a, sc in (r.get("aspects") or {}).items():
                    a = a.strip().lower()
                    tot[a] += 1
                    negc[a] += sc < 0
            tn = sum(negc.values()) or 1
            for a in names:
                reps["share_of_negative"][a].append(100 * negc[a] / tn)
                reps["negative_rate"][a].append(100 * negc[a] / tot[a] if tot[a] else float("nan"))
                reps["mention_rate"][a].append(100 * tot[a] / m)
            reps["top"].append(max(names, key=lambda a: (negc[a], -names.index(a))) if negc else None)

        def pci(xs):
            xs = sorted(x for x in xs if x == x)
            if not xs:
                return None
            return [round(xs[int(0.025 * (len(xs) - 1))], 1), round(xs[int(0.975 * (len(xs) - 1))], 1)]
        topc = Counter(reps["top"])
        overall["negative_ci_boot"] = pci(reps["negative_pct"])
        overall["positive_ci_boot"] = pci(reps["positive_pct"])
        for a in aspects:
            a["share_of_negative_ci"] = pci(reps["share_of_negative"][a["aspect"]])
            a["top_driver_prob"] = round(100 * topc.get(a["aspect"], 0) / args.boot, 1)
        boot = {"n": args.boot, "authors": len(keys), "replicates": reps}
        save_json(boot, work / "drivers_boot.json")
        # use the author-clustered ranges for the headline when available
        overall["negative_ci"] = overall["negative_ci_boot"] or overall["negative_ci"]
        overall["positive_ci"] = overall["positive_ci_boot"] or overall["positive_ci"]
        overall["ci_method"] = f"author-clustered bootstrap ({args.boot} re-draws)"
    else:
        overall["ci_method"] = "Wilson interval (too few authors to resample)"

    # direction
    times = [r["_time"] for r in recs if r["_time"]]
    direction = {"status": "no timestamps"}
    if times:
        span = (max(times) - min(times)).days
        unit = args.period if args.period != "auto" else ("month" if span > 60 else "week" if span > 14 else None)
        if not unit:
            direction = {"status": "single window", "span_days": span,
                         "note": "All sampled comments fall within about two weeks, so this is a snapshot. "
                                 "Collect threads across several months to see direction."}
        else:
            per = defaultdict(list)
            for r in recs:
                if r["_time"]:
                    per[period_key(r["_time"], unit)].append(r)
            keys = sorted(per)
            usable = [k for k in keys if len(per[k]) >= args.min_per_period]
            rows = []
            for k in keys:
                pr = per[k]
                kn = sum(r["overall"] < 0 for r in pr)
                am = Counter(a.lower() for r in pr for a in (r.get("aspects") or {}))
                rows.append({"period": k, "n": len(pr), "negative_pct": pct(kn, len(pr)),
                             "negative_ci": wilson(kn, len(pr)),
                             "top_aspects": {a: pct(c, len(pr)) for a, c in am.most_common(5)}})
            verdict = "insufficient data"
            if len(usable) >= 2:
                first = next(r for r in rows if r["period"] == usable[0])
                last = next(r for r in rows if r["period"] == usable[-1])
                if last["negative_ci"][0] > first["negative_ci"][1]:
                    verdict = "worsening"
                elif last["negative_ci"][1] < first["negative_ci"][0]:
                    verdict = "improving"
                else:
                    verdict = "no clear change"
            # switching language across the full corpus (not just the sample)
            sw = defaultdict(lambda: [0, 0])
            for m in load_manifest(work):
                s = load_signals(work, m["transcript_id"])
                if not s:
                    continue
                for st in s["turns"]:
                    turn = tindex.get((m["transcript_id"], st["turn_id"]), {})
                    tm = parse_time(turn.get("created"))
                    if tm and st.get("words", 0) >= 8:
                        key = period_key(tm, unit)
                        sw[key][1] += 1
                        sw[key][0] += "switching_language" in st.get("flags", [])
            direction = {"status": "ok", "unit": unit, "span_days": span, "periods": rows,
                         "usable_periods": usable, "negative_trend": verdict,
                         "switching_rate_per_100": {k: pct(v[0], v[1]) for k, v in sorted(sw.items())}}

    study = load_study(work)

    # stance (news/topic)
    stance = None
    sr = [r for r in recs if r.get("stance") is not None]
    if sr:
        kf = sum(r["stance"] > 0 for r in sr)
        ka = sum(r["stance"] < 0 for r in sr)
        side_asp = {"for": Counter(), "against": Counter()}
        for r in sr:
            side = "for" if r["stance"] > 0 else "against" if r["stance"] < 0 else None
            if side:
                side_asp[side].update(a.lower() for a in (r.get("aspects") or {}))
        stance = {"target": study.get("stance_target"), "n_expressing": len(sr), "n_sample": n,
                  "expressing_pct": pct(len(sr), n),
                  "for_pct": pct(kf, len(sr)), "for_ci": wilson(kf, len(sr)),
                  "against_pct": pct(ka, len(sr)), "against_ci": wilson(ka, len(sr)),
                  "neutral_pct": pct(len(sr) - kf - ka, len(sr)),
                  "for_talks_about": {a: pct(c, kf) for a, c in side_asp["for"].most_common(6)},
                  "against_talks_about": {a: pct(c, ka) for a, c in side_asp["against"].most_common(6)}}

    # before / after an event
    event = None
    ed = parse_time((study.get("event_date") or "") + " 00:00")
    if ed:
        pre = [r for r in recs if r["_time"] and r["_time"] < ed]
        post = [r for r in recs if r["_time"] and r["_time"] >= ed]
        measures = [compare("negative", sum(r["overall"] < 0 for r in pre), len(pre),
                            sum(r["overall"] < 0 for r in post), len(post))]
        spre = [r for r in pre if r.get("stance") is not None]
        spost = [r for r in post if r.get("stance") is not None]
        if spre and spost:
            measures.append(compare("for", sum(r["stance"] > 0 for r in spre), len(spre),
                                    sum(r["stance"] > 0 for r in spost), len(spost)))
        shifts = []
        for a in {a.lower() for r in recs for a in (r.get("aspects") or {})}:
            k1 = sum(a in {x.lower() for x in (r.get("aspects") or {})} for r in pre)
            k2 = sum(a in {x.lower() for x in (r.get("aspects") or {})} for r in post)
            c = compare(a, k1, len(pre), k2, len(post))
            if c["verdict"] in ("rose", "fell"):
                shifts.append(c)
        shifts.sort(key=lambda c: -abs(c["diff_pts"]))
        ev_period = period_key(ed, direction["unit"]) if direction.get("status") == "ok" else None
        event = {"date": study["event_date"], "period": ev_period, "measures": measures, "aspect_shifts": shifts[:8],
                 "note": "Before/after comparison of the random sample. Other things also change over time, "
                         "so a shift is consistent with the event's effect but does not prove it."}

    # by source (site / subreddit): results can be dominated by whichever source supplied most
    site_of = {m["transcript_id"]: (m.get("site") or m.get("subreddit") or m.get("source_file") or "?")
               for m in load_manifest(work)}
    bys = defaultdict(list)
    for r in recs:
        bys[site_of.get(r["ref"].split("#")[0], "?")].append(r)
    by_source = sorted(({"source": k, "n": len(v), "share_pct": pct(len(v), n),
                         "negative_pct": pct(sum(r["overall"] < 0 for r in v), len(v)),
                         "negative_ci": wilson(sum(r["overall"] < 0 for r in v), len(v))}
                        for k, v in bys.items()), key=lambda x: -x["n"])
    overall["small_sample"] = n < 60
    overall["dominant_source"] = by_source[0]["source"] if by_source and by_source[0]["share_pct"] > 50 \
        and len(by_source) > 1 else None

    out = {"by_source": by_source, "overall": overall, "drivers": drivers, "strengths": strengths, "all_aspects": aspects,
           "rare_aspects": rare, "direction": direction, "stance": stance, "event": event}
    save_json(out, work / "drivers.json")

    o = overall
    print(f"Sample: {n} comments from {o['n_authors']} authors"
          + (f" (random draw from {o['sample_of']})" if o["sample_of"] else ""))
    print(f"Negative {o['negative_pct']}% (95% CI {o['negative_ci'][0]}-{o['negative_ci'][1]}) · "
          f"neutral {o['neutral_pct']}% · positive {o['positive_pct']}% · mean {o['mean']}")
    print(f"Authors net negative: {o['authors_net_negative_pct']}%")
    print(f"Ranges: {overall['ci_method']}")
    print("\nDrivers of negativity (share of negative aspect mentions):")
    for a in drivers[:8]:
        rng_txt = f" ({a['share_of_negative_ci'][0]}-{a['share_of_negative_ci'][1]})" if a.get("share_of_negative_ci") else ""
        top_txt = f"  top driver in {a['top_driver_prob']}% of re-draws" if a.get("top_driver_prob") else ""
        print(f"  {a['aspect']:<22} {a['share_of_negative_pct']:>5}%{rng_txt}  neg-rate {a['negative_rate_pct']}%  "
              f"authors {a['authors']}{top_txt}")
    print("Strengths (share of positive mentions):")
    for a in strengths[:5]:
        print(f"  {a['aspect']:<22} {a['share_of_positive_pct']:>5}%  mean {a['mean']}")
    if rare:
        print(f"\nAspects with < {args.min_mentions} mentions (merge synonyms?): {', '.join(rare[:20])}")
    if stance:
        print(f"\nStance on '{stance['target']}': for {stance['for_pct']}% ({stance['for_ci'][0]}-{stance['for_ci'][1]}), "
              f"against {stance['against_pct']}% ({stance['against_ci'][0]}-{stance['against_ci'][1]}), "
              f"of {stance['n_expressing']} expressing a position")
    if event:
        for mz in event["measures"]:
            print(f"Around {event['date']}: % {mz['measure']} {mz['before_pct']} -> {mz['after_pct']} "
                  f"(diff {mz['diff_pts']}, 95% {mz['diff_ci']}) {mz['verdict']}")
    d = direction
    print(f"\nDirection: {d.get('negative_trend', d['status'])}" + (f" ({d.get('note')})" if d.get("note") else ""))


if __name__ == "__main__":
    main()
