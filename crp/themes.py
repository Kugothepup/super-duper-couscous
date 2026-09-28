"""crp themes: cluster observations (default) or forum posts into candidate themes. Ported from themes.py.

A second opinion on the synthesis, not the synthesis. For each cluster: its top terms, how many people
contribute (coverage), whether one person dominates it (over half of a cluster of 4+), and the three
most representative posts. TF-IDF + LSA embeddings and k-means with k picked by silhouette (crp/clusters.py).
  --source observations  each observation with its quote (the skill's nuggets)
  --source posts         every forum post of 12+ words in the collection (the skill's turns)
Writes results/themes.json with post ids and terms only; read the texts with crp view posts <study> ID ...
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from crp import manifest
from crp.anonymise import POSTS
from crp.clusters import cluster_terms, embed, pick_k
from crp.io import InputError, atomic_write_text, read_jsonl
from crp.schemas import Post
from crp.synthesis import OBSERVATIONS, load

THEMES = Path("results") / "themes.json"
MIN_ITEMS = 8
MIN_WORDS = 12


def items_of(study_dir: Path, source: str) -> list[dict]:
    posts = {p.post_id: p for p in read_jsonl(study_dir / POSTS, Post)}
    if source == "observations":
        return [{"ref": o.post_id, "person": posts[o.post_id].person_code, "text": f"{o.observation} {o.quote}"}
                for o in load(study_dir)["observations"] if o.post_id in posts]
    return [{"ref": p.post_id, "person": p.person_code, "text": p.text} for p in posts.values()
            if p.source_type == "forum" and p.role == "participant" and len(p.text.split()) >= MIN_WORDS]


def cluster(items: list[dict], k: int | None = None) -> dict:
    texts = [i["text"] for i in items]
    X, method = embed(texts)
    sil, k, km = pick_k(X, k)
    labels = km.labels_
    terms = cluster_terms(texts, labels, k)
    clusters = []
    for c in range(k):
        idx = [i for i, lab in enumerate(labels) if lab == c]
        people = Counter(items[i]["person"] for i in idx)
        top_person, top_n = people.most_common(1)[0]
        order = sorted(idx, key=lambda i: -float(np.dot(X[i], km.cluster_centers_[c])))
        clusters.append({"cluster_id": f"C{c + 1:02d}", "size": len(idx), "top_terms": terms[c], "coverage": len(people),
                         "dominated_by": top_person if len(idx) >= 4 and top_n / len(idx) > 0.5 else None,
                         "representative": [items[i]["ref"] for i in order[:3]],
                         "members": [items[i]["ref"] for i in idx]})
    clusters.sort(key=lambda c: (-c["coverage"], -c["size"]))
    return {"method": f"{method}; k-means k={k}", "silhouette": round(float(sil), 3), "n_items": len(items),
            "n_people": len({i["person"] for i in items}), "clusters": clusters}


def themes(study_dir: Path, source: str = "observations", k: int | None = None) -> dict:
    study_dir = Path(study_dir)
    items = items_of(study_dir, source)
    if len(items) < MIN_ITEMS:
        raise InputError(f"Only {len(items)} {source}: too few to cluster meaningfully (need {MIN_ITEMS}). "
                         "Synthesise by hand.")
    inputs = [study_dir / POSTS] + ([study_dir / OBSERVATIONS] if source == "observations" else [])
    with manifest.stage(study_dir, "themes", inputs=inputs) as record:
        out = {"source": source} | cluster(items, k)
        atomic_write_text(study_dir / THEMES, json.dumps(out, indent=2) + "\n")
        record["outputs"] = [str(THEMES)]
        record["settings"] = {"source": source, "k": k}
    return out
