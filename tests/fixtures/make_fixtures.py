"""Write the synthetic test study in tests/fixtures/quillnote-fixture/.

Quillnote is a fictional notes app. The data is invented for tests and is not a demo study (D16).
The script writes raw sources in the formats a real study uses (a pasted forum page and its
capture file, a screenshot and its capture file, a Reddit JSON export, a Reddit CSV export and an
interview transcript), then runs crp ingest, verify and anonymise on a copy to produce posts.jsonl.

Run from the project root to regenerate:  python tests/fixtures/make_fixtures.py
The output is deterministic; test_fixtures.py checks the committed files match it.
"""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

STUDY_ID = "quillnote-fixture"
FIXTURE_SALT = hashlib.sha256(b"quillnote fixture salt, not a secret").hexdigest()
OWL = "night_owl_notes"  # the prolific poster: 12 posts across four threads

# ---- thread content: opener (author, text, score), replies (author, text, parent reply number or None, score)
T1_OPENER = ("maria_k", "Is the new Pro price worth it? It went from 4 to 7 a month and our lab of six is now "
                        "asking whether we should all move to something cheaper.", 14)
T1_REPLIES = [
    (OWL, "I pay it because the templates save me hours every week, but I understand why a lab would balk at "
          "paying for six seats.", None, 9),
    ("tomasz_r", "We cancelled the team plan in April. Nobody could justify the jump to the department, so half "
                 "of us went back to the free tier.", None, 11),
    (OWL, "The free tier caps you at 1,000 notes though, which you hit fast if you clip papers.", 2, 4),
    ("lena.v", "Honestly the price is fine for what it does, my problem is how slow search gets once it's full.",
     None, 6),
    ("quietdesk", "I would pay more if offline mode worked properly on the train.", None, 5),
    (OWL, "Offline has improved since March but it still loses the last edit sometimes.", 5, 2),
    ("pb_writes", "Students get half price if you email support with a university address.", None, 7),
    ("deal_hunter_x", "Use my code QUILL20 for a discount on Pro, link in bio!", None, 0),
    (OWL, "For the record I'd still recommend it to a solo researcher at the new price.", None, 3),
]
T2_TITLE = "Search is slow once you pass 2,000 notes"
T2_OPENER = ("archivist_jo", "Anyone else? It takes about ten seconds to find anything in my archive now.", 42)
T2_REPLIES = [
    (OWL, "Yes, past about 3,000 notes it crawls. I keep a separate index file as a workaround.", None, 18),
    ("kb_lin", "I switched to a plain folder of markdown files for the archive and only keep active projects in "
               "Quillnote.", None, 15),
    ("fern_and_ink", "Search is fine for me with 500 notes, so it must be a scale problem.", None, 8),
    (OWL, "It is scale. Tags help a little because filtering by tag first is faster.", 3, 6),
    ("rowan_p", "The backlinks panel is how I find things now instead of search.", None, 12),
    ("the_indexer", "Support told me a new search engine is coming in the autumn release.", None, 20),
    (OWL, "They said the same last year, so I wouldn't plan around it.", 6, 9),
    ("mika.s", "Exporting to search elsewhere loses the links between notes, which is the whole point.", None, 7),
    ("oldschool_ed", "I gave up and went back to a paper index for my thesis references.", None, 5),
    (OWL, "A paper index for references is not as mad as it sounds, I have done the same.", 9, 3),
    ("lurker_b", "Same, it's painful.", None, 1),
]
T3_TITLE = "Sync broke after the 4.2 update"
T3_OPENER = ("sam_h", "Is anyone else losing edits between devices? I have reinstalled twice and it keeps happening.",
             88)
