import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-initialized Mistral client
_client = None


def _get_api_key() -> Optional[str]:
    """Get Mistral API key from environment, then Secret Manager fallback."""
    key = os.getenv("MISTRAL_API_KEY")
    if key:
        return key.strip()

    # Fallback: Google Secret Manager
    try:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        if project_id:
            from google.cloud import secretmanager

            sm_client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/MISTRAL_API_KEY/versions/latest"
            response = sm_client.access_secret_version(request={"name": name})
            secret_val = response.payload.data.decode("UTF-8").strip()
            if secret_val:
                return secret_val
    except Exception as e:
        logger.warning(f"Could not get MISTRAL_API_KEY from Secret Manager: {e}")

    return None


def _get_client():
    """Lazy-initialize and return the Mistral client."""
    global _client
    if _client is not None:
        return _client

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError(
            "MISTRAL_API_KEY not found. Set the MISTRAL_API_KEY environment variable "
            "or store it in Google Secret Manager."
        )

    try:
        from mistralai import Mistral
    except ImportError:
        from mistralai.client import Mistral
    _client = Mistral(api_key=api_key)
    logger.info("Mistral client initialized successfully")
    return _client


# Human-friendly aliases -> concrete model ids
ALIASES = {
    "small": "mistral-small-latest",
    "medium": "mistral-medium-latest",
    "large": "mistral-large-latest",
    "mistral-small": "mistral-small-latest",
    "mistral-medium": "mistral-medium-latest",
    "mistral-large": "mistral-large-latest",
    "default": os.getenv("MISTRAL_DEFAULT_MODEL", "mistral-small-latest"),
    "": os.getenv("MISTRAL_DEFAULT_MODEL", "mistral-small-latest"),
}


def generate_text(
    prompt: str,
    model_name: str = "mistral-small-latest",
    temperature: float = 0.7,
    max_tokens: int = 16000,
    timeout: int = 30,
) -> str:
    """Generate text using the Mistral API.

    model_name: short model id. If caller passes 'mistral:NAME' we strip the prefix.
    """
    # Normalize model_name if user passed provider prefix
    if isinstance(model_name, str) and model_name.startswith("mistral:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""

    # Resolve aliases
    ms_lower = model_short.lower() if isinstance(model_short, str) else ""
    if ms_lower in ALIASES:
        model_short = ALIASES[ms_lower]

    client = _get_client()

    logger.info(f"Calling Mistral chat: model={model_short}")

    response = client.chat.complete(
        model=model_short,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if response and response.choices and len(response.choices) > 0:
        content = response.choices[0].message.content
        try:
            from llm_usage import record_usage, count_tokens

            u = getattr(response, "usage", None)
            if u is not None:
                record_usage(
                    "mistral", model_short, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0
                )
            else:
                record_usage("mistral", model_short, count_tokens(prompt), count_tokens(content or ""))
        except Exception:
            pass
        return content

    logger.warning(f"Unexpected Mistral response shape: {response}")
    return str(response)


def _resolve_model(model_name: str) -> str:
    """Resolve a model name to a concrete Mistral model id."""
    if isinstance(model_name, str) and model_name.startswith("mistral:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""
    ms_lower = model_short.lower() if isinstance(model_short, str) else ""
    if ms_lower in ALIASES:
        model_short = ALIASES[ms_lower]
    return model_short


def generate_with_tools(
    messages: list[dict],
    tools: list[dict],
    model_name: str = "mistral-small-latest",
    temperature: float = 0.7,
    max_tokens: int = 16000,
) -> dict:
    """Call Mistral chat with function calling support.

    Args:
        messages: OpenAI-style messages list.
        tools: List of tools in OpenAI format (type: function, function: {name, description, parameters}).
        model_name: Mistral model name.

    Returns:
        dict with keys:
          - "content": str | None (text content if any)
          - "tool_call": dict | None ({"name": str, "arguments": dict} if function call)
    """
    model_short = _resolve_model(model_name)
    client = _get_client()
    logger.info(f"Calling Mistral chat with tools: model={model_short}")

    response = client.chat.complete(
        model=model_short,
        messages=messages,
        tools=tools,
        tool_choice="auto",
        temperature=temperature,
        max_tokens=max_tokens,
    )

    if not response or not response.choices:
        return {"content": None, "tool_call": None}

    message = response.choices[0].message
    text_content = message.content if message.content else None
    tool_call = None

    if message.tool_calls and len(message.tool_calls) > 0:
        tc = message.tool_calls[0]
        import json

        args = tc.function.arguments
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        tool_call = {"name": tc.function.name, "arguments": args, "id": getattr(tc, "id", "") or ""}

    return {"content": text_content, "tool_call": tool_call}


def generate_text_stream(
    prompt: str,
    model_name: str = "mistral-small-latest",
    temperature: float = 0.7,
    max_tokens: int = 16000,
):
    """Generate text using the Mistral API in streaming mode.

    Yields text chunks as they arrive from the API.
    """
    if isinstance(model_name, str) and model_name.startswith("mistral:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""

    ms_lower = model_short.lower() if isinstance(model_short, str) else ""
    if ms_lower in ALIASES:
        model_short = ALIASES[ms_lower]

    client = _get_client()
    logger.info(f"Calling Mistral chat stream: model={model_short}")

    stream = client.chat.stream(
        model=model_short,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    for event in stream:
        chunk = event.data.choices[0].delta.content
        if chunk:
            yield chunk
