"""crp check-numbers: every number shown in the report and the dashboard must come from results.json.

Scans results/report.md and results/dashboard.html (its visible text and aria-labels), and the
shareable build if there is one. A number is traceable if it matches, ignoring sign:
  - a number in results/results.json, as a value or inside one of its strings;
  - a number in study.yaml's text (the research questions, say);
  - one of the method's stated constants: the thresholds, the codebook's scale values;
  - inside an evidence line that names a post (T01-p02), a number in that post's own text or its score,
    because quotes and observations may repeat what the post said; on a line naming a thread (T03), a
    number in that thread's title.
Dates, year-weeks, months and years (1990 to 2100) are allowed. Ids such as T01-p02, I01, H1 or C07 aren't
numbers. Anything else was typed, not counted, and fails with its file and line.

Matching values can't tell a right number from one that merely equals something in results.json, so the
AI's own writing is checked at its source too, more strictly: synthesis/summary.md outside its placeholders,
and every statement, recommendation, job, opportunity and hypothesis text, may hold no digits at all (write
non-data quantities in words), and an observation may hold only numbers from the post it cites.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import yaml

from crp import hypotheses, keyness, stats, thresholds, wording
from crp.anonymise import POSTS
from crp.analyse import RESULTS
from crp.build import OUT, SHAREABLE
from crp.codebook import CODEBOOK
from crp.io import InputError, read_jsonl
from crp.schemas import Post

DATES = re.compile(r"\b\d{4}-(?:W\d{2}|\d{2}(?:-\d{2})?)\b")
PERSON = re.compile(r"\bP-[0-9a-f]{8}\b")  # person codes are ids, even when all eight characters are digits
NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\w])")
POST_ID = re.compile(r"\b[A-Z]\d{2}-[pt]\d{2,}\b")
THREAD_ID = re.compile(r"\b[TI]\d{2}\b(?!-)")
SILHOUETTE_WORDS = (0.1, 0.3)  # the trust section's loose / moderate / clear
YEARS = (1990, 2100)


def numbers_in(text: str) -> list[tuple[float, str]]:
    text = DATES.sub(" ", PERSON.sub(" ", text.replace("−", "-")))
    return [(float(m.group(0).replace(",", "")), m.group(0)) for m in NUMBER.finditer(text)]


def walk(value, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.add(abs(float(value)))
    elif isinstance(value, str):
        out.update(v for v, _ in numbers_in(value))
    elif isinstance(value, dict):
        for k, v in value.items():
            walk(k, out)
            walk(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            walk(v, out)


def constants(study_dir: Path) -> set[float]:
    """The method's stated constants, which templates may print as words around the data."""
    out = {thresholds.MIN_PEOPLE_FOR_RANGES, thresholds.MIN_ITEMS_FOR_FULL, thresholds.ALPHA_VERIFIED,
           thresholds.ALPHA_TENTATIVE, thresholds.THREAD_CAP_PCT, thresholds.PERSON_CAP, stats.MIN_MENTIONS,
           stats.MIN_PER_SIDE, wording.GAP, hypotheses.LEAN_FOR, hypotheses.LEAN_AGAINST, keyness.Q, *SILHOUETTE_WORDS}
    codebook = yaml.safe_load((study_dir / CODEBOOK).read_text(encoding="utf-8"))
    for v in codebook.get("variables", []):
        walk([x for x in v.get("values", []) if not isinstance(x, str)], out)
    return {abs(float(x)) for x in out}


def traceable(study_dir: Path) -> set[float]:
    out: set[float] = set()
    walk(json.loads((study_dir / RESULTS).read_text(encoding="utf-8")), out)
    walk(yaml.safe_load((study_dir / "study.yaml").read_text(encoding="utf-8")), out)
    return out | constants(study_dir)


def post_numbers(posts: dict[str, Post], text: str) -> set[float]:
    out: set[float] = set()
    titles = {p.thread_id: p.thread_title for p in posts.values() if p.thread_title}
    for tid in THREAD_ID.findall(text):
        out.update(v for v, _ in numbers_in(titles.get(tid) or ""))
    for pid in POST_ID.findall(text):
        p = posts.get(pid)
        if p is not None:
            out.update(v for v, _ in numbers_in(p.text))
            if p.score is not None:
                out.add(abs(float(p.score)))
    return out


