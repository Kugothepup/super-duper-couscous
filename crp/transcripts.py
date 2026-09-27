"""Interview transcripts (raw/interviews/), ported from parse_transcripts.py.

Supports .txt / .md / .docx (speaker-labelled lines, with or without timestamps, including
Otter-style "Name  0:03" header lines) and .vtt / .srt caption files (Zoom, Teams, Meet;
<v Name> tags or "Name: text" cues). The interviewer is taken from --interviewer, from
speaker labels, or guessed as the speaker who asks the most questions: check it.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from crp.captures import Thread
from crp.io import InputError
from crp.text import clean_quotes

SUPPORTED = {".txt", ".md", ".vtt", ".srt", ".docx"}
TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"

PAT_TS_FIRST = re.compile(rf"^[\[(]?({TS})[\])]?\s*[-–—]?\s*([^:]{{1,40}}?)\s*:\s*(.*)$")
PAT_SPK_TS = re.compile(rf"^([^:\[\]()]{{1,40}}?)\s*[\[(]?({TS})[\])]?\s*:\s*(.*)$")
PAT_HEADER = re.compile(rf"^(.{{1,40}}?)\s+[\[(]?({TS})[\])]?\s*$")
PAT_SPK = re.compile(r"^([^:]{1,40}?)\s*:\s*(.*)$")
SPEAKER_OK = re.compile(r"^[^\W_][\w .'\-()#]{0,39}$")

INTERVIEWER_WORDS = ("interviewer", "moderator", "researcher", "facilitator", "host")
PARTICIPANT_WORDS = ("participant", "respondent", "interviewee", "user", "customer")
UNKNOWN = "UNKNOWN"


def ts_to_sec(s: str | None) -> float | None:
    if not s:
        return None
    try:
        parts = [float(p) for p in s.replace(",", ".").split(":")]
    except ValueError:
        return None
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return round(sec, 3)


def valid_speaker(name: str | None) -> bool:
    name = (name or "").strip()
    return bool(name and SPEAKER_OK.match(name) and len(name.split()) <= 4 and re.search(r"[^\W\d_]", name))


def match_line(line: str) -> tuple[str, str | None, str] | None:
    """(speaker, timestamp, text) if the line opens a speaker turn."""
    s = line.strip()
    if not s:
        return None
    for pat, spk_i, ts_i, txt_i in ((PAT_TS_FIRST, 2, 1, 3), (PAT_SPK_TS, 1, 2, 3),
                                     (PAT_HEADER, 1, 2, None), (PAT_SPK, 1, None, 2)):
        m = pat.match(s)
        if m and valid_speaker(m.group(spk_i)):
            return (m.group(spk_i).strip(), m.group(ts_i) if ts_i else None, m.group(txt_i) if txt_i else "")
    return None


def parse_text_lines(lines: list[str]) -> list[dict]:
    matches = [match_line(ln) for ln in lines]
    counts = Counter(m[0] for m in matches if m)
    # a "speaker" seen only once among many candidates is probably prose with a colon
    accepted = set(counts) if len(counts) <= 3 else {s for s, c in counts.items() if c >= 2}
    segs: list[dict] = []
    for ln, m in zip(lines, matches):
        if m and m[0] in accepted:
            segs.append({"speaker": m[0], "start": ts_to_sec(m[1]), "end": None, "text": m[2].strip()})
        elif ln.strip():
            if not segs:
                segs.append({"speaker": UNKNOWN, "start": None, "end": None, "text": ""})
            segs[-1]["text"] += " " + ln.strip()
    return segs


def parse_cues(text: str) -> list[dict]:
    segs = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        ti = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ti is None:
            continue
        m = re.match(rf"\s*({TS})\s*-->\s*({TS})", lines[ti])
        start, end = (ts_to_sec(m.group(1)), ts_to_sec(m.group(2))) if m else (None, None)
        body = " ".join(lines[ti + 1:])
        spk = None
        mv = re.match(r"\s*<v(?:\.[^ >]*)?\s+([^>]+)>(.*)", body)
        if mv:
            spk, body = mv.group(1).strip(), mv.group(2)
        else:
            ms = PAT_SPK.match(body)
            if ms and valid_speaker(ms.group(1)):
                spk, body = ms.group(1).strip(), ms.group(2)
        body = re.sub(r"<[^>]+>", "", body).strip()
        if body:
            segs.append({"speaker": spk, "start": start, "end": end, "text": body})
    return segs


def read_docx_lines(path: Path) -> list[str]:
    import docx  # python-docx
    return [p.text for p in docx.Document(str(path)).paragraphs]


def merge_segments(segs: list[dict]) -> list[dict]:
    turns: list[dict] = []
    prev = UNKNOWN
    for s in segs:
        spk = s["speaker"] or prev
        text = re.sub(r"\s+", " ", clean_quotes(s["text"])).strip()
        if turns and turns[-1]["speaker"] == spk:
            turns[-1]["text"] = (turns[-1]["text"] + " " + text).strip()
            if s["end"] is not None:
                turns[-1]["end"] = s["end"]
        elif text:
            turns.append({"speaker": spk, "start": s["start"], "end": s["end"], "text": text})
        prev = spk
    return turns


def guess_roles(turns: list[dict], interviewer_names: str | None) -> tuple[dict[str, str], str]:
    roles, method = _guess_roles([t for t in turns if t["speaker"] != UNKNOWN], interviewer_names)
    if any(t["speaker"] == UNKNOWN for t in turns):
        roles[UNKNOWN] = "unknown"
    return roles, method


def _guess_roles(turns: list[dict], interviewer_names: str | None) -> tuple[dict[str, str], str]:
    speakers = list(dict.fromkeys(t["speaker"] for t in turns))
    if not speakers:
        return {}, "no speakers"
    if interviewer_names:
        names = [n.strip().lower() for n in interviewer_names.split(",") if n.strip()]
        roles = {s: "interviewer" if any(n in s.lower() for n in names) else "participant" for s in speakers}
        if "interviewer" in roles.values():
            return roles, "--interviewer flag"
        # no name matched in this transcript: fall through to auto-detection
    kw = {}
    for s in speakers:
        low = s.lower()
        if any(w in low for w in INTERVIEWER_WORDS) or re.fullmatch(r"(int|mod|r)\d*", low):
            kw[s] = "interviewer"
        elif any(w in low for w in PARTICIPANT_WORDS) or re.fullmatch(r"p\d+", low):
            kw[s] = "participant"
    if "interviewer" in kw.values():
        return {s: kw.get(s, "participant") for s in speakers}, "speaker labels"
    if len(speakers) == 1:
        return {speakers[0]: "participant"}, "single speaker (check!)"
    stats = {}
    for s in speakers:
        ts = [t for t in turns if t["speaker"] == s]
        q = sum("?" in t["text"] for t in ts) / len(ts)
        words = sum(len(t["text"].split()) for t in ts) / len(ts)
        stats[s] = (q, -words, len(ts))
    eligible = [s for s in speakers if stats[s][2] >= 2] or speakers
    interviewer = max(eligible, key=lambda s: stats[s][:2])
    return ({s: ("interviewer" if s == interviewer else "participant") for s in speakers},
            "question-ratio heuristic (check!)")


def read_interviews(folder: Path, interviewer_names: str | None = None) -> tuple[list[Thread], dict]:
    files = sorted({f for f in folder.rglob("*") if f.suffix.lower() in SUPPORTED}, key=lambda f: f.name.lower()) \
        if folder.is_dir() else []
    threads, details = [], []
    for f in files:
        suf = f.suffix.lower()
        if suf in (".vtt", ".srt"):
            segs = parse_cues(f.read_text(encoding="utf-8", errors="replace"))
        elif suf == ".docx":
            try:
                segs = parse_text_lines(read_docx_lines(f))
            except ImportError:
                raise InputError(f"{f.name}: reading .docx needs python-docx") from None
        else:
            segs = parse_text_lines(f.read_text(encoding="utf-8", errors="replace").splitlines())
        turns = merge_segments(segs)
        roles, method = guess_roles(turns, interviewer_names)
        rel = str(f.relative_to(folder.parent))
        th = Thread(key=f.name, source="interview", source_file=rel, capture_method="transcript",
                    title=None, search_term=None)
        for i, t in enumerate(turns, 1):
            th.turns.append({"turn": i, "parent_turn": None, "kind": "turn",
                             "author": None if t["speaker"] == UNKNOWN else t["speaker"],
                             "role": roles.get(t["speaker"], "unknown"), "timestamp": None, "date_approx": False,
                             "score": None, "promotional": False, "start_s": t["start"], "end_s": t["end"],
                             "text": t["text"], "ref": f"{rel}#t{i:02d}"})
        warnings = []
        if len([r for r in roles.values() if r != "unknown"]) < 2:
            warnings.append("only one speaker detected: check the transcript has speaker labels")
        if UNKNOWN in roles:
            warnings.append("text before the first speaker label is stored with role 'unknown'")
        details.append({"file": rel, "speakers": {s: r for s, r in roles.items() if s != UNKNOWN},
                        "role_method": method, "warnings": warnings})
        threads.append(th)
    return threads, {"interview_files": len(files), "interviews": details}
