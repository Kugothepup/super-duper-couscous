"""Shared helpers for the interview-synthesis scripts."""
import json
import re
import unicodedata
from pathlib import Path

FORCES = ["push", "pull", "anxiety", "habit", "none"]
EVIDENCE = ["observed", "specific_incident", "habitual", "opinion", "hypothetical"]
STRONG_EVIDENCE = {"observed", "specific_incident"}
CONFIDENCE = ["high", "medium", "low"]
VERDICTS = ["supported", "contradicted", "mixed", "not testable"]
# Words of estimative probability (US ICD 203), with the ranges they stand for
LIKELIHOOD = {"almost no chance": "1-5%", "very unlikely": "5-20%", "unlikely": "20-45%",
              "roughly even chance": "45-55%", "likely": "55-80%", "very likely": "80-95%",
              "almost certain": "95-99%"}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def clean_quotes(s):
    return (s.replace("\u2019", "'").replace("\u2018", "'")
             .replace("\u201c", '"').replace("\u201d", '"'))


def norm(s):
    """Lowercase, unify quotes, strip punctuation, collapse spaces (for verbatim checks)."""
    s = unicodedata.normalize("NFKC", clean_quotes(s or "")).lower()
    s = s.replace("'", "")
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_manifest(work):
    p = Path(work) / "manifest.json"
    if not p.exists():
        raise SystemExit(f"No manifest at {p}. Run parse_transcripts.py first.")
    return load_json(p)


def load_turns(work, tid):
    return load_json(Path(work) / "turns" / f"{tid}.json")


def load_signals(work, tid):
    p = Path(work) / "signals" / f"{tid}.json"
    return load_json(p) if p.exists() else None


def load_nuggets(work):
    """Return {transcript_id: [nuggets]} from WORK/nuggets/*.json."""
    out = {}
    d = Path(work) / "nuggets"
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        data = load_json(p)
        if isinstance(data, dict):
            data = data.get("nuggets", [])
        for n in data:
            if isinstance(n, dict):
                n.setdefault("jtbd_force", "none")  # optional outside the product lens
        out[p.stem] = data
    return out


def all_nuggets(work):
    return [n for ns in load_nuggets(work).values() for n in ns]


# ---- study mode helpers (interview vs reddit) ----

ONLINE_SOURCES = {"reddit", "forum"}


def study_mode(manifest):
    """'reddit' = online-community mode (Reddit and other forums): coverage by author,
    triage, echoes, quote-free outputs. 'interview' otherwise."""
    types = {m.get("source_type", "interview") for m in manifest}
    return "reddit" if types and types <= ONLINE_SOURCES else "interview"


def turn_index(work):
    """{(transcript_id, turn_id): turn} across the whole study."""
    idx = {}
    for m in load_manifest(work):
        for t in load_turns(work, m["transcript_id"])["turns"]:
            idx[(m["transcript_id"], t["turn_id"])] = t
    return idx


def unit_of(nugget, mode, tindex):
    """The independent 'voice' behind a nugget: author (reddit) or transcript (interview)."""
    if mode == "reddit":
        t = tindex.get((nugget.get("transcript_id"), (nugget.get("turn_ids") or [None])[0]))
        return t.get("author_id") if t else None
    return nugget.get("transcript_id")


def unit_label(mode):
    return "authors" if mode == "reddit" else "transcripts"


def total_units(work, mode, manifest=None):
    manifest = manifest or load_manifest(work)
    if mode != "reddit":
        return len(manifest)
    authors = set()
    for m in manifest:
        for t in load_turns(work, m["transcript_id"])["turns"]:
            if t["role"] == "participant":
                authors.add(t.get("author_id"))
    return len(authors)


# ---- study lens: what kind of subject is being studied ----
FRAMES = ["problem", "cause", "moral", "remedy", "none"]  # Entman (1993) framing functions

LENSES = {
    "product": {
        "label": "Product",
        "aspect_word": "feature or aspect",
        "jtbd": True, "frames": False, "stance": False,
        "entity_title": "Alternatives in play",
        "entity_lede": "Products people mention, and the forces attached to those mentions.",
        "sections": ["verdict", "drivers", "direction", "themes", "pains", "successes", "jobs",
                     "opportunities", "entities", "outlook", "language", "hypotheses", "trust"],
        "names": {"drivers": "What drives sentiment", "themes": "Themes", "pains": "Pain points",
                  "successes": "Success moments", "opportunities": "Opportunities"},
    },
    "brand": {
        "label": "Brand",
        "aspect_word": "brand association",
        "jtbd": False, "frames": False, "stance": False,
        "entity_title": "Competitors and comparisons",
        "entity_lede": "Brands people compare with, and whether mentions pull towards or push away.",
        "sections": ["verdict", "drivers", "associations", "direction", "themes", "pains", "successes",
                     "jobs", "opportunities", "entities", "outlook", "language", "hypotheses", "trust"],
        "names": {"drivers": "What shapes perception", "themes": "Themes", "pains": "Where the brand lets people down",
                  "successes": "Moments of advocacy", "opportunities": "Opportunities"},
    },
    "news": {
        "label": "News story",
        "aspect_word": "sub-topic, claim or actor",
        "jtbd": False, "frames": True, "stance": True,
        "entity_title": "Actors and organisations",
        "entity_lede": "Who people talk about in connection with the story.",
        "sections": ["verdict", "stance", "drivers", "direction", "themes", "framing", "questions",
                     "entities", "opportunities", "outlook", "language", "hypotheses", "trust"],
        "names": {"drivers": "What drives the reaction", "themes": "Narratives", "pains": "Concerns",
                  "successes": "Positive reactions", "opportunities": "Implications"},
    },
    "topic": {
        "label": "Topic or issue",
        "aspect_word": "sub-topic or argument",
        "jtbd": False, "frames": True, "stance": True,
        "entity_title": "Actors and organisations",
        "entity_lede": "Who people bring into the discussion.",
        "sections": ["verdict", "stance", "drivers", "direction", "themes", "framing", "questions",
                     "pains", "entities", "opportunities", "outlook", "language", "hypotheses", "trust"],
        "names": {"drivers": "What drives opinion", "themes": "Narratives", "pains": "Concerns",
                  "successes": "Positive reactions", "opportunities": "Implications"},
    },
}


def load_study(work):
    """WORK/study.json, with defaults (product lens) if absent."""
    p = Path(work) / "study.json"
    s = load_json(p) if p.exists() else {}
    s.setdefault("type", "product")
    s.setdefault("subject", "")
    s.setdefault("questions", [])
    s["lens"] = LENSES.get(s["type"], LENSES["product"])
    return s


def entity_tags(tags):
    """Yield entity names from product:<name> or entity:<name> tags."""
    for t in tags or []:
        if t.startswith(("product:", "entity:", "brand:")):
            yield t.split(":", 1)[1]