SYNC_DETAILS = [
    "my phone and laptop show different versions of the same note",
    "edits I made on the train vanished when I got home",
    "the sync spinner never stops and nothing uploads",
    "shared notebooks show duplicate pages for everyone on the team",
    "images attached to notes come back blank on the desktop app",
    "the tablet app logs me out every time it tries to sync",
    "tags I added yesterday disappeared overnight",
    "a whole notebook reverted to how it looked last month",
    "notes created offline never appear on my other devices",
    "the web app shows a sync conflict on every single page",
]
SYNC_ENDINGS = [
    "and support hasn't replied to my ticket yet.",
    "so I have stopped trusting it for anything important.",
    "which cost me most of a morning to sort out.",
    "and rolling back to 4.1 is the only thing that helped.",
]
T3_REPLIES = [(f"sync_user_{n + 1:02d}", f"Since the 4.2 update {SYNC_DETAILS[n % 10]}, {SYNC_ENDINGS[n // 10]}",
               None, (n * 5) % 13) for n in range(38)]
T3_REPLIES.insert(12, (OWL, "Since the 4.2 update my phone and laptop disagree about which notes exist, so I now "
                            "export a backup every night before closing the app.", None, 10))
T3_REPLIES.insert(30, (OWL, "Following up: rolling back to 4.1 fixed sync for me, but I lost two days of edits made "
                            "on the tablet.", None, 8))
T4_OPENER = ("pb_writes", "What do you love about Quillnote? Trying to decide whether to renew and would like to "
                          "hear the good side for once.", 10)
T4_REPLIES = [
    (OWL, "The templates. I built a literature review template years ago and still use it daily.", None, 6),
    ("maria_k", "Backlinks changed how I write. I find old ideas I had forgotten about.", None, 9),
    ("lena.v", "The daily note is the only habit that has ever stuck for me.", None, 4),
    ("gardenofnotes", "Clean design, no clutter, and the mobile app is quick when sync behaves.", None, 3),
    (OWL, "Also the export to PDF is the best of any notes app I have tried.", 1, 2),
    ("tomasz_r", "Even after we cancelled I kept a personal plan just for the templates.", None, 5),
]
INTERVIEW = [("Ana", "Can you walk me through the last time you looked for an old note?"),
             ("Dev", "Last Tuesday I needed a quote from a paper I read in spring. Search took ages, so I scrolled "
                     "through the backlinks from the project page instead."),
             ("Ana", "What happened after that?"),
             ("Dev", "I found it in about five minutes, but I had to know which project it belonged to. If I hadn't "
                     "remembered that, I'd have given up."),
             ("Ana", "How do you feel about the price change?"),
             ("Dev", "My department pays, so I don't notice it. I think I'd switch if I had to pay myself."),
             ("Ana", "Is there anything that would make you leave?"),
             ("Dev", "If sync lost my work again. It happened once in June and I rewrote a whole section of a "
                     "chapter.")]


def epoch(day: str, minutes: int) -> int:
    t = dt.datetime.fromisoformat(day) + dt.timedelta(hours=9, minutes=minutes)
    return calendar.timegm(t.timetuple())


def capture(source_file, site, captured, title, query, opener, replies, day, approx=False) -> dict:
    posts = [{"id": "p01", "author": opener[0], "date": day, "date_approx": approx, "parent": None,
              "score": opener[2], "text": opener[1]}]
    for i, (author, text, parent, score) in enumerate(replies, 2):
        posts.append({"id": f"p{i:02d}", "author": author, "date": day, "date_approx": approx,
                      "parent": f"p{parent + 1:02d}" if parent else None, "score": score, "text": text})
    return {"source_file": source_file, "site": site, "url": None, "captured": captured, "thread_title": title,
            "search_query": query, "posts": posts}


def paste_page(cap: dict) -> str:
    """How the thread looks when copied from a browser: names, dates and buttons around each post."""
    lines = [cap["thread_title"], "Quillnote community forum > Pricing", ""]
    for p in cap["posts"]:
        text = p["text"].replace("it's full", "it’s full")  # the page has a curly apostrophe
        lines += [f"{p['author']}  ·  {p['date']}", text, f"Reply   Like {p['score']}", ""]
    return "\n".join(lines)


