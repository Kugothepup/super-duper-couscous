"""crp sample: draw the measurement sample and the detail selection from posts.jsonl.

Measurement sample (samples/measurement.jsonl): a random sample of forum posts. Every percentage
comes from it, and interviews never enter it (D14). The frame is triage.py's candidate pool:
participant posts, leaving out promotional posts, short "same here" echo replies and comments
under 8 words (opening posts are kept however short), and a link post's title, which is the article's
headline rather than anyone's view and stays only as context for the replies (D41). Then two caps:
  person cap (D9, D23)  at most 5 posts per person in the frame, opening posts included. A person
                        with more keeps a random 5.
  thread cap (D2, D22)  no thread supplies more than 10% of the sample drawn. The sample is the
                        largest size, up to 150, at which that can hold. Below 10 threads it can't,
                        and crp sample stops; --thread-cap-pct loosens the cap, and the run
                        manifest records it.
Posts are put in a random order and taken in that order, skipping any whose thread is at its cap,
until the sample is full. Each post's place comes from a hash of the seed, its person code and its
text (D35), not from shuffling the whole list, so it doesn't depend on which other posts are there:
when a later round adds threads, the posts already picked mostly stay picked. It is still a uniform
random order. The person cap keeps each person's first 5 posts in the same order.

Detail selection (samples/detail.jsonl): triage.py's purposive selection, made by code, with the
reasons for each pick. Within a budget of 200 forum posts: every opening post, then top-scored
comments (up to 20% of the budget), comments with signal flags (up to 40%), then the rest spread
across topic clusters, nearest the centre first. At most 5 comments per person; a person's own
opening posts are exempt. If the candidates fit in the budget, all are kept. Interviews are read
in full, as in the skill, so every participant turn goes in with the reason "interview".
Detail posts are never used for percentages: load_measurement() is the only way stats read a sample.
Posts named with crp topup (D37) join the detail selection with the reason given.

The seed is logged. Without --seed, a re-run reuses the last seed; a first run generates one.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from crp import manifest, thresholds
from crp.anonymise import POSTS
from crp.clusters import cluster_terms, embed, pick_k
from crp.io import InputError, atomic_write_text, read_jsonl, sha256_file, write_jsonl
from crp.schemas import DetailItem, MeasurementItem, Post
from crp.signals import SIGNALS, is_echo

ROUNDS = Path("rounds")
TOPUP = Path("topup.jsonl")  # posts added to the detail selection by hand, with a reason (D37)
MEASUREMENT = Path("samples") / "measurement.jsonl"
DETAIL = Path("samples") / "detail.jsonl"
SUMMARY = Path("samples") / "summary.json"
SIGNAL_FLAGS = {"constraint_language", "implicit_request", "workaround_language",
                "switching_language", "high_engagement", "hesitation_cluster"}


def last_round(study_dir: Path) -> Path | None:
    """The most recent closed round's folder, rounds/<n>/, if there is one (D35)."""
    folder = Path(study_dir) / ROUNDS
    done = sorted((d for d in folder.glob("*") if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name)) \
        if folder.is_dir() else []
    return done[-1] if done else None


def read_topup(study_dir: Path) -> list[dict]:
    path = Path(study_dir) / TOPUP
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if path.exists() else []


