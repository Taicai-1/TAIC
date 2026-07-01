import hashlib
import json
import logging
import time
from typing import List

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "mistral-embed"
EMBEDDING_DIM = 1024

_EMB_CACHE_TTL = 86400  # 24 hours


def _get_client():
    """Reuse the lazy-initialized Mistral client from mistral_client."""
    from mistral_client import _get_client as _mc

    return _mc()


def _cache_key(text: str) -> str:
    return f"emb:mistral:{hashlib.md5(text.encode()).hexdigest()[:16]}"


def _get_cached_embedding(text: str) -> List[float] | None:
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            return None
        cached = r.get(_cache_key(text))
        if cached is not None:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Mistral embedding cache read failed: {e}")
    return None


def _set_cached_embedding(text: str, embedding: List[float]):
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            return
        r.setex(_cache_key(text), _EMB_CACHE_TTL, json.dumps(embedding))
    except Exception as e:
        logger.debug(f"Mistral embedding cache write failed: {e}")


def get_embedding(text: str) -> List[float]:
    """Get embedding with retry logic (3 attempts, exponential backoff).

    Raises on failure instead of returning zeros.
    """
    cached = _get_cached_embedding(text)
    if cached is not None:
        return cached

    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = _get_client()
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=[text],
            )
            result = response.data[0].embedding
            _set_cached_embedding(text, result)
            return result
        except Exception as e:
            logger.error(f"Mistral embedding error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                raise


def get_embedding_fast(text: str) -> List[float]:
    """Get embedding with a single attempt and shorter tolerance.

    Raises on failure instead of returning zeros.
    """
    cached = _get_cached_embedding(text)
    if cached is not None:
        return cached

    try:
        client = _get_client()
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            inputs=[text],
        )
        result = response.data[0].embedding
        _set_cached_embedding(text, result)
        return result
    except Exception as e:
        logger.error(f"Mistral fast embedding error: {e}")
        raise


def get_embeddings_batch(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """Embed many texts, returning embeddings in the same order as ``texts``.

    Serves cache hits individually; sends only cache misses to the API in groups of
    ``batch_size`` (the Mistral embeddings endpoint accepts a list of inputs per call).
    Raises on API failure (no zero-vector fallback), consistent with get_embedding_fast
    (single attempt, no retry).
    """
    if not texts:
        return []

    results: List[List[float]] = [None] * len(texts)
    miss_indices: List[int] = []
    for i, t in enumerate(texts):
        cached = _get_cached_embedding(t)
        if cached is not None:
            results[i] = cached
        else:
            miss_indices.append(i)

    client = _get_client()
    for start in range(0, len(miss_indices), batch_size):
        group = miss_indices[start : start + batch_size]
        inputs = [texts[i] for i in group]
        try:
            response = client.embeddings.create(model=EMBEDDING_MODEL, inputs=inputs)
        except Exception as e:
            logger.error(f"Mistral batch embedding error (batch start {start}, {len(inputs)} inputs): {e}")
            raise
        for idx, item in zip(group, response.data):
            emb = item.embedding
            results[idx] = emb
            _set_cached_embedding(texts[idx], emb)

    return results
