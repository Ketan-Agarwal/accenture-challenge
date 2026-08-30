"""Shared embedding utilities for grounding and disagreement checks.

Loads ``all-MiniLM-L6-v2`` lazily on first use (~80 MB, CPU-only, <50 ms per
embedding) and exposes a thin API consumed by :mod:`app.checks`.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

log = logging.getLogger(__name__)

_MODEL = None


def _load_model():
    """Lazy-load the sentence-transformer model on first call."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("Loaded all-MiniLM-L6-v2 embedding model.")
    except Exception:
        log.warning("sentence-transformers unavailable; falling back to token Jaccard.", exc_info=True)
        _MODEL = None
    return _MODEL


def embed(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings for *texts*.

    Falls back to a zero matrix when the model cannot be loaded so that
    callers can degrade gracefully.
    """
    model = _load_model()
    if model is None:
        return np.zeros((len(texts), 1))
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalised vectors."""
    return float(np.dot(a, b))


def pairwise_cosine_matrix(embeddings: np.ndarray) -> np.ndarray:
    """Return the full pairwise cosine-similarity matrix for a set of embeddings."""
    return embeddings @ embeddings.T


def embeddings_available() -> bool:
    """Return *True* if the sentence-transformer model loaded successfully."""
    return _load_model() is not None


class EmbeddingIndex:
    """Pre-computed embedding index for a corpus of text chunks.

    Built once at startup (cheap: ~6 chunks × ~50 ms each) and reused for
    every grounding check.
    """

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self._embeddings: np.ndarray | None = None

    @property
    def embeddings(self) -> np.ndarray:
        if self._embeddings is None:
            self._embeddings = embed(self.chunks)
        return self._embeddings

    def best_match(self, query_embedding: np.ndarray) -> tuple[float, str, int]:
        """Return ``(score, chunk_text, chunk_index)`` for the closest chunk."""
        scores = self.embeddings @ query_embedding
        idx = int(np.argmax(scores))
        return float(scores[idx]), self.chunks[idx], idx

    def top_k(self, query_embedding: np.ndarray, k: int = 3) -> list[tuple[float, str, int]]:
        """Return the top-*k* chunks by cosine similarity."""
        scores = self.embeddings @ query_embedding
        indices = np.argsort(scores)[::-1][:k]
        return [(float(scores[i]), self.chunks[i], int(i)) for i in indices]