def ids_hash(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


# ---- the candidate pool (both samples) ---------------------------------------

def candidates(posts: list[Post], min_words: int = thresholds.MIN_WORDS) -> tuple[list[Post], Counter]:
    """triage.py's candidate pool, forum posts only, and how many forum posts each rule left out."""
    pool, left_out = [], Counter()
    for p in posts:
        if p.source_type != "forum":
            continue
        if p.role != "participant":
            left_out["removed_or_unknown"] += 1
        elif p.headline:
            left_out["headline"] += 1
        elif p.promotional:
            left_out["promotional"] += 1
        elif p.kind != "post" and is_echo(p.text):
            left_out["echo_reply"] += 1
        elif p.kind != "post" and len(p.text.split()) < min_words:
            left_out["short"] += 1
        else:
            pool.append(p)
    return pool, left_out


# ---- measurement sample ------------------------------------------------------

def draw_key(seed: int, post: Post) -> tuple[str, str]:
    """A post's place in the random order: a hash of the seed and the post itself (D35), then its id for ties."""
    h = hashlib.sha256(f"{seed}\0{post.person_code}\0{post.text}".encode("utf-8")).hexdigest()
    return h, post.post_id


def cap_people(frame: list[Post], cap: int, seed: int) -> tuple[list[Post], dict[str, int]]:
    """At most `cap` posts per person; a person with more keeps the first `cap` in the random order. Returns
    the capped frame in its original order, and {person code: posts before capping} for each person capped."""
    by_person: dict[str, list[Post]] = defaultdict(list)
    for p in frame:
        by_person[p.person_code].append(p)
    keep, capped = set(), {}
    for code in sorted(by_person):
        posts = by_person[code]
        if len(posts) > cap:
            capped[code] = len(posts)
            posts = sorted(posts, key=lambda p: draw_key(seed, p))[:cap]
        keep.update(p.post_id for p in posts)
    return [p for p in frame if p.post_id in keep], capped


def thread_cap_size(thread_sizes: list[int], target: int, pct: int) -> tuple[int, int]:
    """The largest sample size n, up to `target`, at which no thread need supply more than pct% of n.
    Returns (n, the most posts any one thread may supply), or (0, 0) if no size works."""
    for n in range(min(target, sum(thread_sizes)), 0, -1):
        cap = n * pct // 100
        if sum(min(s, cap) for s in thread_sizes) >= n:
            return n, cap
    return 0, 0


def draw(frame: list[Post], n: int, thread_cap: int, seed: int) -> list[Post]:
    """Take posts in the random order, skipping any whose thread is full, until n are taken."""
    taken: list[Post] = []
    per_thread: Counter = Counter()
    for p in sorted(frame, key=lambda p: draw_key(seed, p)):
        if len(taken) == n:
            break
        if per_thread[p.thread_id] < thread_cap:
            taken.append(p)
            per_thread[p.thread_id] += 1
    if len(taken) != n:
        raise AssertionError(f"drew {len(taken)} posts, expected {n}")
    return taken


def measurement_sample(pool: list[Post], seed: int, size: int, person_cap: int,
                       thread_cap_pct: int) -> tuple[list[Post], dict]:
    frame, capped = cap_people(pool, person_cap, seed)
    sizes = Counter(p.thread_id for p in frame)
    n, cap = thread_cap_size(list(sizes.values()), size, thread_cap_pct)
    if frame and n == 0:
        need = -(-100 // thread_cap_pct)
        shown = ", ".join(f"{t} {k}" for t, k in sizes.items())
        raise InputError(
            f"No measurement sample fits the thread cap. With no thread above {thread_cap_pct}% of the sample, "
            f"posts must come from at least {need} threads, and the frame has {len(sizes)} ({shown} posts). "
            f"Collect more threads, or loosen the cap with --thread-cap-pct N (the run manifest records it, "
            f"and the outputs will show it).")
    taken = draw(frame, n, cap, seed) if n else []
    got = Counter(p.thread_id for p in taken)
    before = Counter(p.thread_id for p in pool)
    info = {"target": size, "drawn": n,
            "frame": {"eligible": len(pool), "eligible_sha256": ids_hash([p.post_id for p in pool]),
                      "person_cap": person_cap, "people_capped": len(capped),
                      "posts_capped": sum(capped.values()) - person_cap * len(capped),
                      "after_person_cap": len(frame), "frame_sha256": ids_hash([p.post_id for p in frame])},
            "thread_cap_pct": thread_cap_pct, "thread_cap": cap,
            "threads": {t: {"eligible": before[t], "after_person_cap": sizes[t], "sampled": got[t]} for t in before}}
    return taken, info


# ---- detail selection (triage.py) --------------------------------------------

def detail_selection(pool: list[Post], flags: dict[str, set[str]], budget: int = thresholds.DETAIL_BUDGET,
                     per_person: int = thresholds.DETAIL_PER_PERSON) -> tuple[dict[str, list[str]], dict]:
    """triage.py's selection. Returns {post_id: reasons}, in the order picked, and a summary."""
    reasons: dict[str, list[str]] = defaultdict(list)
    per_author: Counter = Counter()
    fl = {p.post_id: flags.get(p.post_id, set()) & SIGNAL_FLAGS for p in pool}

    def take(p: Post, why: str) -> bool:
        if p.post_id in reasons:
            reasons[p.post_id].append(why)
            return False
        if p.kind != "post" and per_author[p.person_code] >= per_person:
            return False
        reasons[p.post_id].append(why)
        per_author[p.person_code] += 1
        return True

    clusters_out, method = [], None
    if len(pool) <= budget:
        for p in pool:
            reasons[p.post_id].append("all")
    else:
        for p in pool:
            if p.kind == "post":
                take(p, "post")
        quota = int(budget * 0.2)
        for p in sorted(pool, key=lambda p: -(p.score or 0)):
            if quota <= 0 or len(reasons) >= budget:
                break
            quota -= take(p, "top_score")
        quota = int(budget * 0.4)
        for p in sorted([p for p in pool if fl[p.post_id]], key=lambda p: (-len(fl[p.post_id]), -(p.score or 0))):
            if quota <= 0 or len(reasons) >= budget:
                break
            quota -= take(p, "flag:" + ",".join(sorted(fl[p.post_id])))
        texts = [p.text for p in pool]
        X, method = embed(texts)
        _, k, km = pick_k(X, None)
        terms = cluster_terms(texts, km.labels_, k)
        members: dict[int, list[int]] = defaultdict(list)
        for i, lab in enumerate(km.labels_):
            members[lab].append(i)
        remaining = budget - len(reasons)
        for lab in sorted(members, key=lambda lab: -len(members[lab])):
            idx = sorted(members[lab], key=lambda i: -float(np.dot(X[i], km.cluster_centers_[lab])))
            share = max(1, round(remaining * len(idx) / len(pool)))
            got = 0
            for i in idx:
                if got >= share or len(reasons) >= budget:
                    break
                got += take(pool[i], f"cluster:C{lab + 1:02d}")
            sel = sum(1 for i in idx if pool[i].post_id in reasons)
            clusters_out.append({"cluster_id": f"C{lab + 1:02d}", "size": len(idx), "selected": sel,
                                 "top_terms": terms[lab][:6]})
    first = Counter(rs[0].split(":")[0] for rs in reasons.values())
    info = {"budget": budget, "per_person": per_person, "candidates": len(pool), "selected": len(reasons),
            "all_kept": len(pool) <= budget, "first_reason": dict(first.most_common()),
            "people_at_cap": sum(1 for n in per_author.values() if n >= per_person),
            "cluster_method": method and f"{method}; k-means k={len(clusters_out)}", "clusters": clusters_out}
    return dict(reasons), info


# ---- the command -------------------------------------------------------------

def read_flags(study_dir: Path) -> dict[str, set[str]]:
    """Signal flags per post, refusing ones computed from an older posts.jsonl."""
    runs = [r for r in manifest.read(study_dir) if r.get("command") == "signals" and r.get("status") == "ok"]
    if not (study_dir / SIGNALS).exists() or not runs:
        raise InputError("Run crp signals first: the detail selection uses its flags.")
    if runs[-1]["inputs"].get(str(POSTS)) != sha256_file(study_dir / POSTS):
        raise InputError("posts.jsonl has changed since crp signals ran. Run crp signals again.")
    rows = [json.loads(line) for line in (study_dir / SIGNALS).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["post_id"]: set(r["flags"]) for r in rows}


def check_not_coded(study_dir: Path) -> None:
    for sub in ("batches", "labels"):
        d = study_dir / sub
        if d.is_dir() and any(d.iterdir()):
            raise InputError(f"{d} already holds files, so this sample has gone for coding. Drawing a new one now "
                             "would leave those labels without their sample. Once coding starts, the sample is fixed.")


def resolve_seed(study_dir: Path, seed: int | None) -> tuple[int, str]:
    if seed is not None:
        return seed, "given"
    prev = study_dir / SUMMARY
    if not prev.exists() and last_round(study_dir) is not None:
        prev = last_round(study_dir) / SUMMARY  # a new round keeps the seed, so earlier picks mostly stay (D35)
    if prev.exists():
        return int(json.loads(prev.read_text(encoding="utf-8"))["seed"]), "reused"
    return secrets.randbelow(2**31), "generated"


def sample(study_dir: Path, seed: int | None = None, size: int = thresholds.MEASUREMENT_SIZE,
           person_cap: int = thresholds.PERSON_CAP, thread_cap_pct: int = thresholds.THREAD_CAP_PCT,
           budget: int = thresholds.DETAIL_BUDGET, per_person: int = thresholds.DETAIL_PER_PERSON,
           min_words: int = thresholds.MIN_WORDS) -> dict:
    study_dir = Path(study_dir)
    posts_path = study_dir / POSTS
    if not posts_path.exists():
        raise InputError(f"No {posts_path}. Run crp anonymise first.")
    for name, value, lo, hi in (("size", size, 1, None), ("person cap", person_cap, 1, None),
                                ("thread cap", thread_cap_pct, 1, 100), ("budget", budget, 1, None),
                                ("detail per-person cap", per_person, 1, None), ("minimum words", min_words, 0, None)):
        if value < lo or (hi is not None and value > hi):
            raise InputError(f"The {name} must be {lo} or more{f' and {hi} or less' if hi else ''} (got {value}).")
    check_not_coded(study_dir)
    flags = read_flags(study_dir)
    posts = read_jsonl(posts_path, Post)
    seed, seed_source = resolve_seed(study_dir, seed)
    pool, left_out = candidates(posts, min_words)
    interview = [p for p in posts if p.source_type == "interview" and p.role == "participant"]
    if not pool and not interview:
        raise InputError("No posts to sample: every forum post was left out and there are no interview turns.")

    inputs = [posts_path, study_dir / SIGNALS] + ([study_dir / TOPUP] if (study_dir / TOPUP).exists() else [])
    with manifest.stage(study_dir, "sample", inputs=inputs, seed=seed) as record:
        taken, m_info = measurement_sample(pool, seed, size, person_cap, thread_cap_pct)
        reasons, d_info = detail_selection(pool, flags, budget, per_person) if pool else ({}, None)
        by_id = {p.post_id: p for p in posts}
        topups = [t for t in read_topup(study_dir) if t["post_id"] not in reasons]
        for t in topups:
            if t["post_id"] not in by_id or by_id[t["post_id"]].source_type != "forum":
                raise InputError(f"{TOPUP}: {t['post_id']} isn't a forum post in posts.jsonl any more.")
            reasons[t["post_id"]] = [f"topup: {t['reason']}"]
        order = {p.post_id: i for i, p in enumerate(posts)}
        chosen = {p.post_id for p in taken}
        write_jsonl(study_dir / MEASUREMENT, [
            MeasurementItem(post_id=p.post_id, thread_id=p.thread_id, person_code=p.person_code)
            for p in sorted(taken, key=lambda p: order[p.post_id])])
        detail = [DetailItem(post_id=p.post_id, thread_id=p.thread_id, person_code=p.person_code,
                             source_type=p.source_type, reasons=reasons[p.post_id])
                  for p in posts if p.post_id in reasons]
        detail += [DetailItem(post_id=p.post_id, thread_id=p.thread_id, person_code=p.person_code,
                              source_type="interview", reasons=["interview"]) for p in interview]
        write_jsonl(study_dir / DETAIL, sorted(detail, key=lambda d: order[d.post_id]))
        m_info["frame"] = {"forum_posts": sum(p.source_type == "forum" for p in posts), "min_words": min_words,
                           "left_out": dict(sorted(left_out.items()))} | m_info["frame"]
        m_info["sha256"] = sha256_file(study_dir / MEASUREMENT)
        summary = {"seed": seed, "seed_source": seed_source, "posts_sha256": sha256_file(posts_path),
                   "measurement": m_info,
                   "detail": {"forum": d_info, "interview_turns": len(interview),
                              "in_measurement_too": sum(p.post_id in chosen for p in detail),
                              "topup": len(topups),
                              "sha256": sha256_file(study_dir / DETAIL)}}
        atomic_write_text(study_dir / SUMMARY, json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        record["seed_source"] = seed_source
        record["settings"] = {"size": size, "person_cap": person_cap, "thread_cap_pct": thread_cap_pct,
                              "thread_cap_posts": m_info["thread_cap"], "budget": budget,
                              "detail_per_person": per_person, "min_words": min_words}
        record["frame_sha256"] = m_info["frame"]["frame_sha256"]
        record["eligible_sha256"] = m_info["frame"]["eligible_sha256"]
        record["outputs"] = [str(MEASUREMENT), str(DETAIL), str(SUMMARY)]
    return summary


# ---- reading the samples back ------------------------------------------------

def _checked_summary(study_dir: Path, key: str, path: Path) -> dict:
    summary_path = study_dir / SUMMARY
    if not path.exists() or not summary_path.exists():
        raise InputError(f"No {path}. Run crp sample first.")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    recorded = summary[key]["sha256"]
    if sha256_file(path) != recorded:
        raise InputError(f"{path} has been edited since crp sample drew it. Samples are made by code only: "
                         "run crp sample again.")
    if sha256_file(study_dir / POSTS) != summary["posts_sha256"]:
        raise InputError("posts.jsonl has changed since crp sample ran. Run crp signals and crp sample again.")
    return summary


def load_measurement(study_dir: Path) -> list[Post]:
    """The forum posts in the random measurement sample: the only posts any percentage may use."""
    study_dir = Path(study_dir)
    path = study_dir / MEASUREMENT
    _checked_summary(study_dir, "measurement", path)
    items = read_jsonl(path, MeasurementItem)
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    out = []
    for it in items:
        p = posts.get(it.post_id)
        if p is None or p.source_type != "forum":
            raise InputError(f"{path}: {it.post_id} isn't a forum post in posts.jsonl.")
        out.append(p)
    return out


def load_detail(study_dir: Path) -> list[tuple[DetailItem, Post]]:
    """The purposive detail selection, with each post. For close reading and nugget coding, never percentages."""
    study_dir = Path(study_dir)
    path = study_dir / DETAIL
    _checked_summary(study_dir, "detail", path)
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    out = []
    for it in read_jsonl(path, DetailItem):
        if it.post_id not in posts:
            raise InputError(f"{path}: {it.post_id} isn't in posts.jsonl.")
        out.append((it, posts[it.post_id]))
    return out
