"""crp batch: blinded batch files for the blind-coder agent.

Each batches/batch_NNN.jsonl starts with a header (the frozen codebook's variables for that
sample, its instructions and the output format), then one line per item holding only
item_id, text and, if the codebook asks for context, parent_text: the post a comment replies to,
or the interviewer's question before an interview turn. No names, person codes, thread titles,
sources, dates, scores, signal flags, study questions or hypotheses.

Measurement batches code the measurement sample (the codebook's measurement variables); detail
batches code the detail selection (its detail variables) (D10). Items are shuffled with the seed
(default: the sample's) and given opaque ids, m0001 or d0001, so neither the id nor the order
reveals the thread. batches/index.json maps each item id to its post; the coder never needs it.

Reuse across rounds (D35): after crp round, an item the coder would see exactly as before (same sample,
same frozen codebook, same text and parent text) takes its label from the last round instead of going to
the coder again. Those items go in batches/reused_<sample>.jsonl, a batch file written by code for the
record (never given to the coder), with ids rm0001 or rd0001, and their labels in labels/reused_<sample>.
labels.jsonl. crp labels lock refuses to mix them with labels from a different coder model.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from crp import manifest
from crp.anonymise import POSTS
from crp.codebook import CODEBOOK, frozen
from crp.io import InputError, atomic_write_text, read_jsonl
from crp.sample import DETAIL, MEASUREMENT, SUMMARY, last_round, load_detail, load_measurement
from crp.schemas import Codebook, Post, Variable

BATCHES = Path("batches")
INDEX = BATCHES / "index.json"
LABELS = Path("labels")
LABELS_LOCK = Path("labels.lock")
ITEM_FIELDS = ("item_id", "text", "parent_text")  # the only fields an item line may hold
HEADER_FIELDS = ("record", "batch", "items", "codebook_version", "instructions", "codebook", "output_format")
VARIABLE_FIELDS = ("name", "description", "kind", "values", "definitions", "nullable", "required_when")
BATCH_SIZE = 40  # triage.py's batch size
PREFIX = {"measurement": "m", "detail": "d"}
REUSED = "reused_"  # batch-name prefix for items whose labels come from the last round


def labels_file(batch: str) -> Path:
    return LABELS / f"{batch}.labels.jsonl"


def shown(value: object) -> str:
    return json.dumps(value)


def coder_codebook(codebook: Codebook, variables: list[Variable]) -> dict:
    """The parts of the codebook the coder needs, and nothing else."""
    out: dict = {}
    if any(v.kind == "per_aspect" or v.name == "aspect" for v in variables):
        out["aspects"] = {a: codebook.aspect_definitions.get(a, "") for a in codebook.aspects}
    out["variables"] = []
    for v in variables:
        d = {"name": v.name, "description": v.description, "kind": v.kind, "values": v.values}
        if v.definitions:
            d["definitions"] = v.definitions
        if v.nullable:
            d["nullable"] = True
        if v.required_when:
            d["required_when"] = v.required_when
        out["variables"].append(d)
    return out


def output_format(variables: list[Variable]) -> dict:
    line: dict = {}
    rules = ["JSON Lines: one object per item, one line each, in the order the items are given.",
             "Write values exactly as listed: numbers as numbers, true and false unquoted, text in quotes.",
             "rationale: 15 words or fewer, saying what in the text decided the codes."]
    for v in variables:
        allowed = shown(v.values)
        if v.kind == "per_aspect":
            line[v.name] = {"<aspect>": f"one of {allowed}"}
            rules.append(f"{v.name}: one entry per aspect the text evaluates, using only the listed aspects; "
                         "{} if it evaluates none.")
        elif v.required_when:
            line[v.name] = f"one of {allowed}, or null"
            rules.append(f"{v.name}: required when {v.required_when} is true; null when {v.required_when} is false.")
        elif v.nullable:
            line[v.name] = f"one of {allowed}, or null"
            rules.append(f"{v.name}: null when the text expresses none.")
        else:
            line[v.name] = f"one of {allowed}"
    return {"line": {"item_id": "<the item's item_id>", "values": line, "rationale": "<15 words or fewer>"},
            "rules": rules}


def context(post: Post, posts: dict[str, Post], previous: dict[str, Post]) -> str | None:
    if post.source_type == "forum":
        parent = posts.get(post.parent_id) if post.parent_id else None
        return parent.text if parent else None
    before = previous.get(post.post_id)
    return before.text if before is not None and before.role == "interviewer" else None


def item_key(sample: str, codebook_sha: str, item: dict) -> str:
    """What the coder saw for an item, as a hash: two items with the same key would get the same labels."""
    seen = [sample, codebook_sha, item["text"], item.get("parent_text")]
    return hashlib.sha256(json.dumps(seen, ensure_ascii=False).encode("utf-8")).hexdigest()


def reusable(study_dir: Path, codebook_sha: str) -> tuple[dict[str, dict], dict | None]:
    """{item key: label values} from the last round's locked labels, and where they came from."""
    prev = last_round(study_dir)
    if prev is None or not (prev / LABELS_LOCK).exists():
        return {}, None
    lock = json.loads((prev / LABELS_LOCK).read_text(encoding="utf-8"))
    if lock["codebook_sha256"] != codebook_sha:
        return {}, None
    index = json.loads((prev / INDEX).read_text(encoding="utf-8"))
    out = {}
    for entry in index["batches"]:
        lines = (prev / BATCHES / f"{entry['batch']}.jsonl").read_text(encoding="utf-8").splitlines()[1:]
        items = {json.loads(line)["item_id"]: json.loads(line) for line in lines}
        for line in (prev / labels_file(entry["batch"])).read_text(encoding="utf-8").splitlines():
            if line.strip():
                lab = json.loads(line)
                out[item_key(entry["sample"], codebook_sha, items[lab["item_id"]])] = lab["values"]
    return out, {"from": str(prev.relative_to(study_dir)), "coder_model": lock["coder_model"]}


