import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-initialized Perplexity client (uses OpenAI SDK with custom base_url)
_client = None


def _get_api_key() -> Optional[str]:
    """Get Perplexity API key from environment, then Secret Manager fallback."""
    key = os.getenv("PERPLEXITY_API_KEY")
    if key:
        return key.strip()

    # Fallback: Google Secret Manager
    try:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if project_id:
            from google.cloud import secretmanager

            sm_client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/PERPLEXITY_API_KEY/versions/latest"
            response = sm_client.access_secret_version(request={"name": name})
            secret_val = response.payload.data.decode("UTF-8").strip()
            if secret_val:
                return secret_val
    except Exception as e:
        logger.warning(f"Could not get PERPLEXITY_API_KEY from Secret Manager: {e}")

    return None


def _get_client():
    """Lazy-initialize and return the Perplexity client (OpenAI SDK with custom base_url)."""
    global _client
    if _client is not None:
        return _client

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "PERPLEXITY_API_KEY not found. Set the PERPLEXITY_API_KEY environment variable "
            "or store it in Google Secret Manager."
        )

    from openai import OpenAI

    _client = OpenAI(api_key=api_key, base_url="https://api.perplexity.ai")
    logger.info("Perplexity client initialized successfully")
    return _client


# Human-friendly aliases -> concrete model ids
ALIASES = {
    "default": "sonar",
    "": "sonar",
    "sonar": "sonar",
    "sonar-pro": "sonar-pro",
    "sonar-reasoning": "sonar-reasoning",
}


def generate_text(
    prompt: str,
    model_name: str = "sonar",
    temperature: float = 0.7,
    max_tokens: int = 16000,
    timeout: int = 30,
) -> str:
    """Generate text using the Perplexity API (OpenAI-compatible).

    model_name: short model id. If caller passes 'perplexity:NAME' we strip the prefix.
    """
    # Normalize model_name if user passed provider prefix
    if isinstance(model_name, str) and model_name.startswith("perplexity:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""

    # Resolve aliases
    ms_lower = model_short.lower() if isinstance(model_short, str) else ""
    if ms_lower in ALIASES:
        model_short = ALIASES[ms_lower]

    client = _get_client()

    logger.info(f"Calling Perplexity chat: model={model_short}")

    response = client.chat.completions.create(
        model=model_short,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response and response.choices and len(response.choices) > 0:
        content = response.choices[0].message.content

        # Perplexity returns source URLs in a 'citations' field on the response
        citations = getattr(response, "citations", None)
        if citations and isinstance(citations, list):
            sources = "\n\n**Sources :**\n"
            for i, url in enumerate(citations, 1):
                sources += f"- [{i}. {url}]({url})\n"
            content += sources

        return content

    logger.warning(f"Unexpected Perplexity response shape: {response}")
    return str(response)
