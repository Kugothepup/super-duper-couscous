"""Old and new figures for each changed method, on the fixture study with dummy codes (D12 asks for them).

Run from the project root: python tests/method_log.py
It prints a Markdown table for DECISIONS.md. Every number in it comes from code: the skill's own
functions (tests/reference/drivers.py, language.py rules) for "old", crp for "new". The codes are
dummy values chosen by position (tests/conftest.py), so the figures show what each change does to
the arithmetic, not anything about real people.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "reference"))

from conftest import FIXTURE_SECRETS, FIXTURE_STUDY, write_labels  # noqa: E402
from crp import stats  # noqa: E402
from crp.analyse import measurement_records  # noqa: E402
from crp.labels import labelled  # noqa: E402
from crp.anonymise import anonymise  # noqa: E402
from crp.batch import make_batches, read_index  # noqa: E402
from crp.codebook import freeze, frozen  # noqa: E402
from crp.ingest import ingest  # noqa: E402
from crp.keyness import keyness  # noqa: E402
from crp.labels import lock  # noqa: E402
from crp.sample import candidates, sample  # noqa: E402
from crp.sensitivity import cap_weights, without_caps  # noqa: E402
from crp.signals import signals  # noqa: E402
from crp.verify import verify  # noqa: E402
import crp.verify  # noqa: E402

spec = importlib.util.spec_from_file_location("ref_drivers", HERE / "reference" / "drivers.py")
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)
SEED = 11


def build(tmp: Path) -> Path:
    d = tmp / "studies" / FIXTURE_STUDY.name
    shutil.copytree(FIXTURE_STUDY, d)
    (d / "posts.jsonl").unlink()
    crp.verify.ocr_text = lambda path: None  # the same with or without Tesseract
    ingest(d)
    verify(d)
    anonymise(d, FIXTURE_SECRETS)
    signals(d)
    sample(d, seed=SEED, thread_cap_pct=30)
    freeze(d)
    make_batches(d)
    write_labels(d)
    lock(d, "dummy")
    return d


def rng(r) -> str:
    return "none" if r is None else f"{r[0]}-{r[1]}"


def shown(sh: dict) -> str:
    if sh["status"] == "counts-only":
        return f"{sh['k']} of {sh['n']}, count only"
    return f"{sh['pct']}% ({rng(sh.get('range'))}, {sh.get('range_from')})"


def main() -> None:
    import json
    import datetime as dt
    from collections import Counter
    with tempfile.TemporaryDirectory() as tmp:
        d = build(Path(tmp))
        codebook, _ = frozen(d)
        records = measurement_records(d, codebook, labelled(d, read_index(d)))
        rows = []
        old = stats.Engine(records, 2000, SEED)
        new = stats.Engine(records, 5000, SEED)
        h_old, h_new = stats.headline(old), stats.headline(new)
        rows.append(("D12 re-draws", "% negative, range from resampling people",
                     f"{rng(h_old['negative']['range_people'])} (2000)", f"{rng(h_new['negative']['range_people'])} (5000)"))
        rows.append(("D3 threads", "% negative, range from resampling threads", "not run",
                     f"{rng(h_new['negative'].get('range_threads'))}; shown: {h_new['negative']['range_from']}"))
        k, n = h_new["people_net_negative"]["k"], h_new["people_net_negative"]["n"]
        rows.append(("D28 ranges", "people net negative", f"{h_new['people_net_negative']['pct']}% (Wilson {rng(ref.wilson(k, n))})",
                     shown(h_new["people_net_negative"])))
        a_old = {a["aspect"]: a for a in stats.aspects(new, rule="skill")["aspects"]}
        a_new = stats.aspects(new)
        for a in a_new["aspects"]:
            if not a["ranked"]:
                continue
            o = a_old[a["aspect"]]["top_driver"]
            t = a.get("top_driver")
            rows.append(("D12 top driver", f"{a['aspect']}: top driver, % of re-draws (people)",
                         f"{o['pct_people']}", f"{t['pct_people'] if t else 'n/a'}"))
            if t:
                rows.append(("D29 probability", f"{a['aspect']}: top driver, shown",
                             f"{o['pct_people']} (people only)", f"{t['pct']} ({t['source']}; people {t['pct_people']}, "
                                                                  f"threads {t.get('pct_threads')})"))
            nr = a["negative_rate"]
            rows.append(("D28 ranges", f"{a['aspect']}: negative rate",
                         f"{round(100 * nr['k'] / nr['n'], 1)}% (Wilson {rng(ref.wilson(nr['k'], nr['n']))})", shown(nr)))
        for a in stats.aspects(new, rule="skill")["aspects"]:
            if not a["ranked"] and a["top_driver"]["pct_people"]:
                rows.append(("D12 top driver", f"{a['aspect']} (under 3 mentions)", f"{a['top_driver']['pct_people']}",
                             "not eligible"))
        study = json.loads(json.dumps({"event": "2026-06-09"}))
        ev = stats.event(new, dt.date.fromisoformat(study["event"]))
        m = ev["measures"][0]
        b, af = m["before"], m["after"]
        rows.append(("D12 before/after", "% negative, after minus before",
                     f"{ref.compare('negative', b['k'], b['n'], af['k'], af['n'])['diff_ci']} (Newcombe), "
                     f"{ref.compare('negative', b['k'], b['n'], af['k'], af['n'])['verdict']}",
                     (f"{m['diff_pts']} ({rng(m.get('range'))}), {m['verdict']}" if m["diff_pts"] is not None
                      else f"no difference, {m['verdict']}: before is {shown(b)}, after is {shown(af)}")))
        src, _ = stats.by_source(new)
        for s in src:
            ng = s["negative"]
            rows.append(("D28 ranges", f"{s['source']}: % negative",
                         f"{round(100 * ng['k'] / ng['n'], 1)}% (Wilson {rng(ref.wilson(ng['k'], ng['n']))})", shown(ng)))
        texts = {}
        for line in (d / "posts.jsonl").read_text().splitlines():
            p = json.loads(line)
            texts[p["post_id"]] = p
        items = [(texts[r.post_id]["text"], r.person, r.overall) for r in records]
        ko, kn = keyness(items, rule="skill"), keyness(items)
        rows.append(("D6 keyness", "terms tested / kept",
                     f"{ko['basis']['tested']} / {len(ko['negative']) + len(ko['positive'])}",
                     f"{kn['basis']['tested']} / {len(kn['negative']) + len(kn['positive'])} (hidden: early signal)"))
        summary = json.loads((d / "samples" / "summary.json").read_text())
        from crp.io import read_jsonl
        from crp.schemas import Post
        posts = read_jsonl(d / "posts.jsonl", Post)
        eligible = Counter(p.person_code for p in candidates(posts, summary["measurement"]["frame"]["min_words"])[0])
        w = cap_weights(records, eligible, summary["measurement"]["frame"]["person_cap"], summary["measurement"]["threads"])
        rows.append(("D27 without caps", "% negative", f"{h_new['negative']['pct']}% (capped sample)",
                     f"{without_caps(records, w)['pct']}% (estimated, uncapped)"))
        from crp.hypotheses import proportion
        detail = {pid: v for (smp, pid), v in labelled(d, read_index(d)).items() if smp == "detail"}
        person = {p.post_id: p.person_code for p in posts}
        n_people = {person[pid] for pid, v in detail.items()}
        k_people = {person[pid] for pid, v in detail.items() if v.get("friction") is True}
        sh = proportion(k_people, n_people, len(detail), 5000, SEED)
        rows.append(("D28 ranges", "proportion signal: people with friction among coded detail posts",
                     f"{sh['k']} of {sh['n']}, {round(100 * sh['k'] / sh['n'], 1)}% (Wilson {rng(ref.wilson(sh['k'], sh['n']))})",
                     shown(sh)))
    print(f"Fixture study, seed {SEED}, thread cap 30%, dummy codes: {len(records)} comments from "
          f"{len({r.person for r in records})} people.\n")
    print("| Change | Figure | Old | New |")
    print("|---|---|---|---|")
    for r in rows:
        print("| " + " | ".join(r) + " |")


if __name__ == "__main__":
    main()
