"""Write the synthetic test study in tests/fixtures/quillnote-fixture/.

Quillnote is a fictional notes app. The data is invented for tests and is not a demo study (D16).
Run from the project root to regenerate:  python tests/fixtures/make_fixtures.py
The output is deterministic; test_fixtures.py checks the committed files match it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import yaml

STUDY_ID = "quillnote-fixture"
SALT = b"fixture-salt-not-a-secret"
FORUM = "Quillnote community forum"
REDDIT = "reddit.com/r/notetaking"


def code(name: str) -> str:
    return "P-" + hmac.new(SALT, name.encode(), hashlib.sha256).hexdigest()[:8]


def thread(tid, source, capture, raw, stamp, opener, replies, date_approx=False):
    """replies: (author, text, parent_index or None for the opening post, score)"""
    rows = [{"post_id": f"{tid}-p01", "source_type": "forum", "source": source, "thread_id": tid,
             "parent_id": None, "person_code": code(opener[0]), "role": "participant", "kind": "post",
             "timestamp": f"{stamp}T09:00:00", "date_approx": date_approx, "score": opener[2],
             "text": opener[1], "capture_method": capture, "raw_ref": f"{raw}#p01"}]
    for i, (author, text, parent, score) in enumerate(replies, 2):
        hour = 9 + (i * 7) // 60
        rows.append({"post_id": f"{tid}-p{i:02d}", "source_type": "forum", "source": source, "thread_id": tid,
                     "parent_id": f"{tid}-p{parent:02d}" if parent else f"{tid}-p01",
                     "person_code": code(author), "role": "participant", "kind": "comment",
                     "timestamp": f"{stamp}T{hour:02d}:{(i * 7) % 60:02d}:00", "date_approx": date_approx,
                     "score": score, "text": text, "capture_method": capture, "raw_ref": f"{raw}#p{i:02d}"})
    return rows


OWL = "night_owl_notes"  # the prolific poster: 12 posts across four threads

T1 = thread("T1", FORUM, "paste", "forum_pro_price.txt", "2026-04-02",
            ("maria_k", "Is the new Pro price worth it? It went from 4 to 7 a month and our lab of six "
                        "is now asking whether we should all move to something cheaper.", 14),
            [(OWL, "I pay it because the templates save me hours every week, but I understand why a lab "
                   "would balk at paying for six seats.", None, 9),
             ("tomasz_r", "We cancelled the team plan in April. Nobody could justify the jump to the "
                          "department, so half of us went back to the free tier.", None, 11),
             (OWL, "The free tier caps you at 1,000 notes though, which you hit fast if you clip papers.", 3, 4),
             ("lena.v", "Honestly the price is fine for what it does, my problem is how slow search gets.", None, 6),
             ("quietdesk", "I would pay more if offline mode worked properly on the train.", None, 5),
             (OWL, "Offline has improved since March but it still loses the last edit sometimes.", 6, 2),
             ("pb_writes", "Students get half price if you email support with a university address.", None, 7),
             ("deal_hunter_x", "Use my code QUILL20 for a discount on Pro, link in bio!", None, 0),
             (OWL, "For the record I'd still recommend it to a solo researcher at the new price.", None, 3)])

T2 = thread("T2", REDDIT, "export", "r_notetaking_search.json", "2026-05-14",
            ("archivist_jo", "Search in Quillnote is slow once you pass 2,000 notes. Anyone else? It takes "
                             "about ten seconds to find anything in my archive now.", 42),
            [(OWL, "Yes, past about 3,000 notes it crawls. I keep a separate index file as a workaround.", None, 18),
             ("kb_lin", "I switched to a plain folder of markdown files for the archive and only keep "
                        "active projects in Quillnote.", None, 15),
             ("fern_and_ink", "Search is fine for me with 500 notes, so it must be a scale problem.", None, 8),
             (OWL, "It is scale. Tags help a little because filtering by tag first is faster.", 4, 6),
             ("rowan_p", "The backlinks panel is how I find things now instead of search.", None, 12),
             ("the_indexer", "Support told me a new search engine is coming in the autumn release.", None, 20),
             (OWL, "They said the same last year, so I wouldn't plan around it.", 7, 9),
             ("mika.s", "Exporting to search elsewhere loses the links between notes, which is the whole point.", None, 7),
             ("oldschool_ed", "I gave up and went back to a paper index for my thesis references.", None, 5),
             (OWL, "A paper index for references is not as mad as it sounds, I have done the same.", 10, 3),
             ("lurker_b", "Same, it's painful.", None, 1)])

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
pile_on = []
for n in range(38):
    detail, ending = SYNC_DETAILS[n % 10], SYNC_ENDINGS[n // 10]
    pile_on.append((f"sync_user_{n + 1:02d}", f"Since the 4.2 update {detail}, {ending}", None, (n * 5) % 13))
pile_on.insert(12, (OWL, "Since the 4.2 update my phone and laptop disagree about which notes exist, "
                         "so I now export a backup every night before closing the app.", None, 10))
pile_on.insert(30, (OWL, "Following up: rolling back to 4.1 fixed sync for me, but I lost two days of edits "
                         "made on the tablet.", None, 8))

T3 = thread("T3", REDDIT, "export", "r_notetaking_sync.json", "2026-06-10",
            ("sam_h", "Sync broke after the 4.2 update. Is anyone else losing edits between devices? I have "
                      "reinstalled twice and it keeps happening.", 88),
            pile_on)

T4 = thread("T4", FORUM, "screenshot", "forum_love.png", "2026-07-20",
            ("pb_writes", "What do you love about Quillnote? Trying to decide whether to renew and would "
                          "like to hear the good side for once.", 10),
            [(OWL, "The templates. I built a literature review template years ago and still use it daily.", None, 6),
             ("maria_k", "Backlinks changed how I write. I find old ideas I had forgotten about.", None, 9),
             ("lena.v", "The daily note is the only habit that has ever stuck for me.", None, 4),
             ("gardenofnotes", "Clean design, no clutter, and the mobile app is quick when sync behaves.", None, 3),
             (OWL, "Also the export to PDF is the best of any notes app I have tried.", 2, 2),
             ("tomasz_r", "Even after we cancelled I kept a personal plan just for the templates.", None, 5)],
            date_approx=True)

INTERVIEW = [("Ana", "interviewer", "Can you walk me through the last time you looked for an old note?"),
             ("Dev", "participant", "Last Tuesday I needed a quote from a paper I read in spring. Search took "
                                    "ages, so I scrolled through the backlinks from the project page instead."),
             ("Ana", "interviewer", "What happened after that?"),
             ("Dev", "participant", "I found it in about five minutes, but I had to know which project it "
                                    "belonged to. If I hadn't remembered that, I'd have given up."),
             ("Ana", "interviewer", "How do you feel about the price change?"),
             ("Dev", "participant", "My department pays, so I don't notice it. I think I'd switch if I had to "
                                    "pay myself."),
             ("Ana", "interviewer", "Is there anything that would make you leave?"),
             ("Dev", "participant", "If sync lost my work again. It happened once in June and I rewrote a "
                                    "whole section of a chapter.")]


def interview_rows():
    rows = []
    for i, (name, role, text) in enumerate(INTERVIEW, 1):
        rows.append({"post_id": f"I01-t{i:02d}", "source_type": "interview", "source": "interview",
                     "thread_id": "I01", "parent_id": None, "person_code": code(name), "role": role,
                     "kind": "turn", "timestamp": f"2026-08-12T10:{i * 2:02d}:00", "date_approx": False,
                     "score": None, "text": text, "capture_method": "transcript",
                     "raw_ref": f"interview_01.txt#t{i:02d}"})
    return rows


STUDY = {"id": STUDY_ID, "subject": "Quillnote (fictional, for tests)", "type": "product",
         "questions": ["Why do people stay with Quillnote or leave it?",
                       "What gets in the way of finding and keeping notes?"],
         "stance_target": None, "event_date": "2026-06-09", "window_start": "2026-04-01",
         "window_end": "2026-08-31", "sources": [FORUM, REDDIT],
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


def write(out_dir: Path) -> None:
    d = out_dir / STUDY_ID
    d.mkdir(parents=True, exist_ok=True)
    posts = T1 + T2 + T3 + T4 + interview_rows()
    (d / "posts.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in posts),
                                   encoding="utf-8")
    (d / "study.yaml").write_text(yaml.safe_dump(STUDY, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (d / "codebook.yaml").write_text(yaml.safe_dump(CODEBOOK, sort_keys=False, allow_unicode=True),
                                     encoding="utf-8")
    (d / "collection_log.csv").write_text(COLLECTION_LOG, encoding="utf-8")


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
