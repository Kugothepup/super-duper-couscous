#!/usr/bin/env python3
"""Turn captured forum posts (pasted text or screenshots) into pipeline turns, with checks.

Pasted pages and screenshots are too varied to parse by rule, so Claude first transcribes
each source file into a capture file, WORK/capture/<name>.json:

{
  "source_file": "forum_thread_1.txt",        # the paste or screenshot it came from
  "site": "Notion community forum",           # or "reddit.com/r/PKMS"
  "url": "https://...",                        # if known
  "captured": "2026-09-20",                    # date the page was captured
  "thread_title": "Is the new pricing worth it?",
  "search_query": "notion pricing researchers",# how it was found (see collection log)
  "posts": [
    {"id": "p1", "author": "maria_k", "date": "2026-09-02", "date_approx": false,
     "parent": null, "score": 14, "text": "verbatim post text"},
    {"id": "p2", "author": null, "date": "2026-08-01", "date_approx": true,
     "parent": "p1", "score": null, "text": "..."}
  ]
}

Checks (errors stop the build; warnings are reported and carried to the dashboard):
  - pasted text (.txt/.md): every post's text must appear verbatim in the source file
  - screenshots (.png/.jpg): with --ocr, the transcription is compared with Tesseract OCR
    and low word overlap is flagged for a human look
  - parents must exist; dates must be YYYY-MM-DD (relative dates converted, marked approx)
  - exact and near-duplicate posts (cross-posts, quoted reposts) are dropped and counted
  - promotional-looking posts are flagged (not removed)

Usage:
  python parse_forum.py --work WORKDIR --sources path/to/originals [--ocr] [--min-overlap 0.6]
Writes WORKDIR/turns/Txx.json (one per captured thread), manifest.json, authors_private.json
and forum_checks.json.
"""
import argparse
import datetime as dt
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import clean_quotes, load_json, norm, save_json  # noqa: E402

