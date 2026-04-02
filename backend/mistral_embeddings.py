import logging
import time
from typing import List

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "mistral-embed"
EMBEDDING_DIM = 1024


def _get_client():
    """Reuse the lazy-initialized Mistral client from mistral_client."""
    from mistral_client import _get_client as _mc
    return _mc()


def get_embedding(text: str) -> List[float]:
    """Get embedding with retry logic (3 attempts, exponential backoff).

    Raises on failure instead of returning zeros.
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = _get_client()
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                inputs=[text],
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Mistral embedding error (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def get_embedding_fast(text: str) -> List[float]:
    """Get embedding with a single attempt and shorter tolerance.

    Raises on failure instead of returning zeros.
    """
    try:
        client = _get_client()
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            inputs=[text],
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Mistral fast embedding error: {e}")
        raise
