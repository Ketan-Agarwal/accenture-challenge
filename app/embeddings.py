"""Shared embedding utilities for grounding and disagreement checks.

Local embeddings are optional. The model is loaded only when explicitly
enabled and never downloads at request time unless a separate opt-in flag is
set. This keeps the default demo deterministic and offline-safe.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_MODEL = None
_LOAD_ATTEMPTED = False


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_model():
    """Load the optional model at most once, with downloads disabled by default."""
    global _MODEL, _LOAD_ATTEMPTED
    if _LOAD_ATTEMPTED:
        return _MODEL
    _LOAD_ATTEMPTED = True
    if not _enabled("CONTROLPLANE_ENABLE_LOCAL_EMBEDDINGS"):
        log.info("Local embeddings disabled; using the deterministic Jaccard fallback.")
        return None
    try:
        from sentence_transformers import SentenceTransformer

        allow_download = _enabled("CONTROLPLANE_ALLOW_MODEL_DOWNLOAD")
        _MODEL = SentenceTransformer(
            "all-MiniLM-L6-v2",
            local_files_only=not allow_download,
        )
        log.info("Loaded all-MiniLM-L6-v2 embedding model.")
    except Exception:
        log.warning(
            "Local embedding model unavailable; using token Jaccard. "
            "Install the embeddings extra and pre-cache the model to enable it."
        )
        _MODEL = None
    return _MODEL


def embed(texts: list[str]) -> Any:
    """Return L2-normalised embeddings for *texts*.

    Callers must check :func:`embeddings_available` first.
    """
    model = _load_model()
    if model is None:
        raise RuntimeError("Local embeddings are not enabled or the model is unavailable")
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def cosine_similarity(a: Any, b: Any) -> float:
    """Cosine similarity between two L2-normalised vectors."""
    return float(sum(float(left) * float(right) for left, right in zip(a, b, strict=True)))


def pairwise_cosine_matrix(embeddings: Any) -> Any:
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
        self._embeddings: Any | None = None

    @property
    def embeddings(self) -> Any:
        if self._embeddings is None:
            self._embeddings = embed(self.chunks)
        return self._embeddings

    def best_match(self, query_embedding: Any) -> tuple[float, str, int]:
        """Return ``(score, chunk_text, chunk_index)`` for the closest chunk."""
        scores = self.embeddings @ query_embedding
        idx = max(range(len(scores)), key=lambda candidate: float(scores[candidate]))
        return float(scores[idx]), self.chunks[idx], idx

    def top_k(self, query_embedding: Any, k: int = 3) -> list[tuple[float, str, int]]:
        """Return the top-*k* chunks by cosine similarity."""
        scores = self.embeddings @ query_embedding
        indices = sorted(range(len(scores)), key=lambda candidate: float(scores[candidate]), reverse=True)[:k]
        return [(float(scores[i]), self.chunks[i], int(i)) for i in indices]
