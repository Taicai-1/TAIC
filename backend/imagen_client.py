import os
import base64
import logging

logger = logging.getLogger(__name__)


def generate_image(prompt: str, aspect_ratio: str = "1:1") -> bytes:
    """Generate an image using Imagen 3 via Vertex AI REST API.

    Uses Application Default Credentials (same pattern as gemini_client.py).

    Returns raw PNG bytes of the generated image.
    Raises RuntimeError if generation fails or safety filters block the prompt.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    credentials, default_project = google.auth.default()
    project = project or default_project
    if not project:
        raise RuntimeError(
            "Unable to determine GCP project for Imagen API "
            "(set GOOGLE_CLOUD_PROJECT or ensure ADC provides a project id)."
        )

    location = (
        os.getenv("IMAGEN_LOCATION")
        or os.getenv("CLOUD_RUN_REGION")
        or os.getenv("GOOGLE_CLOUD_REGION")
        or "us-central1"
    )

    session = AuthorizedSession(credentials)

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project}/locations/{location}/"
        f"publishers/google/models/imagen-3.0-generate-002:predict"
    )

    body = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
        },
    }

    logger.info(f"Calling Imagen 3: location={location} prompt_length={len(prompt)}")
    resp = session.post(url, json=body, timeout=60)

    if resp.status_code >= 400:
        logger.error(f"Imagen API error {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    data = resp.json()
    predictions = data.get("predictions")

    if not predictions:
        # Log full response to diagnose safety filter vs structural issue
        logger.warning(f"Imagen empty predictions. Full response: {data}")
        raise RuntimeError(
            "Imagen returned no predictions. "
            "The prompt may have been blocked by safety filters. "
            "Try rephrasing your request."
        )

    b64_image = predictions[0].get("bytesBase64Encoded")
    if not b64_image:
        raise RuntimeError("Imagen response missing image data (bytesBase64Encoded).")

    image_bytes = base64.b64decode(b64_image)
    logger.info(f"Imagen image generated: {len(image_bytes)} bytes")
    return image_bytes
