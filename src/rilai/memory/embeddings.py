"""Embedding generation for semantic search."""

from typing import List, Optional
import hashlib
import json
from pathlib import Path

# Simple cache for embeddings
_cache: dict[str, List[float]] = {}
_cache_file: Optional[Path] = None


def set_cache_file(path: Path) -> None:
    """Set the cache file path and load existing cache."""
    global _cache, _cache_file
    _cache_file = path

    if path.exists():
        try:
            with open(path) as f:
                _cache = json.load(f)
        except (json.JSONDecodeError, IOError):
            _cache = {}


def _save_cache() -> None:
    """Save cache to file."""
    if _cache_file:
        try:
            with open(_cache_file, "w") as f:
                json.dump(_cache, f)
        except IOError:
            pass


def _get_cache_key(text: str) -> str:
    """Generate cache key for text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def get_embedding(text: str) -> Optional[List[float]]:
    """Get embedding for text.

    Uses OpenRouter's embedding endpoint or falls back to simple hashing.
    Results are cached to reduce API calls.
    """
    if not text:
        return None

    # Check cache
    cache_key = _get_cache_key(text)
    if cache_key in _cache:
        return _cache[cache_key]

    # Try to get real embedding
    try:
        embedding = await _fetch_embedding(text)
    except Exception:
        # Fallback to simple hash-based embedding
        embedding = _simple_embedding(text)

    # Cache result
    _cache[cache_key] = embedding
    _save_cache()

    return embedding


async def _fetch_embedding(text: str) -> List[float]:
    """Fetch embedding from API."""
    try:
        from rilai.providers.openrouter import get_provider

        provider = get_provider()

        # Use embedding endpoint if available
        if hasattr(provider, "embed"):
            return await provider.embed(text)
    except Exception:
        pass

    # Otherwise use a small model to generate pseudo-embedding
    # This is a fallback - not as good as real embeddings
    raise NotImplementedError("Real embeddings not available")


def _simple_embedding(text: str, dim: int = 128) -> List[float]:
    """Generate simple hash-based embedding.

    This is a fallback when real embeddings aren't available.
    Uses character n-grams and word features.
    """
    import math

    # Initialize with zeros
    embedding = [0.0] * dim

    words = text.lower().split()

    # Word-level features
    for i, word in enumerate(words[:50]):
        word_hash = hash(word)
        idx = word_hash % dim
        # Position-weighted contribution
        weight = 1.0 / (1.0 + i * 0.1)
        embedding[idx] += weight

    # Character n-gram features
    text_lower = text.lower()
    for n in [2, 3]:
        for i in range(len(text_lower) - n + 1):
            ngram = text_lower[i:i+n]
            idx = hash(ngram) % dim
            embedding[idx] += 0.5

    # Normalize
    magnitude = math.sqrt(sum(x * x for x in embedding))
    if magnitude > 0:
        embedding = [x / magnitude for x in embedding]

    return embedding


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)