def untraced(text: str, allowed: set[float]) -> list[str]:
    return [tok for v, tok in numbers_in(text) if v not in allowed and not (v.is_integer() and YEARS[0] <= v <= YEARS[1])]


class _Visible(HTMLParser):
    """Visible text and aria-labels of a page, each chunk with the post it sits under (data-post)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[tuple[str, str | None, int]] = []
        self.stack: list[tuple[str, str | None]] = []
        self.skip = 0

    def post(self) -> str | None:
        return next((p for _, p in reversed(self.stack) if p), None)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        if tag not in ("meta", "link", "br", "input", "img", "hr", "circle", "line", "rect", "polygon", "polyline"):
            self.stack.append((tag, a.get("data-post")))
        if a.get("aria-label"):
            self.chunks.append((a["aria-label"], a.get("data-post") or self.post(), self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        a = dict(attrs)
        if a.get("aria-label"):
            self.chunks.append((a["aria-label"], self.post(), self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.chunks.append((data, self.post(), self.getpos()[0]))


def check_markdown(path: Path, allowed: set[float], posts: dict[str, Post]) -> list[str]:
    problems = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        extra = post_numbers(posts, line)
        for tok in untraced(line, allowed | extra):
            problems.append(f"{path.name} line {n}: {tok}  <- {line.strip()[:100]}")
    return problems


def check_html(path: Path, allowed: set[float], posts: dict[str, Post]) -> list[str]:
    parser = _Visible()
    parser.feed(path.read_text(encoding="utf-8"))
    problems = []
    for text, post, line in parser.chunks:
        extra = post_numbers(posts, post) if post else set()
        for tok in untraced(text, allowed | extra):
            problems.append(f"{path.name} line {line}: {tok}  <- {' '.join(text.split())[:100]}")
    return problems


PLACEHOLDER = re.compile(r"(?s)\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}")


def typed(text: str, allowed: set[float] = frozenset()) -> list[str]:
    return [tok for v, tok in numbers_in(text) if v not in allowed and not (v.is_integer() and YEARS[0] <= v <= YEARS[1])]


def check_prose(study_dir: Path, posts: dict[str, Post]) -> list[str]:
    """Digits typed into the AI's own writing, at the source."""
    from crp.synthesis import SYNTHESIS, load
    problems = []
    summary = study_dir / SYNTHESIS / "summary.md"
    if summary.exists():
        for n, line in enumerate(PLACEHOLDER.sub(" ", summary.read_text(encoding="utf-8")).splitlines(), 1):
            problems += [f"synthesis/summary.md line {n}: {tok}  <- use a placeholder" for tok in typed(line)]
    if not (study_dir / SYNTHESIS).is_dir():
        return problems
    files = load(study_dir)
    texts: list[tuple[str, str]] = []
    for i in files["insights"]:
        texts += [(f"insight {i.id}", i.statement)] + [(f"insight {i.id} recommendation", x) for x in i.recommendations]
    texts += [(f"job {j.id}", j.job) for j in files["jobs"]]
    texts += [(f"opportunity {o.id}", o.statement) for o in files["opportunities"]]
    for h in files["hypotheses"]:
        ns = h.next_step
        texts += [(f"hypothesis {h.id}", t) for t in [h.statement, ns.method, ns.recruit or "", ns.confirm, ns.disconfirm,
                                                    *ns.questions, *(sg.text for sg in h.signals)]]
    for where, text in texts:
        problems += [f"{where}: {tok}  <- write it in words, or use a placeholder in summary.md" for tok in typed(text)]
    for o in files["observations"]:
        own = post_numbers(posts, o.post_id)
        problems += [f"observation {o.post_id}: {tok}  <- not in the post it cites" for tok in typed(o.observation, own)]
    return problems


def check_numbers(study_dir: Path) -> dict:
    study_dir = Path(study_dir)
    if not (study_dir / RESULTS).exists():
        raise InputError("No results/results.json. Run crp analyse first.")
    files = [study_dir / d / f for d in (OUT, SHAREABLE) for f in ("report.md", "dashboard.html") if (study_dir / d / f).exists()]
    if not files:
        raise InputError("Nothing to check. Run crp build first.")
    allowed = traceable(study_dir)
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    problems = check_prose(study_dir, posts)
    for f in files:
        problems += (check_markdown if f.suffix == ".md" else check_html)(f, allowed, posts)
    return {"ok": not problems, "files": [str(f.relative_to(study_dir)) for f in files], "problems": problems}
