#!/usr/bin/env python3
"""Cluster nuggets (default) or raw participant turns into candidate cross-transcript themes.

Clusters are a second opinion on your synthesis, not the synthesis itself. For each
cluster you get top terms, how many independent voices contribute (transcripts for
interviews, authors for Reddit), whether one voice dominates it, and the most
representative items.

Embeddings: uses sentence-transformers (all-MiniLM-L6-v2) if installed and the model
can be downloaded, otherwise TF-IDF + LSA. Clustering: k-means, k picked by silhouette.

Usage:
  python themes.py --work WORKDIR [--source nuggets|turns] [--k 8] [--embed]
Writes WORKDIR/themes.json.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import (all_nuggets, load_manifest, load_turns, save_json, study_mode,  # noqa: E402
                     total_units, turn_index, unit_label, unit_of)

CONVERSATIONAL = {
    "yeah", "yes", "okay", "ok", "like", "just", "really", "know", "think", "um", "uh", "gonna",
    "wanna", "kind", "sort", "thing", "things", "stuff", "lot", "pretty", "actually", "mean",
    "right", "got", "get", "don", "didn", "doesn", "isn", "wasn", "ve", "ll", "re", "going",
    "said", "say", "guess", "maybe", "probably", "basically", "literally", "little", "bit",
    "way", "want", "use", "used", "using", "time", "good", "make", "does", "did", "doing", "oh",
}


def load_items(work, source):
    mode = study_mode(load_manifest(work))
    items = []
    if source == "nuggets":
        tindex = turn_index(work)
        for n in all_nuggets(work):
            items.append({"ref": n["id"], "transcript_id": n["transcript_id"],
                          "unit": unit_of(n, mode, tindex),
                          "text": f"{n.get('observation', '')} {n.get('quote', '')}",
                          "show": n.get("observation", "")})
    else:
        for m in load_manifest(work):
            for t in load_turns(work, m["transcript_id"])["turns"]:
                if t["role"] == "participant" and len(t["text"].split()) >= 12:
                    items.append({"ref": f"{m['transcript_id']}#{t['turn_id']}",
                                  "transcript_id": m["transcript_id"],
                                  "unit": t.get("author_id") if mode == "reddit" else m["transcript_id"],
                                  "text": t["text"], "show": t["text"]})
    return items, mode


def stopwords():
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    return sorted(ENGLISH_STOP_WORDS | CONVERSATIONAL)


def embed(texts, use_st):
    if use_st:
        try:
            from sentence_transformers import SentenceTransformer
            vec = SentenceTransformer("all-MiniLM-L6-v2").encode(texts, normalize_embeddings=True)
            return np.asarray(vec), "sentence-transformers all-MiniLM-L6-v2"
        except Exception as e:  # noqa: BLE001
            print(f"(sentence-transformers unavailable: {e.__class__.__name__}; using TF-IDF+LSA)")
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize
    sw = stopwords()
    X = None
    for min_df in (2, 1):
        vec = TfidfVectorizer(stop_words=sw, ngram_range=(1, 2), min_df=min_df, sublinear_tf=True)
        X = vec.fit_transform(texts)
        if X.shape[1] >= 20:
            break
    n_comp = min(100, X.shape[1] - 1, X.shape[0] - 1)
    if n_comp >= 2:
        X = TruncatedSVD(n_components=n_comp, random_state=0).fit_transform(X)
        return normalize(X), f"TF-IDF + LSA ({n_comp} dims)"
    return normalize(X.toarray()), "TF-IDF"


def pick_k(X, k_fixed):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    n = len(X)
    if k_fixed:
        ks = [min(k_fixed, n - 1)]
    else:
        hi = max(3, min(12, n // 4))
        ks = list(range(3, hi + 1)) if n >= 12 else [2]
    best = None
    for k in ks:
        km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
        s = silhouette_score(X, km.labels_) if 1 < k < n else 0.0
        if best is None or s > best[0]:
            best = (s, k, km)
    return best


def cluster_terms(texts, labels, k, n_terms=6):
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [" ".join(t for t, l in zip(texts, labels) if l == c) for c in range(k)]
    vec = TfidfVectorizer(stop_words=stopwords(), ngram_range=(1, 2), sublinear_tf=True)
    M = vec.fit_transform(docs).toarray()
    vocab = np.array(vec.get_feature_names_out())
    return [list(vocab[np.argsort(row)[::-1][:n_terms]]) for row in M]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--source", choices=["nuggets", "turns"], default="nuggets")
    ap.add_argument("--k", type=int, help="fix the number of clusters")
    ap.add_argument("--embed", action="store_true", help="try sentence-transformers embeddings")
    args = ap.parse_args()

    items, mode = load_items(args.work, args.source)
    if len(items) < 8:
        raise SystemExit(f"Only {len(items)} items; too few to cluster meaningfully. Synthesise by hand.")
    texts = [i["text"] for i in items]
    X, method = embed(texts, args.embed)
    sil, k, km = pick_k(X, args.k)
    labels = km.labels_
    terms = cluster_terms(texts, labels, k)
    n_units = total_units(args.work, mode)
    label = unit_label(mode)

    clusters = []
    for c in range(k):
        idx = [i for i, l in enumerate(labels) if l == c]
        tids = Counter(items[i]["unit"] for i in idx)
        top_tid, top_n = tids.most_common(1)[0]
        centroid = km.cluster_centers_[c]
        order = sorted(idx, key=lambda i: -float(np.dot(X[i], centroid)))
        clusters.append({
            "cluster_id": f"C{c + 1:02d}",
            "size": len(idx),
            "top_terms": terms[c],
            "coverage": len(tids),
            "units": sorted(u for u in tids if u),
            "dominated_by": top_tid if len(idx) >= 4 and top_n / len(idx) > 0.5 else None,
            "representative": [{"ref": items[i]["ref"], "transcript_id": items[i]["transcript_id"],
                                "text": items[i]["show"][:220]} for i in order[:3]],
            "members": [items[i]["ref"] for i in idx],
        })
    clusters.sort(key=lambda c: (-c["coverage"], -c["size"]))
    save_json({"source": args.source, "method": f"{method}; k-means k={k}",
               "silhouette": round(float(sil), 3), "n_items": len(items),
               "unit": label, "n_units": n_units, "clusters": clusters},
              Path(args.work) / "themes.json")

    print(f"{len(items)} {args.source} -> {k} clusters via {method} (silhouette {sil:.2f})")
    if sil < 0.1:
        print("  ! Low silhouette: clusters overlap heavily. Treat as loose groupings only.")
    for c in clusters:
        dom = f"  ! mostly {c['dominated_by']}" if c["dominated_by"] else ""
        print(f"{c['cluster_id']} n={c['size']:>3} {label}={c['coverage']}/{n_units}  "
              f"{', '.join(c['top_terms'][:5])}{dom}")


if __name__ == "__main__":
    main()
