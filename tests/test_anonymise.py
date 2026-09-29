import json
import os
import stat
from collections import Counter

from conftest import FIXTURE_SECRETS, read_jsonl
from crp.anonymise import anonymise, load_or_create_salt, person_code, strip_mentions
from crp.cli import main
from crp.ingest import ingest
from crp.verify import verify


def prepared(study):
    ingest(study)
    verify(study)
    return study


def test_same_name_always_gets_the_same_code(study, no_ocr, tmp_path):
    salt = load_or_create_salt(tmp_path / "s")
    assert person_code(salt, "maria_k") == person_code(salt, "maria_k") != person_code(salt, "maria_K")
    anonymise(prepared(study), FIXTURE_SECRETS)
    first = (study / "posts.jsonl").read_bytes()
    anonymise(study, FIXTURE_SECRETS)
    assert (study / "posts.jsonl").read_bytes() == first
    posts = read_jsonl(study / "posts.jsonl")
    ingested = read_jsonl(study / "raw" / "ingested.jsonl")
    codes = {}
    for i, p in zip(ingested, posts):
        if i["author"]:
            assert codes.setdefault(i["author"], p["person_code"]) == p["person_code"]
    assert len(set(codes.values())) == len(codes)  # different names, different codes
    # maria_k posts in a pasted thread and a screenshot thread: one person
    assert Counter(p["thread_id"] for i, p in zip(ingested, posts) if i["author"] == "maria_k") == {"T01": 1, "T04": 1}


def test_unnamed_posts_each_count_as_one_person(tmp_path, no_ocr):
    raw = tmp_path / "raw" / "capture"
    raw.mkdir(parents=True)
    (tmp_path / "raw" / "page.txt").write_text("First post here\nA reply without a name\nAnother one")
    (raw / "a.json").write_text('{"source_file": "page.txt", "posts": ['
                                '{"id": "p1", "author": "op", "text": "First post here"},'
                                '{"id": "p2", "author": null, "text": "A reply without a name", "parent": "p1"},'
                                '{"id": "p3", "author": null, "text": "Another one", "parent": "p1"}]}')
    ingest(tmp_path)
    verify(tmp_path)
    assert anonymise(tmp_path, tmp_path / ".secrets")["forum_people"] == 3


def test_interview_speakers_get_codes(study, no_ocr):
    anonymise(prepared(study), FIXTURE_SECRETS)
    text = (study / "posts.jsonl").read_text()
    assert '"Ana"' not in text and '"Dev"' not in text and '"author"' not in text
    turns = [p for p in read_jsonl(study / "posts.jsonl") if p["thread_id"] == "I01"]
    assert len({p["person_code"] for p in turns}) == 2


def test_mentions_are_stripped():
    assert strip_mentions("@maria_k agreed, and u/night_owl said so too. Mail me@example.com") == \
        "@[user] agreed, and u/[user] said so too. Mail me@example.com"


def test_salt_is_private_and_reused(tmp_path):
    salt = load_or_create_salt(tmp_path / ".secrets")
    path = tmp_path / ".secrets" / "salt"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / ".secrets").st_mode) == 0o700
    assert load_or_create_salt(tmp_path / ".secrets") == salt and len(salt) == 32


def test_salt_never_appears_in_any_output_or_log(study, no_ocr, capsys):
    project = study.parents[1]
    for cmd in ("ingest", "verify", "anonymise", "signals"):
        assert main([cmd, str(study)]) == 0
    salt_hex = (project / ".secrets" / "salt").read_text().strip()
    salt = bytes.fromhex(salt_hex)
    logs = capsys.readouterr()
    assert salt_hex not in logs.out + logs.err
    for f in project.rglob("*"):
        if f.is_file() and ".secrets" not in f.parts:
            data = f.read_bytes()
            assert salt_hex.encode() not in data and salt not in data, f
    manifest = (study / "results" / "run_manifest.json").read_text()
    assert '"salt_fingerprint"' in manifest


def test_bare_names_in_post_text_are_replaced():
    """D38, from ux-t: an author's name written without u/ or @ is replaced too, as a whole word, exact case."""
    from crp.anonymise import name_pattern
    pat = name_pattern({"maple_owl", "Ana", "Jo", None})
    assert pat.sub("[user]", "As maple_owl said, Ana was right.") == "As [user] said, [user] was right."
    assert pat.sub("[user]", "maple_owls and Anatomy and u/maple_owl-x stay") == "maple_owls and Anatomy and u/maple_owl-x stay"
    assert pat.sub("[user]", "Jo agreed, ana too") == "Jo agreed, ana too"  # under three characters, or another case
    assert name_pattern({None, "Jo"}) is None


def test_anonymise_counts_replaced_names(tmp_path, no_ocr):
    from test_paste import CAPTURED, LINK_POST
    from crp.cli import main
    from crp.ingest import ingest
    from crp.paste import paste
    from crp.verify import verify
    main(["new", "names", "--subject", "Quillnote", "--type", "product", "--root", str(tmp_path)])
    d = tmp_path / "names"
    paste(d, LINK_POST.replace("feels like a joke.\n\n5", "feels like a joke, as maple_owl says.\n\n5"), captured=CAPTURED)
    ingest(d)
    verify(d)
    rep = anonymise(d, tmp_path / "secrets")
    assert rep["names_in_text_replaced"] == 1
    assert any("as [user] says" in json.loads(line)["text"] for line in (d / "posts.jsonl").read_text().splitlines())
