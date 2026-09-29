"""crp paste: copied Reddit pages into capture files that crp verify passes. The pages are invented."""
import datetime as dt
import json

import pytest

from crp.cli import main
from crp.ingest import ingest
from crp.io import InputError
from crp.paste import parse_reddit, paste
from crp.verify import verify

CAPTURED = dt.date(2026, 9, 28)

# The layout Steeve's pastes use: avatar lines, vote counts on their own, no "Upvote" buttons.
LINK_POST = """Quillnote to raise prices again
r/notetaking - Quillnote to raise prices again
example-news.com
The company says the new plan brings faster search and more storage for teams.

Open
12
·
7
Comments Section
AutoModerator
MOD
•
2d ago
u/maple_owl avatar
maple_owl
OP
•
2d ago
I posted this because our lab is deciding whether to renew before the price goes up.

9
u/river_fern avatar
river_fern
•
2d ago
Search has been slow for months, so paying more for the same thing feels like a joke.

5
u/quiet_heron avatar
quiet_heron
•
1d ago
> Search has been slow for months, so paying more for the same thing feels like a joke.

It is only slow for big archives, mine with a few hundred notes is fine.

2

2 more replies
[deleted]
•
1d ago
Comment deleted by user

1
u/pixel_moth avatar
pixel_moth
•
5h ago
Comment Image

3
u/slate_wren avatar
slate_wren
•
3mo ago
I left for plain markdown files last spring and have not missed the templates once.

-1
Continue this thread
"""

# The other layout ux-t met: a text post with a body, and "Upvote" before each vote count.
SELF_POST = """Is anyone else losing edits after the update?
r/notetaking - Is anyone else losing edits after the update?
Since the update my phone and laptop disagree about which notes exist.
Upvote
1.2K
Downvote
Share
maple_owl
OP
•
6h ago
Rolling back to the old version fixed it for me, but I lost a day of edits.
Upvote
40
Downvote
Reply
Promo_Account
•
Ad
Try the best notes app today.
Upvote
0
river_fern
•
3h ago
Same problem on the tablet, support has not replied to my ticket yet.
Upvote
12
Downvote
Reply
helpful_haiku
•
2h ago
Notes that disappear, I am a bot, beep boop.
Upvote
1
Downvote
Reply
"""


def test_link_post_layout():
    p = parse_reddit(LINK_POST, CAPTURED)
    assert p["community"] == "r/notetaking" and p["title"] == "Quillnote to raise prices again"
    assert p["link_post"] and p["post_votes"] == 12
    assert [c["author"] for c in p["comments"]] == ["maple_owl", "river_fern", "quiet_heron", "slate_wren"]
    assert p["skipped"] == {"ads": 0, "bots": 1, "deleted": 1, "image_only": 1}
    assert p["collapsed"] == {"more_replies": 2, "continue_threads": 1}
    first = p["comments"][0]
    assert first["op"] and first["score"] == 9 and first["date"] == "2026-09-26"
    assert p["comments"][3] == {"author": "slate_wren", "op": False, "date": "2026-06-30", "score": -1,
                                "text": "I left for plain markdown files last spring and have not missed the templates once."}


def test_self_post_layout_with_upvote_buttons():
    p = parse_reddit(SELF_POST, CAPTURED)
    assert not p["link_post"] and p["post_votes"] == 1200
    assert p["post_text"] == "Since the update my phone and laptop disagree about which notes exist."
    assert [(c["author"], c["score"]) for c in p["comments"]] == [("maple_owl", 40), ("river_fern", 12)]
    assert p["skipped"] == {"ads": 1, "bots": 1, "deleted": 0, "image_only": 0}


def test_not_a_reddit_page_is_refused():
    assert parse_reddit("Just some notes\nabout nothing\n", CAPTURED) is None


@pytest.fixture
def blank(tmp_path):
    main(["new", "paste-test", "--subject", "Quillnote", "--type", "product", "--root", str(tmp_path)])
    return tmp_path / "paste-test"


def test_paste_writes_a_capture_that_verifies(blank, no_ocr):
    rep = paste(blank, LINK_POST, captured=CAPTURED, search_term="quillnote price")
    assert rep["name"] == "quillnote-to-raise-prices-again" and rep["posts"] == 5 and rep["quotes_removed"] == 1
    cap = json.loads((blank / "raw" / "capture" / f"{rep['name']}.json").read_text())
    assert cap["site"] == "reddit.com/r/notetaking" and cap["search_query"] == "quillnote price"
    opening, *replies = cap["posts"]
    # a link post's opening is its title, credited to whoever carries the OP badge, dated to the earliest comment
    assert opening == {"id": "p1", "author": "maple_owl", "date": "2026-06-30", "date_approx": True, "parent": None,
                       "score": 12, "text": "Quillnote to raise prices again"}
    # the quoted paragraph is left out, and the quoted post becomes the parent
    assert replies[2]["parent"] == "p3"
    assert replies[2]["text"] == "It is only slow for big archives, mine with a few hundred notes is fine."
    SELF = paste(blank, SELF_POST, captured=CAPTURED)
    assert json.loads((blank / "raw" / "capture" / f"{SELF['name']}.json").read_text())["posts"][0]["text"] == \
        "Since the update my phone and laptop disagree about which notes exist."
    ingest(blank)
    rep = verify(blank)
    assert rep["ok"] and set(rep["counts"]) <= {"exact", "normalised"}


def test_the_same_name_needs_replace_and_keeps_the_old_paste(blank):
    paste(blank, LINK_POST, captured=CAPTURED)
    with pytest.raises(InputError, match="already exists"):
        paste(blank, LINK_POST, captured=CAPTURED)
    rep = paste(blank, LINK_POST, captured=CAPTURED, replace=True)
    assert rep["replaced"] and (blank / rep["replaced"]).exists()
    assert len(list((blank / "raw" / "replaced").iterdir())) == 2  # the paste and its capture


def test_cli_reports_what_was_skipped_and_collapsed(blank, tmp_path, capsys):
    src = tmp_path / "page.txt"
    src.write_text(LINK_POST)
    assert main(["paste", str(blank), str(src), "--captured", "2026-09-28"]) == 0
    out = capsys.readouterr().out
    assert "5 posts" in out and "2 more replies" in out and "Next: crp ingest" in out
