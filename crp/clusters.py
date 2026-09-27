"""Topic clustering helpers, ported from the skill's themes.py.

crp sample uses them to spread the detail selection across topics (as triage.py did), and the
themes step will reuse them. TF-IDF + LSA embeddings, k-means with k picked by silhouette.

Both run on one thread. When several of k-means' starts reach the same fit, threaded arithmetic
picked a different one from run to run (same groups, different cluster numbers), so the same
input didn't always give the same output (D24).
"""
from __future__ import annotations

import numpy as np
from threadpoolctl import threadpool_limits

CONVERSATIONAL = {
    "yeah", "yes", "okay", "ok", "like", "just", "really", "know", "think", "um", "uh", "gonna",
    "wanna", "kind", "sort", "thing", "things", "stuff", "lot", "pretty", "actually", "mean",
    "right", "got", "get", "don", "didn", "doesn", "isn", "wasn", "ve", "ll", "re", "going",
    "said", "say", "guess", "maybe", "probably", "basically", "literally", "little", "bit",
    "way", "want", "use", "used", "using", "time", "good", "make", "does", "did", "doing", "oh",
}


def stopwords() -> list[str]:
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    return sorted(ENGLISH_STOP_WORDS | CONVERSATIONAL)


def embed(texts: list[str]) -> tuple[np.ndarray, str]:
    """TF-IDF + LSA vectors, normalised to unit length. Returns (vectors, method)."""
    with threadpool_limits(limits=1):
        return _embed(texts)


def _embed(texts: list[str]) -> tuple[np.ndarray, str]:
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


def pick_k(X: np.ndarray, k_fixed: int | None = None) -> tuple[float, int, object]:
    """k-means for each candidate k; keep the best silhouette. Returns (silhouette, k, fitted model)."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    n = len(X)
    if k_fixed:
        ks = [min(k_fixed, n - 1)]
    else:
        hi = max(3, min(12, n // 4))
        ks = list(range(3, hi + 1)) if n >= 12 else [2]
    best = None
    with threadpool_limits(limits=1):
        for k in ks:
            km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
            s = silhouette_score(X, km.labels_) if 1 < k < n else 0.0
            if best is None or s > best[0]:
                best = (s, k, km)
    return best


def cluster_terms(texts: list[str], labels, k: int, n_terms: int = 6) -> list[list[str]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [" ".join(t for t, lab in zip(texts, labels) if lab == c) for c in range(k)]
    vec = TfidfVectorizer(stop_words=stopwords(), ngram_range=(1, 2), sublinear_tf=True)
    M = vec.fit_transform(docs).toarray()
    vocab = np.array(vec.get_feature_names_out())
    return [list(vocab[np.argsort(row)[::-1][:n_terms]]) for row in M]