def build(study_dir: Path, size: int, seed: int, reuse: bool = True) -> tuple[dict[str, str], dict, dict[str, str]]:
    """The batch files' text by name, the index, and the reused labels' text by batch name. Nothing is written."""
    codebook, lock = frozen(study_dir)
    earlier, source = reusable(study_dir, lock["sha256"]) if reuse else ({}, None)
    groups = {"measurement": load_measurement(study_dir), "detail": [p for _, p in load_detail(study_dir)]}
    all_posts = read_jsonl(study_dir / POSTS, Post)
    posts = {p.post_id: p for p in all_posts}
    previous = {b.post_id: a for a, b in zip(all_posts, all_posts[1:]) if a.thread_id == b.thread_id}
    rng = random.Random(seed)
    files: dict[str, str] = {}
    reused_labels: dict[str, str] = {}
    index = {"codebook_version": codebook.version, "codebook_sha256": lock["sha256"], "seed": seed, "batch_size": size,
             "batches": []}

    def line_for(item_id: str, p: Post) -> dict:
        item = {"item_id": item_id, "text": p.text}
        parent = context(p, posts, previous) if codebook.parent_context else None
        if parent is not None:
            item["parent_text"] = parent
        return item

    def add(name: str, sample: str, variables: list[Variable], head: dict, ids: list[str], chunk: list[Post],
            extra: dict | None = None) -> None:
        lines = [{"record": "header", "batch": name, "items": len(chunk)} | head | (extra or {})]
        lines += [line_for(i, p) for i, p in zip(ids, chunk)]
        files[name] = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
        entry = {"batch": name, "sample": sample, "variables": [v.name for v in variables],
                 "sha256": hashlib.sha256(files[name].encode("utf-8")).hexdigest(),
                 "items": [{"item_id": i, "post_id": p.post_id} for i, p in zip(ids, chunk)]}
        index["batches"].append(entry)

    for sample, items in groups.items():
        if not items:
            continue
        variables = [v for v in codebook.variables if v.applies_to == sample]
        if not variables:
            raise InputError(f"The {sample} sample has {len(items)} posts, but the codebook has no variables "
                             f"with applies_to: {sample}.")
        head = {"codebook_version": codebook.version, "instructions": codebook.instructions_for(sample),
                "codebook": coder_codebook(codebook, variables), "output_format": output_format(variables)}
        keys = {p.post_id: item_key(sample, lock["sha256"], line_for("", p)) for p in items}
        old = [p for p in items if keys[p.post_id] in earlier]
        new = [p for p in items if keys[p.post_id] not in earlier]
        order = rng.sample(new, len(new))
        for start in range(0, len(order), size):
            chunk = order[start:start + size]
            coded = sum(1 for b in index["batches"] if "reused" not in b)
            add(f"batch_{coded + 1:03d}", sample, variables, head,
                [f"{PREFIX[sample]}{start + i + 1:04d}" for i in range(len(chunk))], chunk)
        if old:
            name = f"{REUSED}{sample}"
            ids = [f"r{PREFIX[sample]}{i + 1:04d}" for i in range(len(old))]
            add(name, sample, variables, head, ids, old, {"reused": source})
            reused_labels[name] = "".join(json.dumps({"item_id": i, "values": earlier[keys[p.post_id]]},
                                                     ensure_ascii=False) + "\n" for i, p in zip(ids, old))
            index["batches"][-1]["reused"] = source | {
                "labels_sha256": hashlib.sha256(reused_labels[name].encode("utf-8")).hexdigest()}
    if reused_labels:
        index["reused_from"] = source["from"]
    return files, index, reused_labels