def screenshot(cap: dict) -> bytes:
    from PIL import Image, ImageDraw
    lines = []
    for p in cap["posts"]:
        words, row = p["text"].split(), ""
        lines.append(f"{p['author']} . 2 months ago")
        for w in words:
            if len(row) + len(w) > 70:
                lines.append(row)
                row = ""
            row = f"{row} {w}".strip()
        lines += [row, ""]
    img = Image.new("L", (760, 18 * len(lines) + 20), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((10, 10 + 18 * i), line, fill=0)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def reddit_listing() -> list:
    sub, link = "notetaking", "q2srch"
    post = {"kind": "t3", "data": {"id": link, "author": T2_OPENER[0], "title": T2_TITLE, "selftext": T2_OPENER[1],
                                   "score": T2_OPENER[2], "created_utc": epoch("2026-05-14", 0), "subreddit": sub}}
    nodes = []
    for i, (author, text, parent, score) in enumerate(T2_REPLIES, 1):
        nodes.append({"kind": "t1", "data": {
            "id": f"c{i:02d}", "parent_id": f"t1_c{parent:02d}" if parent else f"t3_{link}", "link_id": f"t3_{link}",
            "author": author, "body": text, "score": score, "created_utc": epoch("2026-05-14", 7 * i),
            "subreddit": sub, "replies": ""}})
    by_id = {n["data"]["id"]: n for n in nodes}
    top = []
    for n in nodes:
        parent = n["data"]["parent_id"]
        if parent.startswith("t1_"):
            host = by_id[parent[3:]]["data"]
            if not host["replies"]:
                host["replies"] = {"kind": "Listing", "data": {"children": []}}
            host["replies"]["data"]["children"].append(n)
        else:
            top.append(n)
    top.append({"kind": "more", "data": {"count": 3, "children": ["x1", "x2", "x3"]}})
    return [{"kind": "Listing", "data": {"children": [post]}}, {"kind": "Listing", "data": {"children": top}}]


def reddit_csv() -> str:
    link = "q3sync"
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["id", "parent_id", "link_id", "author", "body", "title", "score", "created_utc", "subreddit"])
    w.writerow([link, "", link, T3_OPENER[0], T3_OPENER[1], T3_TITLE, T3_OPENER[2], epoch("2026-06-10", 0),
                "notetaking"])
    for i, (author, text, _, score) in enumerate(T3_REPLIES, 1):
        w.writerow([f"k{i:02d}", f"t3_{link}", f"t3_{link}", author, text, "", score, epoch("2026-06-10", 5 * i),
                    "notetaking"])
    w.writerow(["k99", f"t3_{link}", f"t3_{link}", "AutoModerator", "Please search before posting.", "", 1,
                epoch("2026-06-10", 1), "notetaking"])
    return out.getvalue()


STUDY = {"id": STUDY_ID, "subject": "Quillnote (fictional, for tests)", "type": "product",
         "questions": ["Why do people stay with Quillnote or leave it?",
                       "What gets in the way of finding and keeping notes?"],
         "stance_target": None, "event_date": "2026-06-09", "window_start": "2026-04-01",
         "window_end": "2026-08-31", "sources": ["Quillnote community forum", "reddit.com/r/notetaking"],
         "population": "People posting about Quillnote in its forum and r/notetaking, plus one interview",
         "owner": "Steeve", "created": "2026-09-26"}

COLLECTION_LOG = """source,search_term,date,reason,neutral,results_seen,kept,why_excluded
Quillnote community forum,pro price,2026-09-20,pricing change announced in March,n,14,1,off-topic or duplicates
Quillnote community forum,what do you love,2026-09-20,balance the complaint-led searches,y,9,1,older than the study window
reddit.com/r/notetaking,quillnote search slow,2026-09-21,people mention search at scale,n,22,1,duplicates
reddit.com/r/notetaking,quillnote sync,2026-09-21,sync problems after 4.2,n,31,1,
reddit.com/r/notetaking,quillnote,2026-09-21,neutral name-only search,y,40,0,nothing beyond the threads already kept
"""

SCORE_DEFS = {-2: "strongly negative: strong language, lost work, cancelled or switched",
              -1: "negative: a plain complaint", 0: "neutral, mixed, unclear or off-topic",
              1: "positive", 2: "strongly positive: strong language or a clear benefit"}
