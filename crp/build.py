"""crp build: the dashboard and the report, every number filled from results/results.json.

Numbers come only from results.json. Text comes from study.yaml and the AI's synthesis files. The design
(crp/templates) is ported from build_dashboard.py, dashboard.js and build_report.py, rendered here rather
than in the browser, so crp check-numbers can read every number shown; the page's script only handles
focus, copying and the colour theme. Outlook is gone (D1). Every section carries a coding-verification
banner from the agreement status of the variables it rests on (D5, D25).

The AI may write synthesis/summary.md: prose for the top of the report, with a placeholder such as
{{ headline.negative.pct }} for every number. It is rendered in a sandbox with results.json as its context.

By default the outputs leave out verbatim quotes, thread titles and person codes, and the build refuses
to write if any six-word run from a post's text appears in them (D33). They go to results/dashboard.html and
results/report.md. --with-quotes writes an internal version that quotes posts to results/internal/, which
is gitignored and carries a banner saying not to share it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from jinja2.exceptions import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from crp import manifest, thresholds, wording
from crp.agreement import section_status
from crp.analyse import HEARD_BAND, RESULTS
from crp.anonymise import POSTS
from crp.codebook import frozen
from crp.hypotheses import LEAN_AGAINST, LEAN_FOR
from crp.io import InputError, atomic_write_text, read_jsonl, read_yaml, sha256_file, validate
from crp.schemas import Post, Results, Study
from crp.synthesis import SYNTHESIS, check
from crp.text import shingles

OUT = Path("results")
INTERNAL = OUT / "internal"  # --with-quotes: never shared or committed
SUMMARY_PROSE = SYNTHESIS / "summary.md"
SHINGLE = 6  # words: a run this long from a post counts as a quote

LENSES = {  # _common.LENSES, without Outlook (D1) and with interviews counted apart (D14)
    "product": {"label": "Product", "aspect_word": "feature or aspect", "jtbd": True, "stance": False,
                "entity_title": "Alternatives in play",
                "entity_lede": "Products people mention, and the forces attached to those mentions.",
                "sections": ["verdict", "drivers", "direction", "themes", "heard", "pains", "successes", "jobs", "opportunities",
                             "entities", "interviews", "language", "hypotheses", "trust"],
                "names": {"drivers": "What drives sentiment", "themes": "Themes", "pains": "Pain points",
                          "successes": "Success moments", "opportunities": "Opportunities"}},
    "brand": {"label": "Brand", "aspect_word": "brand association", "jtbd": False, "stance": False,
              "entity_title": "Competitors and comparisons",
              "entity_lede": "Brands people compare with, and whether mentions pull towards or push away.",
              "sections": ["verdict", "drivers", "associations", "direction", "themes", "heard", "pains", "successes", "jobs",
                           "opportunities", "entities", "interviews", "language", "hypotheses", "trust"],
              "names": {"drivers": "What shapes perception", "themes": "Themes",
                        "pains": "Where the brand lets people down", "successes": "Moments of advocacy",
                        "opportunities": "Opportunities"}},
    "news": {"label": "News story", "aspect_word": "sub-topic, claim or actor", "jtbd": False, "stance": True,
             "entity_title": "Actors and organisations", "entity_lede": "Who people talk about in connection with the story.",
             "sections": ["verdict", "stance", "drivers", "direction", "themes", "heard", "framing", "questions", "entities",
                          "opportunities", "interviews", "language", "hypotheses", "trust"],
             "names": {"drivers": "What drives the reaction", "themes": "Narratives", "pains": "Concerns",
                       "successes": "Positive reactions", "opportunities": "Implications"}},
    "topic": {"label": "Topic or issue", "aspect_word": "sub-topic or argument", "jtbd": False, "stance": True,
              "entity_title": "Actors and organisations", "entity_lede": "Who people bring into the discussion.",
              "sections": ["verdict", "stance", "drivers", "direction", "themes", "heard", "framing", "questions", "pains",
                           "entities", "opportunities", "interviews", "language", "hypotheses", "trust"],
              "names": {"drivers": "What drives opinion", "themes": "Narratives", "pains": "Concerns",
                        "successes": "Positive reactions", "opportunities": "Implications"}},
}
DEFAULT_NAMES = {"verdict": "Summary", "stance": "Where people stand", "drivers": "What drives sentiment",
                 "associations": "Brand associations", "direction": "Direction of travel", "themes": "Themes",
                 "pains": "Pain points", "successes": "Success moments", "jobs": "Jobs to be done",
                 "opportunities": "Opportunities", "framing": "How the story is framed",
                 "questions": "Questions people ask", "interviews": "Interviews", "language": "Language used",
                 "trust": "How much to trust this", "hypotheses": "Hypotheses for discovery",
                 "heard": "Have we heard enough?"}
# the coded variables each section rests on, for its verification banner (D25); "@aspects" is the per-aspect one
SECTION_VARIABLES = {"verdict": ["overall"], "stance": ["stance"], "drivers": ["overall", "@aspects"],
                     "associations": ["@aspects"], "direction": ["overall"], "themes": ["evidence_type"],
                     "pains": ["friction", "severity", "aspect"], "successes": ["success", "aspect"],
                     "jobs": ["jtbd_force"], "framing": ["frame"], "questions": [],
                     "opportunities": ["friction", "severity", "aspect"], "entities": ["jtbd_force", "sentiment"],
                     "interviews": ["jtbd_force", "evidence_type", "friction", "severity", "aspect"],
                     "language": ["overall"], "hypotheses": ["overall", "@aspects"], "heard": []}
FORCE_LABEL = {"push": "Push (pain with the current way)", "pull": "Pull (attraction of a new way)",
               "anxiety": "Anxiety (worry about switching)", "habit": "Habit (comfort of the status quo)"}


def banner(r: dict, codebook, section: str) -> dict | None:
    wanted = SECTION_VARIABLES.get(section)
    if wanted is None:
        return None
    per_aspect = [v.name for v in codebook.variables if v.kind == "per_aspect" and v.applies_to == "measurement"]
    names = [x for w in wanted for x in (per_aspect if w == "@aspects" else [w])]
    names = [n for n in names if any(v.name == n for v in codebook.variables)]
    if not names:
        return {"status": "none", "text": "This rests on the AI's reading (observations and tags), which the "
                                          "agreement check doesn't cover."}
    report = {"metrics": {k: {"status": v} for k, v in r["agreement_status"].items()}} if r["agreement_status"] else None
    status = section_status(report, names)
    alphas = ", ".join(f"{k} {a}" for k, a in r["alpha"].items() if k.split(" (")[0] in names and a is not None)
    if report is None:
        text = "Coding unverified: the agreement check hasn't been run, so don't rely on these results yet."
    elif status == "verified":
        text = f"Coding verified: agreement {alphas} ({thresholds.ALPHA_VERIFIED} or above)."
    elif status == "tentative":
        text = (f"Coding tentative: agreement {alphas}, between {thresholds.ALPHA_TENTATIVE} and "
                f"{thresholds.ALPHA_VERIFIED}. Treat these results with care.")
    else:
        text = (f"Coding unverified: agreement {alphas or 'not checked for every variable here'}"
                f"{f', below {thresholds.ALPHA_TENTATIVE} or not checked for every variable' if alphas else ''}. "
                "Don't rely on these results yet.")
    return {"status": status, "text": text}


def through_steps(values: list[float]) -> list[float]:
    """A step line redrawn through the middle of each step, so a range of whole numbers draws smoothly. It
    stays within half a step of the original, and keeps the first and last points."""
    n = len(values)
    knots = [(0, values[0])] + [(k - 0.5, (values[k - 1] + values[k]) / 2) for k in range(1, n)
                                if values[k] != values[k - 1]] + [(n - 1, values[-1])]
    out, j = [], 0
    for k in range(n):
        while j + 1 < len(knots) - 1 and knots[j + 1][0] <= k:
            j += 1
        (x0, y0), (x1, y1) = knots[j], knots[j + 1]
        out.append(y0 if x1 == x0 else y0 + (y1 - y0) * (k - x0) / (x1 - x0))
    return out


def curve(he: dict | None, width: int = 560, height: int = 240) -> dict | None:
    """SVG coordinates for the heard-enough curve: the average order as a line, the range as a band.
    Drawing only: every number the page prints comes from results.json."""
    if not he:
        return None
    left, right, top, bottom = 44, width - 20, 20, height - 40
    n, t = he["posts"], he["topics"]

    def x(k: int) -> float:
        return round(left + k / (n - 1) * (right - left), 1)

    def y(v: float) -> float:
        return round(bottom - v / t * (bottom - top), 1)

    line = "M" + " L".join(f"{x(k)},{y(v)}" for k, v in enumerate(he["mean"]))
    high = [max(v, m) for v, m in zip(through_steps(he["high"]), he["mean"])]
    low = [min(v, m) for v, m in zip(through_steps(he["low"]), he["mean"])]
    band = "M" + " L".join(f"{x(k)},{y(v)}" for k, v in enumerate(high)) + " L" + \
        " L".join(f"{x(k)},{y(v)}" for k, v in reversed(list(enumerate(low)))) + " Z"
    return {"line": line, "band": band, "left": left, "right": right, "top": top, "bottom": bottom,
            "width": width, "height": height}


def context(study_dir: Path, shareable: bool) -> dict:
    study_dir = Path(study_dir)
    path = study_dir / RESULTS
    if not path.exists():
        raise InputError("No results/results.json. Run crp analyse first.")
    results = validate(Results, json.loads(path.read_text(encoding="utf-8")), str(path))
    r = results.model_dump(mode="json")
    study = read_yaml(study_dir / "study.yaml", Study)
    codebook, _ = frozen(study_dir)
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    checked = check(study_dir, codebook, list(posts.values())) if (study_dir / SYNTHESIS).is_dir() else None
    if checked and not checked["ok"]:
        raise InputError("The synthesis has errors. Run crp validate, fix them, then analyse and build again.")
    nuggets = checked["nuggets"] if checked else {}
    files = checked["files"] if checked else {k: [] for k in ("insights", "jobs", "opportunities", "hypotheses")}

    def ev(pid: str) -> dict:
        n = nuggets.get(pid)
        post = posts[pid]
        out = {"id": pid, "obs": n.obs.observation if n else "", "aspect": n.aspect if n and n.aspect != "other" else None,
               "force": n.codes.get("jtbd_force") if n else None, "ev": (n.codes.get("evidence_type") or "") if n else "",
               "sev": n.codes.get("severity") if n else None, "strong": bool(n and n.strong),
               "score": post.score if post.source_type == "forum" else None}
        out |= {"quote": None, "who": None} if shareable else \
            {"quote": n.obs.quote if n else post.text[:160], "who": post.person_code}
        return out

    lens = LENSES[study.type]
    sources = [s["source"] for s in (r.get("collection") or {}).get("sources", [])]
    present = {"verdict": True, "stance": bool(r["stance"]) or lens["stance"], "drivers": True,
               "associations": study.type == "brand", "direction": True, "themes": True, "pains": True,
               "successes": True, "jobs": True, "framing": True, "questions": True, "opportunities": True,
               "entities": bool((r.get("synthesis") or {}).get("products")), "interviews": bool(r["interviews"]),
               "language": bool(r["language"]), "hypotheses": bool(r["hypotheses"]), "trust": True,
               "heard": bool(r.get("heard_enough"))}
    sections = [(s, lens["names"].get(s) or (lens["entity_title"] if s == "entities" else DEFAULT_NAMES[s]))
                for s in lens["sections"] if present.get(s)]
    prose = None
    if (study_dir / SUMMARY_PROSE).exists():
        env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        try:
            prose = env.from_string((study_dir / SUMMARY_PROSE).read_text(encoding="utf-8")).render(**r)
        except TemplateError as err:
            raise InputError(f"{SUMMARY_PROSE}: {err}") from None
    titles = {p.thread_id: p.thread_title for p in posts.values() if p.thread_title}
    friction = sorted((n for n in nuggets.values() if n.codes.get("friction") is True),
                      key=lambda n: (-(n.codes.get("severity") or 0), -(n.post.score or 0)))
    return {"r": r, "study": study, "lens": lens, "sections": sections, "shareable": shareable, "ev": ev,
            "curve": curve(r.get("heard_enough")), "heard_band": HEARD_BAND,
            "banner": lambda s: banner(r, codebook, s), "verdict": wording.verdict(r, study),
            "safe": wording.safe_wording(r, study, sources), "population_note": wording.population_note(study),
            "sources": sources, "prose": prose, "force_label": FORCE_LABEL, "friction": [n.post.post_id for n in friction[:10]],
            "insights": {i.id: i for i in files["insights"]}, "jobs": {j.id: j for j in files["jobs"]},
            "opportunities": {o.id: o for o in files["opportunities"]},
            "hypotheses": {h.id: h for h in files["hypotheses"]}, "titles": {} if shareable else titles,
            "thresholds": thresholds, "thresholds_lean": {"for": int(LEAN_FOR), "against": int(LEAN_AGAINST)},
            "codebook": codebook, "posts": posts}


def environment(markdown: bool) -> Environment:
    env = Environment(loader=PackageLoader("crp", "templates"), undefined=StrictUndefined, trim_blocks=not markdown,
                      lstrip_blocks=True, autoescape=False if markdown else select_autoescape(["html"]))
    env.filters["people"] = lambda n: f"{n} {'person' if n == 1 else 'people'}"
    env.filters["label"] = lambda s: str(s).replace("_", " ")
    return env


def quoted_runs(text: str, posts: list[Post]) -> list[str]:
    """Six-word runs of any post's text that appear in `text` (after the skill's loose normalisation)."""
    found = shingles(text, SHINGLE)
    return sorted({s for p in posts if len(p.text.split()) >= SHINGLE for s in shingles(p.text, SHINGLE) & found})


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    return re.sub(r"<[^>]+>", " ", html)


def build(study_dir: Path, with_quotes: bool = False) -> dict:
    study_dir = Path(study_dir)
    shareable = not with_quotes
    ctx = context(study_dir, shareable)
    dashboard = environment(False).get_template("dashboard.html.j2").render(**ctx)
    report = re.sub(r"\n{3,}", "\n\n", environment(True).get_template("report.md.j2").render(**ctx)).strip() + "\n"
    out_dir = study_dir / (INTERNAL if with_quotes else OUT)
    if shareable:
        posts = read_jsonl(study_dir / POSTS, Post)
        leaks = quoted_runs(visible_text(dashboard) + "\n" + report, posts)
        codes = sorted(set(re.findall(r"\bP-[0-9a-f]{8}\b", dashboard + report)))
        if leaks or codes:
            raise InputError("The build would still carry "
                             + (f"{len(leaks)} run(s) of six words quoted from posts (paraphrase the observations "
                                f"that repeat them), e.g. \"{leaks[0]}\"" if leaks else "")
                             + ("; " if leaks and codes else "") + (f"person codes, e.g. {codes[0]}" if codes else "")
                             + ". Nothing was written. (crp build --with-quotes makes an internal version that may quote.)")
    inputs = [study_dir / RESULTS, study_dir / "study.yaml"] + sorted(p for p in (study_dir / SYNTHESIS).glob("*")
                                                                       if p.is_file())
    with manifest.stage(study_dir, "build --with-quotes" if with_quotes else "build", inputs=inputs) as record:
        atomic_write_text(out_dir / "dashboard.html", dashboard)
        atomic_write_text(out_dir / "report.md", report)
        record["outputs"] = [str((out_dir / f).relative_to(study_dir)) for f in ("dashboard.html", "report.md")]
    return {"dashboard": out_dir / "dashboard.html", "report": out_dir / "report.md", "with_quotes": with_quotes,
            "results_sha256": sha256_file(study_dir / RESULTS)}
