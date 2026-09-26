#!/usr/bin/env python3
"""Hypotheses for discovery: the handover from these findings to real research.

Forum and interview samples like these are good at suggesting where to look and weak at
proving anything. So hypotheses come at the END of the findings, as starting points for
discovery: what the signals suggest, how strongly, and how to test each one properly.

They come from two places:
  origin "stated": the user's own belief (e.g. their strategy), written down before reading
                   the data where possible, so it can't be quietly reshaped by it
  origin "formed": suggested by this data. These are never "tested" by the same data
                   (that is circular); the signals only suggest them

WORK/hypotheses.json:
{"hypotheses": [
  {"id": "H1", "origin": "stated", "owner": "ours",
   "statement": "We believe research teams leave Notion mainly because of the price rise",
   "importance": "high",
   "signals": [
     {"id": "H1a", "text": "Pricing is the top driver of negativity",
      "test": {"type": "top_driver", "aspect": "pricing"}},
     {"id": "H1b", "text": "Pricing outweighs offline as a source of negativity",
      "test": {"type": "greater", "a": "pricing", "b": "offline", "measure": "share_of_negative"}},
     {"id": "H1c", "text": "Most people who say they left name price",
      "test": {"type": "proportion", "k_ids": ["T01-N01"], "n_ids": ["T01-N01", "T02-N02"]}},
     {"id": "H1d", "text": "Stayers accept the price because of features",
      "for": ["T01-N03"], "against": []}],
   "not_distinguishing": ["T02-N01"],
   "next_step": {"method": "8-10 interviews with research leads who cancelled or downgraded",
                 "recruit": "Leads of research teams of 5+ who left or downgraded in the last 6 months",
                 "confirm": "Most name price unprompted as the trigger",
                 "disconfirm": "Price comes up only after other reasons, or not at all",
                 "questions": ["Walk me through the last time you reconsidered your notes tool"]}}]}

Signal tests (probabilities use the author-clustered bootstrap from drivers.py; 20+ authors):
  top_driver   {aspect}                                 P(aspect is the largest source of negativity)
  greater      {a, b, measure}                          P(a > b); measure = share_of_negative,
                                                        negative_rate or mention_rate
  above        {aspect, measure, threshold}             P(measure > threshold, in %)
  proportion   {k_ids, n_ids}                           k of n coded comments, with a likely range
  (no test)    {for, against}                           independent voices on each side
Outcome per signal: probability >= 80% leans for, <= 20% leans against, otherwise unclear;
proportions lean for/against when the whole likely range is above/below 50%; voices lean
when one side has 2+ people and at least twice the other side.

Overall lean: all informative signals one way -> "leans for" / "leans against"; both ways ->
"mixed"; nothing informative -> "can't tell from this data". Strength: weak under 5
independent voices or a sample under 60; moderate under 15; else strong.
Priority (assumption mapping, after Bland & Osterwalder): important and weakly evidenced
-> test first; important and well evidenced -> build on it, keep checking; less important
-> park. Hypotheses formed from this data are always "test first" when important, since
this data suggested them and can't also be their test.

Usage:
  python hypotheses.py --work WORKDIR
Writes WORKDIR/hypotheses_result.json.
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_json, load_manifest, load_nuggets, save_json, study_mode, turn_index, unit_of  # noqa: E402

MEASURES = {"share_of_negative", "negative_rate", "mention_rate"}


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h) * 100, 1), round(min(1, c + h) * 100, 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    work = Path(args.work)
    hp = work / "hypotheses.json"
    if not hp.exists():
        raise SystemExit("No hypotheses.json yet (see this script's docstring for the format).")
    H = load_json(hp)
    H = H.get("hypotheses", H) if isinstance(H, dict) else H
    mode = study_mode(load_manifest(work))
    tindex = turn_index(work)
    by_id = {n["id"]: n for ns in load_nuggets(work).values() for n in ns}
    drv = load_json(work / "drivers.json") if (work / "drivers.json").exists() else {}
    boot = load_json(work / "drivers_boot.json") if (work / "drivers_boot.json").exists() else None
    reps = boot["replicates"] if boot else None
    small = bool(drv.get("overall", {}).get("small_sample"))
    errors, warnings = [], []

    def voices(ids):
        return len({unit_of(by_id[i], mode, tindex) for i in ids if i in by_id})

    def check_ids(ids, where):
        bad = [i for i in ids if i not in by_id]
        if bad:
            errors.append(f"{where}: unknown nugget ids {bad}")

    def prob(pred):
        if not reps:
            return None
        vals = [pred(i) for i in range(boot["n"])]
        vals = [v for v in vals if v is not None]
        return round(100 * sum(vals) / len(vals), 1) if vals else None

    def series(measure, a, where):
        if measure not in MEASURES:
            errors.append(f"{where}: measure must be one of {sorted(MEASURES)}")
            return None
        if reps and a not in reps[measure]:
            errors.append(f"{where}: aspect '{a}' not in drivers.py output")
            return None
        return reps[measure][a] if reps else None

    results = []
    for h in H:
        hid = h.get("id", "?")
        if h.get("origin") not in ("stated", "formed"):
            errors.append(f"{hid}: origin must be 'stated' (the user's belief) or 'formed' (suggested by this data)")
        if h.get("importance") not in ("high", "medium", "low"):
            errors.append(f"{hid}: importance must be high, medium or low (how much the strategy rests on it)")
        ns = h.get("next_step") or {}
        for k in ("method", "confirm", "disconfirm"):
            if not ns.get(k):
                errors.append(f"{hid}: next_step needs '{k}'")
        sigs, all_ids = [], []
        for sg in h.get("signals", []):
            sid, where = sg.get("id", "?"), f"{hid}/{sg.get('id', '?')}"
            t = sg.get("test") or {}
            out = {"id": sid, "text": sg.get("text"), "kind": t.get("type", "voices")}
            if t.get("type") == "top_driver":
                a = t.get("aspect", "")
                if reps and a not in reps["share_of_negative"]:
                    errors.append(f"{where}: aspect '{a}' not in drivers.py output")
                    continue
                p = prob(lambda i: reps["top"][i] == a) if reps else None
                out.update(prob=p, detail=f"{a} is the top driver")
            elif t.get("type") == "greater":
                sa = series(t.get("measure", "share_of_negative"), t.get("a"), where)
                sb = series(t.get("measure", "share_of_negative"), t.get("b"), where)
                p = prob(lambda i: None if (sa[i] != sa[i] or sb[i] != sb[i]) else sa[i] > sb[i]) if sa and sb else None
                out.update(prob=p, detail=f"{t.get('a')} > {t.get('b')} on {t.get('measure', 'share_of_negative')}")
            elif t.get("type") == "above":
                sa = series(t.get("measure", "share_of_negative"), t.get("aspect"), where)
                th = float(t.get("threshold", 0))
                p = prob(lambda i: None if sa[i] != sa[i] else sa[i] > th) if sa else None
                out.update(prob=p, detail=f"{t.get('aspect')} {t.get('measure', 'share_of_negative')} above {th:g}%")
            elif t.get("type") == "proportion":
                k_ids, n_ids = t.get("k_ids", []), t.get("n_ids", [])
                check_ids(k_ids + n_ids, where)
                if set(k_ids) - set(n_ids):
                    errors.append(f"{where}: every k_id must also be in n_ids")
                k, n = voices(k_ids), voices(n_ids)
                ci = wilson(k, n)
                out.update(k=k, n=n, ci=ci, lean="for" if n and ci[0] > 50 else "against" if n and ci[1] < 50 else "unclear")
                all_ids += n_ids
            elif t:
                errors.append(f"{where}: unknown test type '{t.get('type')}'")
                continue
            if out["kind"] in ("top_driver", "greater", "above"):
                p = out.get("prob")
                out["lean"] = "unclear" if p is None else "for" if p >= 80 else "against" if p <= 20 else "unclear"
                if p is None:
                    out["note"] = "too few people to compute a probability"
            if out["kind"] == "voices":
                fr, ag = sg.get("for", []), sg.get("against", [])
                check_ids(fr + ag, where)
                vf, va = voices(fr), voices(ag)
                out.update(voices_for=vf, voices_against=va, ids_for=fr, ids_against=ag,
                           lean="for" if vf >= 2 and vf >= 2 * va else "against" if va >= 2 and va >= 2 * vf else "unclear")
                all_ids += fr + ag
            sigs.append(out)
        leans = [s["lean"] for s in sigs if s["lean"] != "unclear"]
        overall = ("can't tell from this data" if not leans else "leans for" if set(leans) == {"for"}
                   else "leans against" if set(leans) == {"against"} else "mixed")
        nv = voices(all_ids)
        if any(s.get("prob") is not None and s["lean"] != "unclear" for s in sigs) and boot:
            nv = max(nv, boot["authors"])  # measured on the whole random sample
        strength = "weak" if (nv < 5 or small) else "moderate" if nv < 15 else "strong"
        imp = h.get("importance")
        evidenced = strength != "weak" and overall in ("leans for", "leans against")
        if imp == "low":
            priority = "park for now"
        elif h.get("origin") == "formed":
            priority = "test first"  # suggested by this data, so not yet independently tested
        else:
            priority = "build on it, keep checking" if evidenced else "test first"
        if h.get("origin") == "formed" and overall == "leans against":
            warnings.append(f"{hid}: a hypothesis formed from this data that the same data leans against; "
                            "reword it or drop it")
        results.append({"id": hid, "origin": h.get("origin"), "owner": h.get("owner"),
                        "statement": h.get("statement"), "importance": imp, "lean": overall,
                        "strength": strength, "voices": nv, "small_sample": small, "priority": priority,
                        "signals": sigs, "not_distinguishing": h.get("not_distinguishing", []),
                        "next_step": ns})

    stated = [r for r in results if r["origin"] == "stated"]
    if stated and all(r["lean"] == "leans for" for r in stated) and len(results) == len(stated):
        warnings.append("Only your own hypotheses, all leaning for. Add at least one rival or formed hypothesis "
                        "so discovery tests alternatives, not just your view.")
    if not any(r["origin"] == "formed" for r in results):
        warnings.append("No hypotheses formed from the data. Look for explanations you didn't bring in.")

    for e in errors:
        print(f"ERROR {e}")
    for w in warnings:
        print(f"WARN  {w}")
    if errors:
        print(f"\n{len(errors)} error(s); hypotheses_result.json not written.")
        sys.exit(1)
    save_json({"hypotheses": results, "warnings": warnings,
               "bootstrap": bool(reps), "boot_authors": boot["authors"] if boot else None},
              work / "hypotheses_result.json")
    for r in results:
        print(f"{r['id']} [{r['origin']}, {r['importance']} importance] {r['lean'].upper()}, {r['strength']} "
              f"({r['voices']} voices) -> {r['priority']}\n   {r['statement']}")
        for s in r["signals"]:
            if "prob" in s:
                val = f"{s['prob']}% of re-draws" if s.get("prob") is not None else s.get("note")
            elif "k" in s:
                val = f"{s['k']} of {s['n']} (likely {s['ci'][0]}-{s['ci'][1]}%)"
            else:
                val = f"{s['voices_for']} for / {s['voices_against']} against"
            print(f"   {s['id']} {s['lean']:<8} {val}  {s['text']}")


if __name__ == "__main__":
    main()