ASPECTS = ["pricing", "search", "sync", "templates", "offline", "backlinks"]
CODEBOOK = {
    "version": "1", "study_type": "product", "aspects": ASPECTS,
    "aspect_definitions": {"pricing": "what it costs, plans and discounts",
                           "search": "finding notes by searching",
                           "sync": "keeping notes the same across devices"},
    "variables": [
        {"name": "overall", "description": "The writer's evaluation of Quillnote, not their mood (D13)",
         "applies_to": "measurement", "kind": "single", "level": "ordinal", "values": [-2, -1, 0, 1, 2],
         "definitions": SCORE_DEFS},
        {"name": "aspect_scores", "description": "Each aspect the comment evaluates, with its own score",
         "applies_to": "measurement", "kind": "per_aspect", "level": "ordinal", "values": [-2, -1, 0, 1, 2]},
        {"name": "jtbd_force", "description": "Force of progress (Moesta & Spiek)", "applies_to": "detail",
         "level": "nominal", "values": ["push", "pull", "anxiety", "habit", "none"]},
        {"name": "evidence_type", "description": "Evidence grade, weakest to strongest", "applies_to": "detail",
         "level": "ordinal", "values": ["hypothetical", "opinion", "habitual", "specific_incident", "observed"]},
        {"name": "friction", "description": "Hit an obstacle, workaround, error or unmet need",
         "applies_to": "detail", "level": "nominal", "values": [True, False]},
        {"name": "severity", "description": "How bad the friction was", "applies_to": "detail",
         "level": "ordinal", "values": [1, 2, 3], "required_when": "friction",
         "definitions": {1: "minor", 2: "moderate: workaround, lost time or real frustration",
                         3: "severe: blocked, lost data, or drove switching"}},
        {"name": "aspect", "description": "The one aspect the nugget is mainly about", "applies_to": "detail",
         "level": "nominal", "values": ASPECTS + ["not_applicable"]},
    ]}


def write_inputs(out: Path) -> None:
    d = out / STUDY_ID
    raw = d / "raw"
    for sub in ("capture", "reddit", "interviews"):
        (raw / sub).mkdir(parents=True, exist_ok=True)
    t1 = capture("pro_price.txt", "Quillnote community forum", "2026-09-20", "Is the new Pro price worth it?",
                 "pro price", T1_OPENER, T1_REPLIES, "2026-04-02")
    t4 = capture("love.png", "Quillnote community forum", "2026-09-20", "What do you love about Quillnote?",
                 "what do you love", T4_OPENER, T4_REPLIES, "2026-07-20", approx=True)
    for name, cap in (("pro_price.json", t1), ("love.json", t4)):
        (raw / "capture" / name).write_text(json.dumps(cap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (raw / "pro_price.txt").write_text(paste_page(t1), encoding="utf-8")
    (raw / "love.png").write_bytes(screenshot(t4))
    (raw / "reddit" / "search_thread.json").write_text(json.dumps(reddit_listing(), indent=1) + "\n", encoding="utf-8")
    (raw / "reddit" / "sync_export.csv").write_text(reddit_csv(), encoding="utf-8")
    (raw / "interviews" / "interview_01.txt").write_text(
        "".join(f"{name}: {text}\n" for name, text in INTERVIEW), encoding="utf-8")
    (d / "study.yaml").write_text(yaml.safe_dump(STUDY, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (d / "codebook.yaml").write_text(yaml.safe_dump(CODEBOOK, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (d / "collection_log.csv").write_text(COLLECTION_LOG, encoding="utf-8")
    (out / "fixture-secrets").mkdir(exist_ok=True)
    (out / "fixture-secrets" / "salt").write_text(FIXTURE_SALT + "\n", encoding="utf-8")


def build_posts(out: Path) -> None:
    """Run the real pipeline on a copy, and keep only posts.jsonl from it."""
    from crp.anonymise import anonymise
    from crp.ingest import ingest
    from crp.verify import verify
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "studies" / STUDY_ID
        shutil.copytree(out / STUDY_ID, work)
        ingest(work)
        if not verify(work)["ok"]:
            raise SystemExit("the fixture's own transcriptions failed crp verify")
        anonymise(work, out / "fixture-secrets")
        shutil.copyfile(work / "posts.jsonl", out / STUDY_ID / "posts.jsonl")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    write_inputs(target)
    build_posts(target)
