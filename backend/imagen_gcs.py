import os
import time
import uuid
import logging

from google.cloud import storage

logger = logging.getLogger(__name__)


def upload_generated_image(image_bytes: bytes, agent_id: int) -> str:
    """Upload generated image bytes to GCS and return public URL.

    Uses the same GCS_BUCKET_NAME env var as the rest of the application.
    Images are stored under generated-images/{agent_id}/{timestamp}_{uuid}.png
    """
    bucket_name = os.getenv("GCS_BUCKET_NAME", "applydi-agent-photos")
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    filename = f"generated-images/{agent_id}/{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type="image/png")

    try:
        blob.make_public()
    except Exception:
        logger.exception("Failed to make generated image public; object may remain private")

    public_url = blob.public_url
    logger.info(f"Uploaded generated image to GCS: {public_url}")
    return public_url
