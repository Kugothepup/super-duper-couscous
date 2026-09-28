"""The AI's synthesis, checked and counted. Ported from validate.py (the checks) and build_dashboard.py
(the counts).

The AI writes, in synthesis/:
  observations.jsonl  one per coded detail post: observation, verbatim quote, tags (D31: one per post)
  insights.json       {"insights": [...]}       statements citing post ids, with counter-evidence
  jobs.json           {"jobs": [...]}           job stories citing post ids
  opportunities.json  {"opportunities": [...]}  how-might-we statements citing post ids
  hypotheses.json     {"hypotheses": [...]}     scored in crp/hypotheses.py
A nugget is a detail post with an observation. Its categories (force, evidence grade, friction and
severity, aspect, sentiment, success, frame) are the blind coder's (D10, D31). Code counts everything:
people (voices), strong evidence, severity, forces, reach. Interview participants are counted apart from
forum people (D14). Quotes must be verbatim: tidied or invented quotes are errors (D31, as D20).
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from dataclasses import dataclass
from pathlib import Path

from crp.batch import read_index
from crp.io import InputError, read_jsonl, validate
from crp.labels import UNSEALED, labelled
from crp.sample import load_detail
from crp.schemas import Codebook, Hypothesis, Insight, Job, Observation, Opportunity, Post
from crp.text import loose
from crp.verify import check_quote

SYNTHESIS = Path("synthesis")
OBSERVATIONS = SYNTHESIS / "observations.jsonl"
FILES = {"insights": (SYNTHESIS / "insights.json", Insight), "jobs": (SYNTHESIS / "jobs.json", Job),
         "opportunities": (SYNTHESIS / "opportunities.json", Opportunity),
         "hypotheses": (SYNTHESIS / "hypotheses.json", Hypothesis)}
STRONG = {"observed", "specific_incident"}
FORCES = ("push", "pull", "anxiety", "habit")
ENTITY = ("product:", "entity:", "brand:")
JOB_STORY = re.compile(r"(?i)^when\b.+\bi want\b.+\bso\b")
NO_ASPECT = {None, "", "not_applicable", "none", "other"}
LOOK = {"hesitation_cluster", "constraint_language", "implicit_request", "workaround_language", "switching_language",
        "high_engagement"}  # build_report.py: flags worth a look when no observation covers the post


@dataclass
class Nugget:
    post: Post
    obs: Observation
    codes: dict  # the blind coder's detail codes; {} until coded

    @property
    def person(self) -> str:
        return self.post.person_code

    @property
    def aspect(self) -> str:
        a = self.codes.get("aspect")
        return "other" if a in NO_ASPECT else str(a).lower()

    @property
    def strong(self) -> bool:
        return self.codes.get("evidence_type") in STRONG


def people(ns: list[Nugget]) -> dict:
    return {"voices": len({n.person for n in ns}),
            "forum_people": len({n.person for n in ns if n.post.source_type == "forum"}),
            "interview_participants": len({n.person for n in ns if n.post.source_type == "interview"})}


def read_list(path: Path, key: str, model) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise InputError(f"{path}: not valid JSON ({err.msg})") from None
    items = data.get(key, data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise InputError(f"{path}: expected {{\"{key}\": [...]}}")
    return [validate(model, item, f"{path} {item.get('id', '#' + str(i + 1)) if isinstance(item, dict) else i + 1}")
            for i, item in enumerate(items)]


def load(study_dir: Path) -> dict:
    """Every synthesis file that exists, validated against its schema."""
    study_dir = Path(study_dir)
    out: dict = {"observations": read_jsonl(study_dir / OBSERVATIONS, Observation)
                 if (study_dir / OBSERVATIONS).exists() else []}
    for key, (path, model) in FILES.items():
        out[key] = read_list(study_dir / path, key, model) if (study_dir / path).exists() else []
    return out


def nuggets_of(study_dir: Path, observations: list[Observation]) -> tuple[dict[str, Nugget], list[str], list[str]]:
    """Observations joined to their posts and blind codes, with errors and warnings about them."""
    detail = {item.post_id: post for item, post in load_detail(study_dir)}
    coded = {pid: v for (sample, pid), v in labelled(study_dir, read_index(study_dir)).items() if sample == "detail"}
    out: dict[str, Nugget] = {}
    errors, warnings = [], []
    for o in observations:
        where = f"observation {o.post_id}"
        post = detail.get(o.post_id)
        if post is None:
            errors.append(f"{where}: not in the detail selection, so it has no blind codes")
            continue
        if o.post_id in out:
            errors.append(f"{where}: a post gets one observation (D31)")
            continue
        check = check_quote(o.quote, post.text)
        if check["status"] in ("tidied", "failed"):
            detail_text = f": {check['diff']}" if check.get("diff") else ""
            errors.append(f"{where}: the quote isn't verbatim ({check['status']}){detail_text}")
        if len(o.quote.split()) < 3:
            warnings.append(f"{where}: very short quote")
        if loose(o.observation) == loose(o.quote):
            warnings.append(f"{where}: the observation just repeats the quote; interpret it")
        codes = coded.get(o.post_id, {})
        if not codes:
            warnings.append(f"{where}: not coded yet")
        elif codes.get("evidence_type") == "observed" and post.source_type == "forum":
            warnings.append(f"{where}: coded 'observed', which is for behaviour seen in a session; "
                            "forum posts are usually specific_incident, habitual or opinion")
        out[o.post_id] = Nugget(post=post, obs=o, codes=codes)
    return out, errors, warnings


def check(study_dir: Path, codebook: Codebook, posts: list[Post]) -> dict:
    """Every check validate.py made on the synthesis, plus crp's (D31). Hypothesis signals that need the
    sample (aspects mentioned, probabilities) are checked again in crp analyse."""
    study_dir = Path(study_dir)
    files = load(study_dir)
    nuggets, errors, warnings = nuggets_of(study_dir, files["observations"])
    transcripts = len({p.thread_id for p in posts if p.source_type == "interview"})

    def cite(ids: list[str], where: str) -> list[Nugget]:
        bad = [i for i in ids if i not in nuggets]
        if bad:
            errors.append(f"{where}: cites posts with no observation: {bad}")
        return [nuggets[i] for i in ids if i in nuggets]

    seen: set[str] = set()
    for key in FILES:
        for item in files[key]:
            if item.id in seen:
                errors.append(f"{key}: id {item.id} is used twice")
            seen.add(item.id)
    for ins in files["insights"]:
        where = f"insight {ins.id}"
        sup = cite(ins.post_ids, where)
        cite(ins.counter_post_ids, where)
        pp = people(sup)
        strong = sum(n.strong for n in sup)
        if pp["voices"] == 1:
            warnings.append(f"{where}: supported by one person; keep confidence low or frame it as a lead")
        high_forum = pp["forum_people"] >= 5
        high_interview = transcripts and len({n.post.thread_id for n in sup if n.post.source_type == "interview"}) \
            >= max(3, transcripts // 3)
        if ins.confidence == "high" and (not (high_forum or high_interview) or strong == 0):
            warnings.append(f"{where}: 'high' but {pp['forum_people']} forum people (want 5+) or too few interviews, "
                            f"and {strong} observed or specific-incident post(s)")
        if not ins.counter_post_ids:
            warnings.append(f"{where}: no counter-evidence listed (fine if none exists; say so)")
    insight_ids = {i.id for i in files["insights"]}
    for job in files["jobs"]:
        ns = cite(job.post_ids, f"job {job.id}")
        if not JOB_STORY.match(job.job):
            warnings.append(f"job {job.id}: write it as 'When <situation>, I want to <motivation>, so I can <outcome>'")
        if len({n.codes.get("jtbd_force") for n in ns} - {None, "none"}) < 2:
            warnings.append(f"job {job.id}: evidence covers fewer than two forces; the forces balance will be thin")
    for opp in files["opportunities"]:
        cite(opp.post_ids, f"opportunity {opp.id}")
        bad = [i for i in opp.insight_ids if i not in insight_ids]
        if bad:
            errors.append(f"opportunity {opp.id}: unknown insight ids {bad}")
        if opp.aspect and opp.aspect not in codebook.aspects:
            warnings.append(f"opportunity {opp.id}: aspect '{opp.aspect}' isn't in the codebook")
    unsealed = (study_dir / UNSEALED).exists()
    for h in files["hypotheses"]:
        where = f"hypothesis {h.id}"
        if h.origin == "stated" and not unsealed:
            errors.append(f"{where}: stated hypotheses come from Steeve's prior, which is still sealed. "
                          "Run crp unseal after the labels are locked (D31).")
        cite(h.not_distinguishing, where)
        for sg in h.signals:
            sw = f"{where}/{sg.id}"
            cite(sg.for_ids + sg.against_ids, sw)
            t = sg.test
            if t is None:
                continue
            if t.type == "proportion":
                cite(t.k_ids + t.n_ids, sw)
                if set(t.k_ids) - set(t.n_ids):
                    errors.append(f"{sw}: every k_id must also be in n_ids")
            for a in [getattr(t, f) for f in ("aspect", "a", "b") if hasattr(t, f)]:
                if a not in codebook.aspects:
                    errors.append(f"{sw}: aspect '{a}' isn't in the codebook")
    hyps = files["hypotheses"]
    if hyps and not any(h.origin == "formed" for h in hyps):
        warnings.append("No hypotheses formed from the data. Look for explanations you didn't bring in.")
    counts = {k: len(v) for k, v in files.items()}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "counts": counts, "files": files,
            "nuggets": nuggets}


# ---- the counts (build_dashboard.py) -----------------------------------------

def group(ns: list[Nugget], key) -> list[dict]:
    g: dict[str, list[Nugget]] = defaultdict(list)
    for n in ns:
        g[key(n)].append(n)
    out = []
    for name, items in g.items():
        sev = [n.codes.get("severity") or 0 for n in items]
        out.append({"aspect": name, "n": len(items), **people(items), "max_sev": max(sev) if sev else 0,
                    "mean_sev": round(sum(sev) / len(sev), 1) if sev else 0.0, "strong": sum(n.strong for n in items),
                    "post_ids": [n.post.post_id for n in items]})
    return out


def aspects_of(ns: list[Nugget]) -> list[str]:
    return sorted({n.aspect for n in ns} - {"other"})


def diverse(ns: list[Nugget], k: int = 3) -> list[Nugget]:
    """build_report.py's pick: up to k, distinct people first, preferring strong evidence, severity, then score."""
    ranked = sorted(ns, key=lambda n: (not n.strong, -(n.codes.get("severity") or 0), -(n.post.score or 0)))
    out, seen = [], set()
    for n in ranked:
        if n.person not in seen:
            out.append(n)
            seen.add(n.person)
        if len(out) == k:
            return out
    for n in ranked:
        if n not in out:
            out.append(n)
        if len(out) == k:
            break
    return out


