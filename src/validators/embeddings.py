"""Embedding manager for semantic scoring — loads model, caches vectors."""

from __future__ import annotations

import numpy as np


class EmbeddingManager:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self._cache: dict[str, np.ndarray] = {}

    def embed(self, text: str) -> np.ndarray:
        """Embed text, using cache for repeated inputs."""
        cache_key = text[:200]  # Use first 200 chars as cache key
        if cache_key in self._cache:
            return self._cache[cache_key]

        embedding = self.model.encode(text, convert_to_numpy=True)
        self._cache[cache_key] = embedding
        return embedding

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    def clear_cache(self) -> None:
        self._cache.clear()
