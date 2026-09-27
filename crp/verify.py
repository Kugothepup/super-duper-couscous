"""crp verify: check every AI transcription against its source before anything is counted.

Quote check (pasted text), strictest first:
  exact       the text appears in the source as written
  normalised  it appears once spaces and quote marks are normalised (passes, with a note)
  tidied      a close match (rapidfuzz partial ratio >= 90) with words changed: shown as a diff
  failed      no close match: the text may be invented
OCR check (screenshots, needs the ocr extra and Tesseract): the transcription's words are
compared with what OCR reads; a post is flagged for a human look if under 60% of its words
are seen, or 2 or more are missing (ported from parse_forum.py). Without OCR, screenshot
posts are "unverified". Exports and transcripts were parsed by code, so there is nothing to check.

crp anonymise refuses to run while any transcription is tidied or failed (D20).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from rapidfuzz import fuzz

from crp import manifest
from crp.io import InputError, atomic_write_text, read_jsonl, sha256_file
from crp.ingest import INGESTED
from crp.schemas import IngestedPost
from crp.text import html_text, loose, tidy, word_diff

FUZZY_MIN = 90
OCR_MIN_OVERLAP = 0.6
OCR_MAX_MISSING = 2
MARKERS = re.compile(r"\[\?\]|\[cut off\]")  # the capture guide's marks for unreadable or cut-off text (D19)
ELISION = re.compile(r"\.\.\.|…|\[\s*\.\.\.\s*\]|\[\s*…\s*\]")
RANK = {"exact": 0, "normalised": 1, "tidied": 2, "failed": 3}
REPORT = Path("results") / "verify_report.json"  # statuses only
DETAILS = Path("raw") / "verify_details.json"  # diffs and missing words, which quote the text


def check_text(said: str, source: str) -> dict:
    """How closely `said` matches somewhere in `source`."""
    if said in source:
        return {"status": "exact"}
    t_said, t_src = tidy(said), tidy(source)
    if t_said and t_said in t_src:
        return {"status": "normalised", "note": "matches once spaces and quote marks are normalised"}
    al = fuzz.partial_ratio_alignment(t_said, t_src)
    score = round(al.score, 1)
    if al.score >= FUZZY_MIN:
        start, end = al.dest_start, al.dest_end
        while start > 0 and not t_src[start - 1].isspace():
            start -= 1
        while end < len(t_src) and not t_src[end].isspace():
            end += 1
        return {"status": "tidied", "score": score, "diff": word_diff(t_said, t_src[start:end])}
    return {"status": "failed", "score": score}


def check_quote(quote: str, source: str) -> dict:
    """A quote that may skip words with '...': each fragment must match, in order. Worst fragment wins."""
    frags = [f for f in ELISION.split(quote) if f.strip()]
    if len(frags) <= 1:
        return check_text(quote.strip(), source)
    results = [check_text(f.strip(), source) for f in frags]
    worst = max(results, key=lambda r: RANK[r["status"]])
    if worst["status"] in ("exact", "normalised"):
        t_src, pos = tidy(source), 0
        for f in frags:
            i = t_src.find(tidy(f), pos)
            if i < 0:
                return {"status": "failed", "note": "the parts are in the source, but not in this order"}
            pos = i + len(tidy(f))
    return worst


def ocr_text(path: Path) -> str | None:
    """Tesseract's reading of an image, or None if OCR isn't available."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    try:
        return pytesseract.image_to_string(Image.open(path))
    except Exception:  # noqa: BLE001 - no Tesseract binary, unreadable image
        return None


def check_ocr(said: str, ocr: str) -> dict:
    ocr_words = set(loose(ocr).split())
    words = [w for w in loose(MARKERS.sub(" ", said)).split() if len(w) > 2]
    missing = [w for w in words if w not in ocr_words]
    overlap = 1 - len(missing) / len(words) if words else 1.0
    status = "ocr_flagged" if overlap < OCR_MIN_OVERLAP or len(missing) >= OCR_MAX_MISSING else "ocr_ok"
    return {"status": status, "overlap": round(overlap, 2), "missing": missing[:8]}


def verify(study_dir: Path) -> dict:
    study_dir = Path(study_dir)
    ingested = study_dir / INGESTED
    if not ingested.exists():
        raise InputError(f"No {ingested}. Run crp ingest first.")
    posts = read_jsonl(ingested, IngestedPost)
    raw = study_dir / "raw"
    sources = sorted({raw / p.raw_ref.split("#")[0] for p in posts if p.capture_method in ("paste", "screenshot")})
    with manifest.stage(study_dir, "verify", inputs=[ingested, *[s for s in sources if s.exists()]]) as record:
        text_cache: dict[Path, str] = {}
        ocr_cache: dict[Path, str | None] = {}
        details, statuses = [], {}
        for p in posts:
            src = raw / p.raw_ref.split("#")[0]
            if p.capture_method in ("paste", "screenshot") and not src.exists():
                res = {"status": "failed", "note": f"source file {src.name} is missing from raw/"}
            elif p.capture_method == "paste":
                if src not in text_cache:
                    page = src.read_text(encoding="utf-8", errors="replace")
                    text_cache[src] = html_text(page) if src.suffix.lower() in (".html", ".htm") else page
                res = check_text(p.text, text_cache[src])
            elif p.capture_method == "screenshot":
                if src not in ocr_cache:
                    ocr_cache[src] = ocr_text(src)
                ocr = ocr_cache[src]
                res = check_ocr(p.text, ocr) if ocr and ocr.strip() else \
                    {"status": "unverified", "note": "OCR unavailable, so the transcription is unchecked"}
            else:
                res = {"status": "parsed", "note": "text came from the file, not a transcription"}
            statuses[p.post_id] = res["status"]
            if res["status"] not in ("exact", "parsed"):
                details.append({"post_id": p.post_id, "raw_ref": p.raw_ref, **res})
        counts: dict[str, int] = {}
        for s in statuses.values():
            counts[s] = counts.get(s, 0) + 1
        ok = not (counts.get("tidied") or counts.get("failed"))
        report = {"ingested_sha256": sha256_file(ingested), "ok": ok, "counts": counts, "posts": statuses}
        atomic_write_text(study_dir / REPORT, json.dumps(report, indent=2) + "\n")
        atomic_write_text(study_dir / DETAILS, json.dumps(details, indent=2, ensure_ascii=False) + "\n")
        record["outputs"] = [str(REPORT), str(DETAILS)]
        record["result"] = {"ok": ok, "counts": counts}
    return {"ok": ok, "counts": counts, "details": details}
