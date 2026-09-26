#!/usr/bin/env python3
"""Parse interview transcripts into normalised speaker turns.

Supports .txt / .md / .docx (speaker-labelled lines, with or without timestamps,
including Otter-style "Name  0:03" header lines) and .vtt / .srt caption files
(Zoom, Teams, Meet exports; <v Name> tags or "Name: text" cues).

Usage:
  python parse_transcripts.py INPUT [INPUT ...] --work WORKDIR [--interviewer "Ana,Moderator"]

INPUT may be files or folders. Transcripts get anonymous ids (T01, T02, ...) in
sorted filename order; the mapping to source files is kept in manifest.json.
Writes WORKDIR/turns/Txx.json and WORKDIR/manifest.json.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import clean_quotes, save_json  # noqa: E402

SUPPORTED = {".txt", ".md", ".vtt", ".srt", ".docx"}
TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"

PAT_TS_FIRST = re.compile(rf"^[\[(]?({TS})[\])]?\s*[-\u2013\u2014]?\s*([^:]{{1,40}}?)\s*:\s*(.*)$")
PAT_SPK_TS = re.compile(rf"^([^:\[\]()]{{1,40}}?)\s*[\[(]?({TS})[\])]?\s*:\s*(.*)$")
PAT_HEADER = re.compile(rf"^(.{{1,40}}?)\s+[\[(]?({TS})[\])]?\s*$")
PAT_SPK = re.compile(r"^([^:]{1,40}?)\s*:\s*(.*)$")
SPEAKER_OK = re.compile(r"^[^\W_][\w .'\-()#]{0,39}$")

INTERVIEWER_WORDS = ("interviewer", "moderator", "researcher", "facilitator", "host")
PARTICIPANT_WORDS = ("participant", "respondent", "interviewee", "user", "customer")


def ts_to_sec(s):
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


def valid_speaker(name):
    name = (name or "").strip()
    return bool(name and SPEAKER_OK.match(name) and len(name.split()) <= 4
                and re.search(r"[^\W\d_]", name))


def match_line(line):
    """Return (speaker, timestamp, text) if the line opens a speaker turn."""
    s = line.strip()
    if not s:
        return None
    for pat, spk_i, ts_i, txt_i in ((PAT_TS_FIRST, 2, 1, 3), (PAT_SPK_TS, 1, 2, 3),
                                     (PAT_HEADER, 1, 2, None), (PAT_SPK, 1, None, 2)):
        m = pat.match(s)
        if m and valid_speaker(m.group(spk_i)):
            return (m.group(spk_i).strip(),
                    m.group(ts_i) if ts_i else None,
                    m.group(txt_i) if txt_i else "")
    return None


def parse_text_lines(lines):
    matches = [match_line(ln) for ln in lines]
    counts = Counter(m[0] for m in matches if m)
    # A "speaker" seen only once among many candidates is probably prose with a colon.
    accepted = set(counts) if len(counts) <= 3 else {s for s, c in counts.items() if c >= 2}
    segs = []
    for ln, m in zip(lines, matches):
        if m and m[0] in accepted:
            segs.append({"speaker": m[0], "start": ts_to_sec(m[1]), "end": None, "text": m[2].strip()})
        elif ln.strip():
            if not segs:
                segs.append({"speaker": "UNKNOWN", "start": None, "end": None, "text": ""})
            segs[-1]["text"] += " " + ln.strip()
    return segs


def parse_cues(text):
    segs = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.split("\n") if l.strip()]
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
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


def read_docx_lines(path):
    try:
        import docx  # python-docx
    except ImportError:
        raise SystemExit("Reading .docx needs python-docx: pip install python-docx")
    return [p.text for p in docx.Document(str(path)).paragraphs]


def merge_segments(segs):
    turns = []
    prev = "UNKNOWN"
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
    for i, t in enumerate(turns, 1):
        t["turn_id"] = i
    return turns


def guess_roles(turns, interviewer_names):
    roles, method = _guess_roles([t for t in turns if t["speaker"] != "UNKNOWN"], interviewer_names)
    if any(t["speaker"] == "UNKNOWN" for t in turns):
        roles["UNKNOWN"] = "unknown"
    return roles, method


def _guess_roles(turns, interviewer_names):
    speakers = list(dict.fromkeys(t["speaker"] for t in turns))
    if not speakers:
        return {}, "no speakers"
    roles = {}
    if interviewer_names:
        names = [n.strip().lower() for n in interviewer_names.split(",") if n.strip()]
        for s in speakers:
            roles[s] = "interviewer" if any(n in s.lower() for n in names) else "participant"
        if "interviewer" in roles.values():
            return roles, "--interviewer flag"
        roles = {}  # no name matched in this transcript: fall through to auto-detection
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


def collect_inputs(inputs):
    files = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            files += [f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED]
        elif p.suffix.lower() in SUPPORTED:
            files.append(p)
        else:
            print(f"skip (unsupported): {p}", file=sys.stderr)
    return sorted(set(files), key=lambda f: f.name.lower())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--work", required=True, help="working folder for all pipeline outputs")
    ap.add_argument("--interviewer", help="comma-separated interviewer name fragments")
    args = ap.parse_args()

    files = collect_inputs(args.inputs)
    if not files:
        raise SystemExit("No supported transcript files found.")
    work = Path(args.work)
    manifest = []
    for i, f in enumerate(files, 1):
        tid = f"T{i:02d}"
        suf = f.suffix.lower()
        if suf in (".vtt", ".srt"):
            segs = parse_cues(f.read_text(encoding="utf-8", errors="replace"))
        elif suf == ".docx":
            segs = parse_text_lines(read_docx_lines(f))
        else:
            segs = parse_text_lines(f.read_text(encoding="utf-8", errors="replace").splitlines())
        turns = merge_segments(segs)
        roles, method = guess_roles(turns, args.interviewer)
        for t in turns:
            t["role"] = roles.get(t["speaker"], "unknown")
        warnings = []
        if len(roles) < 2:
            warnings.append("only one speaker detected - check the transcript has speaker labels")
        if "UNKNOWN" in roles:
            warnings.append("text before first speaker label stored as UNKNOWN")
        p_words = sum(len(t["text"].split()) for t in turns if t["role"] == "participant")
        doc = {
            "transcript_id": tid,
            "source_file": f.name,
            "speakers": roles,
            "role_method": method,
            "has_timestamps": any(t["start"] is not None for t in turns),
            "has_end_times": any(t["end"] is not None for t in turns),
            "participant_words": p_words,
            "turns": [{k: t[k] for k in ("turn_id", "speaker", "role", "start", "end", "text")} for t in turns],
        }
        save_json(doc, work / "turns" / f"{tid}.json")
        manifest.append({"transcript_id": tid, "source_file": f.name, "n_turns": len(turns),
                         "speakers": roles, "role_method": method,
                         "participant_words": p_words, "warnings": warnings})
    save_json(manifest, work / "manifest.json")

    print(f"Parsed {len(manifest)} transcript(s) into {work}/turns\n")
    for m in manifest:
        sp = ", ".join(f"{s}={r[0].upper()}" for s, r in m["speakers"].items())
        print(f"{m['transcript_id']}  {m['source_file']}  turns={m['n_turns']}  "
              f"participant_words={m['participant_words']}  [{sp}]  via {m['role_method']}")
        for w in m["warnings"]:
            print(f"     ! {w}")
    print("\nCheck the I/P roles above. If wrong, re-run with --interviewer \"Name1,Name2\".")


if __name__ == "__main__":
    main()
