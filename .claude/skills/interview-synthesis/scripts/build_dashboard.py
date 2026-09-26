#!/usr/bin/env python3
"""Build a self-contained HTML dashboard of the whole study.

Sections: verdict and sentiment, drivers and strengths, direction over time, themes,
pain points, success moments, jobs to be done, opportunities, alternatives in play,
outlook (probabilities), language, and how much to trust the findings.
Tap any aspect to focus every section on it. Anything resting on thin evidence
(a single voice, low confidence) is drawn hatched instead of solid.

Reads whatever exists in WORK: manifest, drivers.json, insights.json, nuggets/,
jobs.json, opportunities.json, outlook.json, language.json, themes.json, triage.json,
validation.json. Missing parts show an empty state saying which step fills them.

Reddit dashboards never include verbatim quotes. Interview dashboards include
them only with --include-quotes.

Usage:
  python build_dashboard.py --work WORKDIR --title "Subject" [--include-quotes] [--out FILE]
Writes WORKDIR/dashboard.html (or --out).
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (FRAMES, LIKELIHOOD, STRONG_EVIDENCE, entity_tags, load_json,  # noqa: E402
                     load_manifest, load_nuggets, load_study, study_mode, total_units, turn_index,
                     unit_of)


def opt(work, name, key=None):
    p = Path(work) / name
    if not p.exists():
        return None
    d = load_json(p)
    if key and isinstance(d, dict):
        return d.get(key, [])
    return d


def rng(phrase):
    lo, hi = LIKELIHOOD[phrase].rstrip("%").split("-")
    return [int(lo), int(hi)]


def group_by_aspect(ns):
    g = defaultdict(list)
    for n in ns:
        g[(n.get("aspect") or "other").lower()].append(n)
    return g


def build_data(work, title, include_quotes):
    manifest = load_manifest(work)
    mode = study_mode(manifest)
    study = load_study(work)
    lens = dict(study.pop("lens"))
    lens["type"] = study["type"]
    title = title or study.get("subject") or "Study dashboard"
    tindex = turn_index(work)
    nuggets = [n for ns in load_nuggets(work).values() for n in ns]
    by_id = {n["id"]: n for n in nuggets}
    quotes = include_quotes and mode != "reddit"

    def unit(n):
        return unit_of(n, mode, tindex)

    def ev(n):
        t = tindex.get((n["transcript_id"], n["turn_ids"][0]), {})
        e = {"id": n["id"], "obs": n.get("observation", ""), "aspect": (n.get("aspect") or "").lower(),
             "force": n.get("jtbd_force"), "ev": n.get("evidence_type"), "sev": n.get("severity"),
             "who": unit(n), "strong": n.get("evidence_type") in STRONG_EVIDENCE}
        if mode == "reddit":
            e["score"] = t.get("score", 0)
        if quotes:
            e["quote"] = n.get("quote", "")
        return e

    def aspects_of(ns):
        return sorted({(n.get("aspect") or "").lower() for n in ns if n.get("aspect")})

    drv = opt(work, "drivers.json")
    triage = opt(work, "triage.json")
    themes = opt(work, "themes.json")
    lang = opt(work, "language.json")
    validation = opt(work, "validation.json")
    insights = opt(work, "insights.json", "insights") or []
    jobs = opt(work, "jobs.json", "jobs") or []
    opps = opt(work, "opportunities.json", "opportunities") or []
    outlook = opt(work, "outlook.json", "outlook") or []

    times = sorted(t.get("created") for t in tindex.values() if t.get("created"))
    meta = {
        "title": title, "mode": mode,
        "sources": (sorted({m.get("site") or ("r/" + m["subreddit"]) for m in manifest
                            if m.get("site") or m.get("subreddit")})
                    if mode == "reddit" else [f"{len(manifest)} interviews"]),
        "n_docs": len(manifest), "n_items": sum(m["n_turns"] for m in manifest),
        "n_people": total_units(work, mode, manifest),
        "window": [times[0][:10], times[-1][:10]] if times else None,
        "n_nuggets": len(nuggets), "n_read": triage["n_selected"] if triage else None,
        "unit": "people" if mode == "reddit" else "participants",
    }

    # insights / themes
    ins_out = []
    for i in insights:
        sup = [by_id[r] for r in i.get("nugget_ids", []) if r in by_id]
        con = [by_id[r] for r in i.get("counter_nugget_ids", []) if r in by_id]
        ins_out.append({"id": i["id"], "statement": i["statement"], "confidence": i.get("confidence"),
                        "voices": len({unit(n) for n in sup}),
                        "strong": sum(n.get("evidence_type") in STRONG_EVIDENCE for n in sup),
                        "n": len(sup), "evidence": [ev(n) for n in sup], "counter": [ev(n) for n in con],
                        "recs": i.get("recommendations", []), "aspects": aspects_of(sup + con)})

    # pain points and successes grouped by aspect
    def group(ns):
        g = defaultdict(list)
        for n in ns:
            g[(n.get("aspect") or "other").lower()].append(n)
        out = []
        for a, items in g.items():
            sev = [n.get("severity") or 0 for n in items]
            out.append({"aspect": a, "voices": len({unit(n) for n in items}), "n": len(items),
                        "max_sev": max(sev) if sev else 0,
                        "mean_sev": round(sum(sev) / len(sev), 1) if sev else 0,
                        "strong": sum(n.get("evidence_type") in STRONG_EVIDENCE for n in items),
                        "evidence": [ev(n) for n in items]})
        return out
    pains = sorted(group([n for n in nuggets if n.get("friction")]),
                   key=lambda g: (-(g["voices"] * g["max_sev"]), -g["n"]))
    succ = sorted(group([n for n in nuggets if n.get("success")]), key=lambda g: (-g["voices"], -g["n"]))

    # jobs with forces balance
    jobs_out = []
    for j in jobs:
        ns = [by_id[r] for r in j.get("nugget_ids", []) if r in by_id]
        f = Counter(n.get("jtbd_force") for n in ns)
        jobs_out.append({"id": j["id"], "job": j["job"], "forces": {k: f.get(k, 0) for k in
                                                                    ("push", "pull", "anxiety", "habit")},
                         "voices": len({unit(n) for n in ns}), "evidence": [ev(n) for n in ns],
                         "aspects": aspects_of(ns)})

    # opportunities with evidence metrics
    neg_rate = {a["aspect"]: a["negative_rate_pct"] for a in (drv or {}).get("all_aspects", [])}
    opp_out = []
    for o in opps:
        ns = [by_id[r] for r in o.get("nugget_ids", []) if r in by_id]
        sev = [n.get("severity") or 0 for n in ns if n.get("friction")]
        voices = len({unit(n) for n in ns})
        mean_sev = round(sum(sev) / len(sev), 1) if sev else 0
        asp = (o.get("aspect") or "").lower()
        opp_out.append({"id": o["id"], "statement": o["statement"], "kind": o.get("kind"), "aspect": asp,
                        "voices": voices, "mean_sev": mean_sev, "neg_rate": neg_rate.get(asp),
                        "rank_score": voices * (1 + mean_sev), "insights": o.get("insight_ids", []),
                        "evidence": [ev(n) for n in ns], "aspects": sorted({asp} | set(aspects_of(ns)) - {""})})
    opp_out.sort(key=lambda o: -o["rank_score"])

    # outlook
    out_out = []
    for o in outlook:
        asp = sorted({b.split(":", 1)[1] for b in o.get("basis", []) if b.startswith(("driver:", "strength:"))})
        ns = [by_id[b] for b in o.get("basis", []) if b in by_id]
        out_out.append({"id": o["id"], "statement": o["statement"], "likelihood": o.get("likelihood"),
                        "range": rng(o["likelihood"]) if o.get("likelihood") in LIKELIHOOD else None,
                        "horizon": o.get("horizon"), "review_by": o.get("review_by"),
                        "change": o.get("would_change_if"), "basis": o.get("basis", []),
                        "aspects": sorted(set(asp) | set(aspects_of(ns)))})

    # entities: products, brands, actors
    prods = defaultdict(lambda: {"push": 0, "pull": 0, "anxiety": 0, "habit": 0, "voices": set(),
                                 "sent": [], "n": 0})
    for n in nuggets:
        for name in entity_tags(n.get("tags", [])):
            p = prods[name]
            p["n"] += 1
            if n.get("jtbd_force") in ("push", "pull", "anxiety", "habit"):
                p[n["jtbd_force"]] += 1
            if isinstance(n.get("sentiment"), int):
                p["sent"].append(n["sentiment"])
            p["voices"].add(unit(n))
    products = sorted(({"name": k, **{f: v[f] for f in ("push", "pull", "anxiety", "habit")}, "n": v["n"],
                        "mean": round(sum(v["sent"]) / len(v["sent"]), 2) if v["sent"] else None,
                        "voices": len(v["voices"])} for k, v in prods.items()), key=lambda x: -x["voices"])

    # framing (news/topic): Entman's four functions
    frames = []
    for f in FRAMES[:-1]:
        ns = [n for n in nuggets if n.get("frame") == f]
        if ns:
            frames.append({"frame": f, "n": len(ns), "voices": len({unit(n) for n in ns}),
                           "evidence": [ev(n) for n in ns], "aspects": aspects_of(ns)})
    # questions people ask
    qs = [n for n in nuggets if "question" in [t.lower() for t in n.get("tags", [])]]
    questions = sorted(((a, [ev(n) for n in ns]) for a, ns in
                        group_by_aspect(qs).items()), key=lambda x: -len(x[1]))

    trust = {
        "sentiment_sample": (drv or {}).get("overall", {}).get("n_comments"),
        "sample_of": (drv or {}).get("overall", {}).get("sample_of"),
        "read_in_detail": triage["n_selected"] if triage else None,
        "candidates": triage["n_candidates"] if triage else None,
        "per_author_cap": triage["per_author_cap"] if triage else None,
        "echoes": triage["n_echo_replies"] if triage else None,
        "validation": validation,
        "silhouette": themes.get("silhouette") if themes else None,
        "direction_status": (drv or {}).get("direction", {}).get("status"),
        "evidence_mix": dict(Counter(n.get("evidence_type") for n in nuggets)),
        "quotes": "included" if quotes else "withheld",
    }
    meta["title"] = title
    hyp = opt(work, "hypotheses_result.json")
    # how the material was found
    coll = defaultdict(lambda: {"threads": 0, "posts": 0, "queries": set(), "kinds": set()})
    for m in manifest:
        k = m.get("site") or m.get("subreddit") or "?"
        coll[k]["threads"] += 1
        coll[k]["posts"] += m["n_turns"]
        if m.get("search_query"):
            coll[k]["queries"].add(m["search_query"])
        if m.get("capture_kind"):
            coll[k]["kinds"].add(m["capture_kind"])
    trust["collection"] = [{"site": k, "threads": v["threads"], "posts": v["posts"],
                            "queries": sorted(v["queries"]), "kinds": sorted(v["kinds"])} for k, v in coll.items()]
    trust["collection_log"] = opt(work, "collection_log.json", "searches")
    trust["forum_checks"] = opt(work, "forum_checks.json")
    return {"meta": meta, "hypotheses": hyp, "study": study, "lens": lens, "drivers": drv, "insights": ins_out, "pains": pains,
            "successes": succ, "jobs": jobs_out, "opportunities": opp_out, "outlook": out_out,
            "products": products, "frames": frames,
            "questions": [{"aspect": a, "evidence": e} for a, e in questions],
            "language": lang, "trust": trust}


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#EEF1F0; --panel:#F8FAF9; --ink:#16302C; --muted:#566663; --rule:#CBD5D2;
  --neg:#A8324E; --pos:#22786A; --neu:#A3AEAB; --prob:#3B4F9E; --focus:#3B4F9E; --for:#2F5F8A; --against:#96661C;
  --neg-soft:#A8324E22; --pos-soft:#22786A22; --prob-soft:#3B4F9E22;
  --serif:"Newsreader","Iowan Old Style","Palatino Linotype",Georgia,serif;
  --sans:"Public Sans","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
  box-sizing:border-box; padding-top:env(safe-area-inset-top,0px); padding-bottom:env(safe-area-inset-bottom,0px);
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0F1716; --panel:#16211F; --ink:#E3ECE9; --muted:#97A8A3; --rule:#2B3A37;
    --neg:#E27791; --pos:#5CC3AE; --neu:#5F6E6B; --prob:#9AAAF0; --focus:#9AAAF0; --for:#7FB0DB; --against:#D9A548;
    --neg-soft:#E2779126; --pos-soft:#5CC3AE26; --prob-soft:#9AAAF026; color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0F1716; --panel:#16211F; --ink:#E3ECE9; --muted:#97A8A3; --rule:#2B3A37;
  --neg:#E27791; --pos:#5CC3AE; --neu:#5F6E6B; --prob:#9AAAF0; --focus:#9AAAF0; --for:#7FB0DB; --against:#D9A548;
  --neg-soft:#E2779126; --pos-soft:#5CC3AE26; --prob-soft:#9AAAF026; color-scheme:dark;
}
*,*::before,*::after{box-sizing:inherit}
html{scroll-padding-top:calc(env(safe-area-inset-top,0px) + 64px)}
body{margin:0;overflow-x:clip;background:var(--bg);color:var(--ink);font:400 15px/1.55 var(--sans);font-variant-numeric:tabular-nums;-webkit-text-size-adjust:100%}
a{color:inherit}
button{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:3px}
.wrap{display:grid;grid-template-columns:200px minmax(0,1fr);gap:40px;max-width:1180px;margin:0 auto;padding:32px 24px 80px}
nav.rail{position:sticky;top:calc(env(safe-area-inset-top,0px) + 24px);align-self:start;font-size:14px}
nav.rail a{display:block;padding:5px 0 5px 12px;text-decoration:none;color:var(--muted);border-left:2px solid var(--rule)}
nav.rail a:hover{color:var(--ink);border-left-color:var(--ink)}
main{min-width:0}
header.verdict{padding-bottom:28px;border-bottom:1px solid var(--rule)}
.subject{font:500 15px/1.3 var(--sans);color:var(--muted);margin:0 0 14px}
h1{font:500 clamp(28px,4.4vw,46px)/1.12 var(--serif);letter-spacing:-.01em;margin:0 0 22px;max-width:30ch}
.facts{display:flex;flex-wrap:wrap;gap:8px 28px;margin:18px 0 0;padding:0;list-style:none;font-size:14px;color:var(--muted)}
.facts b{display:block;font:600 20px/1.2 var(--sans);color:var(--ink)}
section{padding:36px 0 8px;border-bottom:1px solid var(--rule)}
h2{font:500 26px/1.2 var(--serif);margin:0 0 6px}
.lede{color:var(--muted);margin:0 0 20px;max-width:68ch}
h3{font:600 15px/1.35 var(--sans);margin:0}
.strip{position:relative;margin-top:6px}
.strip .bar{display:flex;height:34px;border-radius:4px;overflow:hidden}
.strip .bar span{display:block;height:100%}
.strip .bar span.n{background:var(--neg)} .strip .bar span.u{background:var(--neu)} .strip .bar span.p{background:var(--pos)}
.strip .ci{position:absolute;top:-6px;height:46px;border:2px solid var(--ink);border-top:0;border-bottom:0;opacity:.75;pointer-events:none}
.strip .legend{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px 16px;font-size:14px;margin-top:10px}
.strip .legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
@media (prefers-reduced-motion:no-preference){.strip .bar span{animation:grow .9s cubic-bezier(.2,.7,.2,1) both}}
@keyframes grow{from{flex-basis:0!important;width:0}}
.focusbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--ink);color:var(--bg);padding:10px 14px;border-radius:0 0 6px 6px;display:none;align-items:center;justify-content:space-between;gap:12px;font-size:14px}
.focusbar.on{display:flex}
.focusbar button{background:transparent;border:1px solid currentColor;border-radius:4px;padding:4px 10px;cursor:pointer}
.asp{background:none;border:0;padding:0;cursor:pointer;text-decoration:underline;text-decoration-color:var(--rule);text-underline-offset:3px;font-weight:600}
.asp:hover{text-decoration-color:currentColor}
.chip{display:inline-block;font-size:13px;padding:1px 8px;border:1px solid var(--rule);border-radius:999px;color:var(--muted);background:none;cursor:pointer}
.chip:hover{color:var(--ink);border-color:var(--ink)}
.rows{display:grid;gap:10px}
.drow{display:grid;grid-template-columns:130px minmax(0,1fr) auto;align-items:center;gap:14px}
.drow .asp{justify-self:start;text-align:left}
.drow.stack{grid-template-columns:110px minmax(0,1fr);row-gap:2px}
.drow.stack .num{grid-column:2;white-space:normal}
.track{height:14px;background:var(--rule);border-radius:3px;overflow:hidden}
.fill{height:100%;border-radius:3px}
.fill.neg{background:var(--neg)} .fill.pos{background:var(--pos)} .fill.prob{background:var(--prob)} .fill.ink{background:var(--ink)}
.thin{background-image:repeating-linear-gradient(135deg,currentColor 0 2px,transparent 2px 6px)!important;background-color:transparent!important}
.fill.neg.thin{color:var(--neg)} .fill.pos.thin{color:var(--pos)} .fill.ink.thin{color:var(--ink)}
.num{font-size:14px;color:var(--muted);white-space:nowrap}
.two{display:grid;grid-template-columns:1fr 1fr;gap:32px}
.item{padding:18px 0;border-top:1px solid var(--rule)}
.item:first-child{border-top:0;padding-top:4px}
.item .stmt{font:500 19px/1.35 var(--serif);margin:0 0 8px;max-width:62ch}
.metaline{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:14px;color:var(--muted);align-items:center}
.metaline .cov{display:inline-flex;align-items:center;gap:8px}
.metaline .cov .track{width:90px;height:8px}
.conf-high{color:var(--ink);font-weight:600} .conf-low{font-style:italic}
details{margin-top:8px}
details.more{margin-top:14px}
details.more>summary{font-weight:600}
summary{cursor:pointer;font-size:14px;color:var(--muted)}
summary:hover{color:var(--ink)}
.ev{list-style:none;margin:8px 0 0;padding:0 0 0 14px;border-left:2px solid var(--rule);font-size:14px}
.ev li{margin:6px 0}
.ev .tag{color:var(--muted)}
.ev q{display:block;font-style:italic;color:var(--muted);margin-top:2px}
.recs{margin:10px 0 0;padding:0 0 0 18px;font-size:14px}
.pips{display:inline-flex;gap:3px;vertical-align:middle}
.pips span{width:9px;height:9px;border-radius:50%;border:1.5px solid var(--neg)}
.pips span.on{background:var(--neg)}
.forces{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:10px 0 4px;max-width:520px}
.forces .side{display:flex;height:18px}
.forces .side.l{justify-content:flex-end;border-right:2px solid var(--ink)}
.forces .seg{height:100%;font-size:11px;line-height:18px;color:var(--bg);text-align:center;overflow:hidden;white-space:nowrap}
.f-push{background:var(--neg)} .f-pull{background:var(--pos)} .f-anxiety{background:var(--prob)} .f-habit{background:var(--neu);color:var(--ink)!important}
.forces-key{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:13px;color:var(--muted);margin-bottom:8px}
.forces-key i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.probaxis{position:relative;height:22px;background:var(--rule);border-radius:3px;margin:10px 0 4px;max-width:520px}
.probaxis .band{position:absolute;top:0;bottom:0;background:var(--prob);border-radius:3px}
.probaxis .tick{position:absolute;top:24px;font-size:12px;color:var(--muted);transform:translateX(-50%)}
.likely{font-weight:600;color:var(--prob)}
.words{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.words li{display:grid;grid-template-columns:minmax(0,150px) minmax(0,1fr) auto;gap:10px;align-items:center;font-size:14px}
.words .w{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.phrases{display:flex;flex-wrap:wrap;gap:8px}
.phrases span{font:400 16px/1.3 var(--serif);padding:4px 10px;border:1px solid var(--rule);border-radius:4px}
.phrases span small{font:400 12px var(--sans);color:var(--muted);margin-left:6px}
.spark{width:100%;height:120px;display:block}
table.tbl{border-collapse:collapse;width:100%;font-size:14px}
.tbl th,.tbl td{text-align:left;padding:8px 10px 8px 0;border-bottom:1px solid var(--rule);vertical-align:middle}
.tbl th{font-weight:600;color:var(--muted)}
.scroll{overflow-x:auto}
.mini{display:flex;height:10px;width:140px;border-radius:2px;overflow:hidden;background:var(--rule)}
.empty{padding:16px;border:1px dashed var(--rule);border-radius:6px;color:var(--muted);font-size:14px}
.trust dl{display:grid;grid-template-columns:minmax(0,220px) minmax(0,1fr);gap:10px 20px;margin:0;font-size:14px}
.trust dt{color:var(--muted)} .trust dd{margin:0}
.warnline{color:var(--neg)}
.keyline{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin:0 0 16px}
.keyline span{display:inline-flex;align-items:center;gap:6px}
.keyline .sw{width:26px;height:10px;border-radius:2px;background:var(--ink)}
.keyline .sw.thin{color:var(--ink)}
.fill.for{background:var(--for)} .fill.against{background:var(--against)}
.proposition{font:italic 400 18px/1.4 var(--serif);color:var(--muted);margin:-10px 0 22px;max-width:60ch}
.scatter{width:100%;min-width:520px;height:auto;display:block}
.scatter .pt{cursor:pointer}
.scatter .pt:focus-visible{outline:none}
.scatter .pt:focus-visible circle{stroke:var(--focus);stroke-width:3}
.dvg{position:relative;display:inline-block;width:140px;height:10px;background:var(--rule);border-radius:2px;vertical-align:middle}
.dvg::after{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--ink)}
.dvg span{position:absolute;top:0;bottom:0;border-radius:2px}
.shifts{margin:0;padding-left:18px;font-size:14px}
.caution{margin:18px 0 0;padding:10px 14px;border-left:3px solid var(--neg);background:var(--neg-soft);font-size:14px;max-width:72ch}
.safe{margin:22px 0 0;padding:14px 16px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);max-width:760px}
.safe-h{margin:0 0 6px;font-weight:600;font-size:14px}
.safe-t{margin:0;font:400 17px/1.45 var(--serif)}
.safe-n{margin:8px 0 10px;font-size:13px;color:var(--muted)}
.owner{margin:0 0 4px;font-size:14px;color:var(--muted)}
.hverdict{margin:0 0 10px;font:600 20px/1.3 var(--sans)}
.hverdict.v-supported{color:var(--pos)} .hverdict.v-contradicted{color:var(--neg)} .hverdict.v-mixed{color:var(--against)} .hverdict.v-not-testable{color:var(--muted)}
.preds{list-style:none;margin:0;padding:0}
.pred{padding:12px 0 12px 14px;border-left:2px solid var(--rule);margin:8px 0}
.pred-h{font-size:15px;margin-bottom:6px}
.vchip{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;border:1px solid currentColor;margin-right:6px}
.vchip.v-supported{color:var(--pos)} .vchip.v-contradicted{color:var(--neg)} .vchip.v-mixed{color:var(--against)} .vchip.v-not-testable{color:var(--muted)}
.pred-bar{display:flex;height:8px;max-width:360px;background:var(--rule);border-radius:2px;overflow:hidden;margin-bottom:6px}
.pred-bar span{display:block;height:100%}
.strength{font-weight:500}
.strength.s-weak{color:var(--muted);font-style:italic}
.track.rel{position:relative;overflow:visible}
.whisk{position:absolute;top:-4px;bottom:-4px;border:1.5px solid var(--ink);border-top:0;border-bottom:0;opacity:.7}
.amap{width:100%;min-width:420px;max-width:620px;height:auto;display:block;margin-bottom:6px}
.pbar{position:relative;height:12px;max-width:420px;background:var(--rule);border-radius:2px;margin:4px 0}
.pbar .zone{position:absolute;top:0;bottom:0;width:20%;opacity:.18}
.pbar .zone.lo{left:0;background:var(--neg)} .pbar .zone.hi{right:0;background:var(--pos)}
.pbar .mark{position:absolute;top:-3px;bottom:-3px;width:3px;margin-left:-1.5px;background:var(--ink);border-radius:1px}
.pbar .range{position:absolute;top:0;bottom:0;background:var(--prob);border-radius:2px}
.pbar .mid{position:absolute;left:50%;top:-3px;bottom:-3px;width:1px;background:var(--ink)}
.prio{display:inline-block;font:600 12px/1.4 var(--sans);padding:2px 9px;border-radius:999px;margin-left:8px;vertical-align:3px;border:1px solid var(--rule);color:var(--muted)}
.prio.p-test-first{background:var(--neg);color:var(--bg);border-color:var(--neg)}
.next{margin-top:12px;padding:12px 16px;border:1px solid var(--rule);border-radius:6px;background:var(--panel);font-size:14px;max-width:760px}
.next p{margin:4px 0} .next ul{margin:4px 0 0;padding-left:18px}
.hide{display:none!important}
.topline{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin:0 0 14px}
.topline .subject{margin:0}
.theme-t{flex:none;background:none;border:1px solid var(--rule);border-radius:4px;padding:3px 10px;font-size:13px;color:var(--muted);cursor:pointer}
.theme-t:hover{color:var(--ink);border-color:var(--ink)}
@media (max-width:860px){
  .wrap{grid-template-columns:1fr;gap:0;padding:0 16px 64px}
  nav.rail{position:sticky;top:0;z-index:4;background:var(--bg);display:flex;overflow-x:auto;gap:4px;padding:calc(env(safe-area-inset-top,0px) + 10px) 0 10px;margin:0 -16px;padding-left:16px;padding-right:16px;border-bottom:1px solid var(--rule);scrollbar-width:none}
  nav.rail a{white-space:nowrap;border:1px solid var(--rule);border-radius:999px;padding:5px 12px}
  header.verdict{padding-top:24px}
  .two{grid-template-columns:1fr;gap:24px}
  .drow{grid-template-columns:96px minmax(0,1fr);row-gap:4px}
  .drow .num{grid-column:2}
  .trust dl{grid-template-columns:1fr}
  .trust dt{margin-top:8px}
  .focusbar{top:54px}
}
</style>
</head>
<body>
<div class="wrap">
  <nav class="rail" id="rail" aria-label="Sections"></nav>
  <main id="main">
    <div class="focusbar" id="focusbar" role="status"><span id="focustext"></span><button type="button" id="clearFocus">Show everything</button></div>
  </main>
</div>
<script type="application/json" id="data">__DATA__</script>
<script>
__JS__
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--title", help="defaults to the subject in study.json")
    ap.add_argument("--include-quotes", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()
    data = build_data(args.work, args.title, args.include_quotes)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    js = (Path(__file__).parent / "dashboard.js").read_text(encoding="utf-8")
    html = (HTML.replace("__JS__", js).replace("__DATA__", blob)
            .replace("__TITLE__", data["meta"]["title"].replace("<", "&lt;")))
    out = Path(args.out) if args.out else Path(args.work) / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out} ({len(html) // 1024} KB). Sections with no data show which step fills them.")


if __name__ == "__main__":
    main()