def make_batches(study_dir: Path, size: int = BATCH_SIZE, seed: int | None = None, reuse: bool = True) -> dict:
    study_dir = Path(study_dir)
    if (study_dir / LABELS_LOCK).exists():
        raise InputError("The labels are locked, so the batches can't change.")
    if size < 1:
        raise InputError(f"The batch size must be 1 or more (got {size}).")
    if seed is None:
        summary = study_dir / SUMMARY
        if not summary.exists():
            raise InputError("No samples yet. Run crp sample first.")
        seed = int(json.loads(summary.read_text(encoding="utf-8"))["seed"])
    files, index, reused_labels = build(study_dir, size, seed, reuse)
    index_text = json.dumps(index, indent=2, ensure_ascii=False) + "\n"
    batch_dir = study_dir / BATCHES
    old = {p.stem: p.read_text(encoding="utf-8") for p in sorted(batch_dir.glob("*.jsonl"))}
    unchanged = old == files and (study_dir / INDEX).exists() and (study_dir / INDEX).read_text(encoding="utf-8") == index_text
    labels_dir = study_dir / LABELS
    coded = [f for f in labels_dir.glob("*") if not f.name.startswith(REUSED)] if labels_dir.is_dir() else []
    if not unchanged and coded:
        raise InputError(f"{labels_dir} already holds labels for the current batches, and re-batching would change "
                         "them. Once coding starts, the batches are fixed.")
    inputs = [study_dir / CODEBOOK, study_dir / POSTS, study_dir / MEASUREMENT, study_dir / DETAIL]
    with manifest.stage(study_dir, "batch", inputs=inputs, seed=seed, codebook_version=index["codebook_version"]) as rec:
        if not unchanged:
            for name in old.keys() - files.keys():
                (batch_dir / f"{name}.jsonl").unlink()
            for f in labels_dir.glob(f"{REUSED}*") if labels_dir.is_dir() else []:
                f.unlink()
            for name, text in files.items():
                atomic_write_text(batch_dir / f"{name}.jsonl", text)
            for name, text in reused_labels.items():
                atomic_write_text(study_dir / labels_file(name), text)
            atomic_write_text(study_dir / INDEX, index_text)
        rec["outputs"] = [str(BATCHES / f"{n}.jsonl") for n in files] + [str(INDEX)] + \
            [str(labels_file(n)) for n in reused_labels]
        rec["settings"] = {"batch_size": size, "reuse": reuse}
        rec["reused_items"] = sum(len(b["items"]) for b in index["batches"] if "reused" in b)
        if index.get("reused_from"):
            rec["reused_from"] = index["reused_from"]
    return {"unchanged": unchanged, "seed": seed, "reused_from": index.get("reused_from"),
            "batches": [{"batch": b["batch"], "sample": b["sample"], "items": len(b["items"]),
                         "reused": "reused" in b} for b in index["batches"]]}


def read_index(study_dir: Path) -> dict:
    path = Path(study_dir) / INDEX
    if not path.exists():
        raise InputError("No batches yet. Run crp batch first.")
    return json.loads(path.read_text(encoding="utf-8"))