TEXT_EXT = {".txt", ".md", ".html", ".htm"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
PROMO = re.compile(r"(use (?:my )?code|discount code|affiliate|dm me|check out my|sign up (?:here|at)|"
                   r"link in (?:my )?bio|promo|sponsored|referral)", re.I)


def shingles(text, k=5):
    w = norm(text).split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def ocr_text(path):
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    try:
        return pytesseract.image_to_string(Image.open(path))
    except Exception:  # noqa: BLE001
        return None


def valid_date(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--sources", required=True, help="folder with the original pastes/screenshots")
    ap.add_argument("--ocr", action="store_true", help="cross-check screenshot transcriptions with Tesseract")
    ap.add_argument("--min-overlap", type=float, default=0.6)
    ap.add_argument("--near-dup", type=float, default=0.8, help="Jaccard similarity to treat posts as duplicates")
    args = ap.parse_args()
    work, src_dir = Path(args.work), Path(args.sources)
    caps = sorted((work / "capture").glob("*.json"))
    if not caps:
        raise SystemExit(f"No capture files in {work}/capture. Transcribe the sources first (see docstring).")

    errors, warnings = [], []
    threads = []
    for cp in caps:
        cap = load_json(cp)
        where = cp.name
        sf = cap.get("source_file")
        src = src_dir / sf if sf else None
        if not src or not src.exists():
            errors.append(f"{where}: source_file '{sf}' not found in {src_dir}")
            continue
        posts = cap.get("posts") or []
        if not posts:
            errors.append(f"{where}: no posts")
            continue
        ids = [p.get("id") for p in posts]
        if len(set(ids)) != len(ids):
            errors.append(f"{where}: duplicate post ids")
        captured = valid_date(cap.get("captured"))
        if not captured:
            warnings.append(f"{where}: no valid 'captured' date; relative dates can't be checked")
        suf = src.suffix.lower()
        src_norm = norm(src.read_text(encoding="utf-8", errors="replace")) if suf in TEXT_EXT else None
        ocr = norm(ocr_text(src) or "") if (suf in IMG_EXT and args.ocr) else None
        if suf in IMG_EXT and args.ocr and not ocr:
            warnings.append(f"{where}: OCR unavailable or empty for {sf}; transcription unchecked")
        for p in posts:
            pw = f"{where}/{p.get('id')}"
            text = clean_quotes(p.get("text") or "").strip()
            if not text:
                errors.append(f"{pw}: empty text")
                continue
            if p.get("parent") and p["parent"] not in ids:
                errors.append(f"{pw}: parent '{p['parent']}' not in this capture")
            if p.get("date") and not valid_date(p["date"]):
                errors.append(f"{pw}: date must be YYYY-MM-DD (convert '2 years ago' using the capture date "
                              "and set date_approx: true)")
            if src_norm is not None and norm(text) not in src_norm:
                errors.append(f"{pw}: text not found verbatim in {sf}. Copy it exactly; don't tidy wording.")
            if ocr is not None and ocr:
                ocr_words = set(ocr.split())
                words = [w for w in norm(text).split() if len(w) > 2]
                missing = [w for w in words if w not in ocr_words]
                hit = 1 - len(missing) / len(words) if words else 1
                p["_ocr_overlap"] = round(hit, 2)
                if hit < args.min_overlap or len(missing) >= 2:
                    warnings.append(f"{pw}: words not seen by OCR in {sf}: {', '.join(missing[:8])}. "
                                    "Check the transcription against the image.")
            if suf in IMG_EXT and not args.ocr:
                p["_unverified"] = True
            p["text"] = text
        threads.append((cp, cap, suf))

    # de-duplicate across all captures (cross-posts, quoted reposts, same thread captured twice)
    seen_exact, seen_sh, dropped = {}, [], Counter()
    for cp, cap, _ in threads:
        keep = []
        for p in cap["posts"]:
            key = norm(p["text"])
            if len(key.split()) >= 6 and key in seen_exact:
                dropped["exact"] += 1
                p["_dup_of"] = seen_exact[key]
                continue
            sh = shingles(p["text"])
            if len(key.split()) >= 12 and any(jaccard(sh, o) >= args.near_dup for o, _ in seen_sh):
                dropped["near"] += 1
                continue
            seen_exact[key] = f"{cp.stem}/{p['id']}"
            seen_sh.append((sh, p["id"]))
            keep.append(p)
        cap["posts"] = keep

    if errors:
        for e in errors:
            print(f"ERROR {e}")
        for w in warnings:
            print(f"WARN  {w}")
        print(f"\n{len(errors)} error(s). Fix the capture files and re-run; nothing was written.")
        sys.exit(1)

    authors, anon = {}, [0]
    manifest = []
    promo_total = unverified = 0
    for n, (cp, cap, suf) in enumerate(threads, 1):
        tid = f"T{n:02d}"
        order, kids = [], defaultdict(list)
        pid = {p["id"]: p for p in cap["posts"]}
        for p in cap["posts"]:
            (kids[p["parent"]] if p.get("parent") in pid else kids[None]).append(p)

        def walk(p, depth, parent_turn):
            order.append((p, depth, parent_turn))
            me = len(order)
            for c in kids[p["id"]]:
                walk(c, depth + 1, me)
        for r in kids[None]:
            walk(r, 0 if r is cap["posts"][0] else 1, None)
        first_author = cap["posts"][0].get("author") if cap["posts"] else None
        turns = []
        for i, (p, depth, parent_turn) in enumerate(order, 1):
            a = p.get("author")
            if a:
                if a not in authors:
                    authors[a] = f"A{len(authors) + 1:03d}"
                aid = authors[a]
            else:
                anon[0] += 1
                aid = f"U{anon[0]:03d}"
            promo = bool(PROMO.search(p["text"])) or p["text"].count("http") >= 3
            promo_total += promo
            unverified += bool(p.get("_unverified"))
            turns.append({"turn_id": i, "speaker": aid, "author_id": aid, "role": "participant",
                          "kind": "post" if i == 1 and depth == 0 else "comment",
                          "is_op": bool(a) and a == first_author, "score": p.get("score") or 0,
                          "depth": depth, "parent_turn": parent_turn,
                          "created": f"{p['date']} 12:00" if p.get("date") else None,
                          "date_approx": bool(p.get("date_approx")), "promotional": promo,
                          "unverified": bool(p.get("_unverified")), "ocr_overlap": p.get("_ocr_overlap"),
                          "start": None, "end": None, "text": p["text"]})
        n_anon = sum(t["author_id"].startswith("U") for t in turns)
        tw = []
        if n_anon:
            tw.append(f"{n_anon} post(s) without an author name: each counts as its own person")
        if sum(1 for t in turns if t["created"]) < len(turns):
            tw.append("some posts have no date and are left out of trends")
        doc = {"transcript_id": tid, "source_type": "forum", "source_file": cap["source_file"],
               "site": cap.get("site", ""), "subreddit": cap.get("site", ""), "url": cap.get("url"),
               "title": cap.get("thread_title", ""), "search_query": cap.get("search_query"),
               "captured": cap.get("captured"), "capture_kind": "screenshot" if suf in IMG_EXT else "paste",
               "speakers": {t["speaker"]: "participant" for t in turns},
               "role_method": "forum (all authors are participants)",
               "has_timestamps": False, "has_end_times": False,
               "participant_words": sum(len(t["text"].split()) for t in turns), "turns": turns}
        save_json(doc, work / "turns" / f"{tid}.json")
        manifest.append({"transcript_id": tid, "source_type": "forum", "source_file": cap["source_file"],
                         "site": doc["site"], "subreddit": doc["site"], "title": doc["title"],
                         "capture_kind": doc["capture_kind"], "search_query": doc["search_query"],
                         "n_turns": len(turns), "n_authors": len({t["author_id"] for t in turns}),
                         "speakers": {}, "role_method": doc["role_method"],
                         "participant_words": doc["participant_words"], "warnings": tw})
    save_json(manifest, work / "manifest.json")
    save_json({v: k for k, v in authors.items()}, work / "authors_private.json")
    checks = {"duplicates_dropped": dict(dropped), "promotional_flagged": promo_total,
              "screenshot_posts_unverified": unverified, "warnings": warnings,
              "anonymous_posts": anon[0], "n_threads": len(manifest)}
    save_json(checks, work / "forum_checks.json")

    for m in manifest:
        print(f"{m['transcript_id']}  {m['site']}  \"{m['title'][:50]}\"  posts={m['n_turns']}  "
              f"authors={m['n_authors']}  ({m['capture_kind']})")
        for w in m["warnings"]:
            print(f"     ! {w}")
    for w in warnings:
        print(f"WARN  {w}")
    print(f"\nDropped duplicates: {dict(dropped) or 'none'} · promotional flagged: {promo_total}"
          + (f" · {unverified} screenshot posts unverified (run with --ocr)" if unverified else ""))
    by_site = Counter()
    for m in manifest:
        by_site[m["site"]] += m["n_turns"]
    top, cnt = by_site.most_common(1)[0]
    if len(by_site) > 1 and cnt / sum(by_site.values()) > 0.5:
        print(f"! {cnt / sum(by_site.values()):.0%} of posts come from {top}; results will mostly reflect it.")


if __name__ == "__main__":
    main()
