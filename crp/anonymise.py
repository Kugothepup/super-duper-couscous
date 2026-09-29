"""crp anonymise: raw/ingested.jsonl -> posts.jsonl, with every name replaced by a person code.

A person code is "P-" + the first 8 hex characters of HMAC-SHA256(salt, name). The same name
always gets the same code, and the code can't be turned back into the name without the salt.
The salt is 32 random bytes in .secrets/salt at the project root, created on first run. It is
never printed, logged or written anywhere else; the run manifest holds only a fingerprint.
Posts with no name shown each count as their own person (as in the skill).
Interview speakers, interviewer included, get codes the same way (D17).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

from crp import manifest
from crp.io import InputError, read_jsonl, sha256_file, validate, write_jsonl
from crp.ingest import INGESTED
from crp.schemas import IngestedPost, Post
from crp.verify import REPORT as VERIFY_REPORT

POSTS = Path("posts.jsonl")
MENTION = re.compile(r"(?<![\w@./])@[A-Za-z0-9_](?:[A-Za-z0-9_.-]*[A-Za-z0-9_])?")
REDDIT_MENTION = re.compile(r"(?<![\w/])/?u/[A-Za-z0-9_-]+")
MIN_NAME = 3


def default_secrets_dir(study_dir: Path) -> Path:
    """studies/<id>/ -> <project>/.secrets/"""
    return Path(study_dir).resolve().parents[1] / ".secrets"


def load_or_create_salt(secrets_dir: Path) -> bytes:
    path = Path(secrets_dir) / "salt"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", text):
            raise InputError(f"{path} isn't a salt this tool wrote (expected 64 hex characters).")
        return bytes.fromhex(text)
    Path(secrets_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return bytes.fromhex(value)


def person_code(salt: bytes, name: str) -> str:
    return "P-" + hmac.new(salt, name.encode("utf-8"), hashlib.sha256).hexdigest()[:8]


def fingerprint(salt: bytes) -> str:
    """Tells salts apart in the manifest without revealing them."""
    return hashlib.sha256(b"crp salt fingerprint\0" + salt).hexdigest()[:12]


def strip_mentions(text: str) -> str:
    return REDDIT_MENTION.sub("u/[user]", MENTION.sub("@[user]", text))


def name_pattern(names: set[str | None]) -> re.Pattern | None:
    """Any author's name written in a post without u/ or @ (D38, from ux-t): exact case, as a whole word, and
    at least MIN_NAME characters so a short name doesn't catch ordinary words."""
    usable = sorted((n for n in names if n and len(n) >= MIN_NAME), key=len, reverse=True)
    if not usable:
        return None
    return re.compile(r"(?<![\w/@-])(?:" + "|".join(map(re.escape, usable)) + r")(?![\w-])")


def check_verified(study_dir: Path) -> None:
    ingested = study_dir / INGESTED
    report_path = study_dir / VERIFY_REPORT
    if not report_path.exists():
        raise InputError("Run crp verify first: transcriptions must be checked before anything is anonymised.")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("ingested_sha256") != sha256_file(ingested):
        raise InputError("raw/ingested.jsonl has changed since crp verify ran. Run crp verify again.")
    if not report.get("ok"):
        c = report.get("counts", {})
        raise InputError(f"crp verify found {c.get('failed', 0)} failed and {c.get('tidied', 0)} tidied "
                         "transcription(s). Fix the capture files (copy the text exactly; don't tidy wording), "
                         "then re-run crp ingest and crp verify.")


def anonymise(study_dir: Path, secrets_dir: Path | None = None) -> dict:
    study_dir = Path(study_dir)
    ingested = study_dir / INGESTED
    if not ingested.exists():
        raise InputError(f"No {ingested}. Run crp ingest first.")
    check_verified(study_dir)
    salt = load_or_create_salt(secrets_dir or default_secrets_dir(study_dir))
    rows = read_jsonl(ingested, IngestedPost)
    with manifest.stage(study_dir, "anonymise", inputs=[ingested, study_dir / VERIFY_REPORT]) as record:
        code_of: dict[str, str] = {}
        posts = []
        names = name_pattern({r.author for r in rows})
        redacted = 0
        for r in rows:
            key = r.author if r.author is not None else f"\0unnamed\0{r.post_id}"
            code = person_code(salt, key)
            if code_of.setdefault(code, key) != key:
                raise InputError("Two different people got the same person code, which is very rare. The salt "
                                 "needs replacing (every person code will change) before this study can continue.")
            text = strip_mentions(r.text)
            if names:
                text, n = names.subn("[user]", text)
                redacted += n
            data = r.model_dump(exclude={"author"}) | {"person_code": code, "text": text}
            posts.append(validate(Post, data, r.post_id))
        write_jsonl(study_dir / POSTS, posts)
        people = {src: len({p.person_code for p in posts if p.role == "participant" and p.source_type == src})
                  for src in ("forum", "interview")}
        record["salt_fingerprint"] = fingerprint(salt)
        record["names_in_text_replaced"] = redacted
        record["outputs"] = [str(POSTS)]
    return {"posts": len(posts), "forum_people": people["forum"], "interview_participants": people["interview"],
            "names_in_text_replaced": redacted}