def summarise(checked: dict, negative_rate: dict[str, float | None], codebook: Codebook, top_drivers: list[str] = (),
              detail_posts: list[Post] = (), flags: dict[str, list[str]] | None = None) -> dict:
    """Reach, counter-evidence, severity, forces and ranks for results.json. Numbers and ids only."""
    files, nuggets = checked["files"], checked["nuggets"]
    ns = list(nuggets.values())
    flags = flags or {}

    def get(ids: list[str]) -> list[Nugget]:
        return [nuggets[i] for i in ids if i in nuggets]

    insights = []
    for i in files["insights"]:
        sup, con = get(i.post_ids), get(i.counter_post_ids)
        insights.append({"id": i.id, "confidence": i.confidence, "n": len(sup), **people(sup),
                         "strong": sum(n.strong for n in sup), "counter_n": len(con),
                         "counter_voices": len({n.person for n in con}), "aspects": aspects_of(sup + con),
                         "post_ids": i.post_ids, "counter_post_ids": i.counter_post_ids})
    pains = sorted(group([n for n in ns if n.codes.get("friction") is True], lambda n: n.aspect),
                   key=lambda g: (-(g["voices"] * g["max_sev"]), -g["n"]))
    successes = sorted(group([n for n in ns if n.codes.get("success") is True], lambda n: n.aspect),
                       key=lambda g: (-g["voices"], -g["n"]))
    jobs = []
    for j in files["jobs"]:
        items = get(j.post_ids)
        f = Counter(n.codes.get("jtbd_force") for n in items)
        jobs.append({"id": j.id, "forces": {k: f.get(k, 0) for k in FORCES}, "n": len(items), **people(items),
                     "aspects": aspects_of(items), "post_ids": j.post_ids})
    opportunities = []
    for o in files["opportunities"]:
        items = get(o.post_ids)
        sev = [n.codes.get("severity") or 0 for n in items if n.codes.get("friction") is True]
        mean_sev = round(sum(sev) / len(sev), 1) if sev else 0.0
        voices = len({n.person for n in items})
        asp = (o.aspect or "").lower()
        opportunities.append({"id": o.id, "kind": o.kind, "aspect": asp or None, "n": len(items), **people(items),
                              "mean_sev": mean_sev, "negative_rate_pct": negative_rate.get(asp),
                              "rank_score": round(voices * (1 + mean_sev), 2), "insight_ids": o.insight_ids,
                              "post_ids": o.post_ids})
    opportunities.sort(key=lambda o: -o["rank_score"])
    products: dict[str, dict] = {}
    for n in ns:
        for tag in n.obs.tags:
            if not tag.startswith(ENTITY):
                continue
            p = products.setdefault(tag.split(":", 1)[1], {"n": 0, "forces": Counter(), "sent": [], "people": set()})
            p["n"] += 1
            p["forces"][n.codes.get("jtbd_force")] += 1
            if isinstance(n.codes.get("sentiment"), int) and not isinstance(n.codes.get("sentiment"), bool):
                p["sent"].append(n.codes["sentiment"])
            p["people"].add(n.person)
    product_rows = sorted(({"name": k, **{f: v["forces"].get(f, 0) for f in FORCES}, "n": v["n"],
                            "voices": len(v["people"]),
                            "mean_sentiment": round(sum(v["sent"]) / len(v["sent"]), 2) if v["sent"] else None}
                           for k, v in products.items()), key=lambda x: -x["voices"])
    frames = []
    try:
        frame_values = [v for v in codebook.variable("frame").values if v != "none"]
    except KeyError:
        frame_values = []
    for f in frame_values:
        items = [n for n in ns if n.codes.get("frame") == f]
        if items:
            frames.append({"frame": f, "n": len(items), **people(items), "aspects": aspects_of(items),
                           "post_ids": [n.post.post_id for n in items]})
    questions = sorted(group([n for n in ns if "question" in n.obs.tags], lambda n: n.aspect), key=lambda g: -g["n"])
    forces = {f: {"n": len(fn), **people(fn), "post_ids": [n.post.post_id for n in fn]}
              for f in FORCES for fn in [[n for n in ns if n.codes.get("jtbd_force") == f]]}
    pairs = Counter(pair for n in ns for pair in combinations(sorted({t for t in n.obs.tags if not t.startswith(ENTITY)}), 2))
    tag_pairs = [{"a": a, "b": b, "n": c} for (a, b), c in pairs.most_common(15) if c >= 2]
    driver_evidence, unexplained = {}, []
    for a in top_drivers:
        rel = [n for n in ns if n.aspect == a or a in n.obs.tags]
        if rel:
            driver_evidence[a] = [n.post.post_id for n in diverse(rel)]
        else:
            unexplained.append(a)
    observed = set(nuggets)
    flagged = sorted((p for p in detail_posts if p.post_id not in observed and LOOK & set(flags.get(p.post_id, ()))),
                     key=lambda p: -(p.score or 0))
    return {"observations": len(ns), "forces": forces, "tag_pairs": tag_pairs, "driver_evidence": driver_evidence,
            "unexplained_drivers": unexplained, "unexamined": [p.post_id for p in flagged[:12]], "evidence_mix": dict(sorted(Counter(str(n.codes.get("evidence_type"))
                                                                         for n in ns).items())),
            "insights": insights, "pains": pains, "successes": successes, "jobs": jobs,
            "opportunities": opportunities, "products": product_rows, "frames": frames, "questions": questions}
