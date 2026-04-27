import os
from openai import OpenAI
from google.cloud import secretmanager
import logging
from typing import Any, Optional
import json

# Optional import for Gemini/Vertex AI client
try:
    from gemini_client import generate_text as gemini_generate_text
except Exception:
    gemini_generate_text = None
try:
    from gemini_client import generate_text_stream as gemini_generate_text_stream
except Exception:
    gemini_generate_text_stream = None

# Optional import for Mistral client
try:
    from mistral_client import generate_text as mistral_generate_text
except Exception:
    mistral_generate_text = None
try:
    from mistral_client import generate_text_stream as mistral_generate_text_stream
except Exception:
    mistral_generate_text_stream = None

# Optional import for Perplexity client
try:
    from perplexity_client import generate_text as perplexity_generate_text
except Exception:
    perplexity_generate_text = None
try:
    from perplexity_client import generate_text_stream as perplexity_generate_text_stream
except Exception:
    perplexity_generate_text_stream = None


def _messages_to_prompt(messages: list) -> str:
    """Convert a list of chat messages (dicts with role/content) to a single prompt string.

    This helper is used when routing chat messages to non-OpenAI providers (e.g. Gemini)
    that expect a single text prompt rather than an OpenAI-style messages array.
    """
    parts = []
    for m in messages:
        role = m.get("role", "user") if isinstance(m, dict) else "user"
        content = m.get("content") if isinstance(m, dict) else str(m)
        parts.append(f"[{role}] {content}")
    return "\n\n".join(parts)


logger = logging.getLogger(__name__)


def get_secret(secret_name: str, project_id: str = None) -> str:
    """Get secret from Google Secret Manager"""
    try:
        if project_id:
            client = secretmanager.SecretManagerServiceClient()
            name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
            response = client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.warning(f"Could not get secret {secret_name}: {e}")

    # Fallback to environment variable
    return os.getenv(secret_name)


# Initialize OpenAI client
project_id = os.getenv("GOOGLE_CLOUD_PROJECT")

# Try environment variable first (injected by Cloud Run --set-secrets)
api_key = os.getenv("OPENAI_API_KEY")

# Clean the API key - remove any whitespace/newlines
if api_key:
    api_key = api_key.strip()

# Fallback to Secret Manager if not in environment
if not api_key:
    api_key = get_secret("OPENAI_API_KEY", project_id)
    if api_key:
        api_key = api_key.strip()

if not api_key:
    raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable or store in Secret Manager.")

logger.info(f"OpenAI API key found: {'Yes' if api_key else 'No'}")

# Initialize OpenAI client with custom configuration for Cloud Run
import httpx

client = OpenAI(
    api_key=api_key,
    timeout=120.0,
    max_retries=3,
    http_client=httpx.Client(
        timeout=120.0,
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        http2=False,  # Force HTTP/1.1 for better Cloud Run compatibility
    ),
)

# Allow overriding the model and the response token limit via environment variables.
# Default back to gpt-4 (the model used previously)
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-1106-preview")
try:
    DEFAULT_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "128000"))
except Exception:
    DEFAULT_MAX_TOKENS = 128000

import hashlib

_EMB_CACHE_TTL = 86400  # 24 hours


def _emb_cache_key(text: str) -> str:
    return f"emb:openai:{hashlib.md5(text.encode()).hexdigest()[:16]}"


def _get_cached_embedding(text: str) -> list | None:
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            return None
        cached = r.get(_emb_cache_key(text))
        if cached is not None:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"OpenAI embedding cache read failed: {e}")
    return None


def _set_cached_embedding(text: str, embedding: list):
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            return
        r.setex(_emb_cache_key(text), _EMB_CACHE_TTL, json.dumps(embedding))
    except Exception as e:
        logger.debug(f"OpenAI embedding cache write failed: {e}")


def get_embedding_fast(text: str) -> list:
    """Get embedding for text with fast timeout"""
    cached = _get_cached_embedding(text)
    if cached is not None:
        return cached

    try:
        response = client.embeddings.create(input=text, model="text-embedding-3-small")
        result = response.data[0].embedding
        _set_cached_embedding(text, result)
        return result
    except Exception as e:
        logger.error(f"Error getting fast embedding: {e}")
        # Return dummy embedding immediately — do NOT cache dummy vectors
        return [0.0] * 1536  # text-embedding-3-small has 1536 dimensions


def get_embedding(text: str) -> list:
    """Get embedding for text with robust retry logic"""
    cached = _get_cached_embedding(text)
    if cached is not None:
        return cached

    import time

    max_retries = 5

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to get embedding (attempt {attempt + 1}/{max_retries})")
            response = client.embeddings.create(input=text, model="text-embedding-3-small")
            logger.info("Successfully got embedding from OpenAI")
            result = response.data[0].embedding
            _set_cached_embedding(text, result)
            return result
        except Exception as e:
            logger.error(f"Error getting embedding (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # Exponential backoff
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                logger.error("All embedding attempts failed")
                raise e


def get_chat_response(messages: list, model_id: str = None, gemini_only: bool = False) -> str:
    """Get chat response from OpenAI with robust retry logic, custom model, and structured messages"""
    import time

    max_retries = 5
    # Prefer explicit model_id passed in, otherwise use environment/default.
    model = model_id if model_id else DEFAULT_MODEL
    # choose max tokens early so it's available to provider-specific branches
    max_tokens = DEFAULT_MAX_TOKENS
    # If the requested model references Gemini/Perplexity providers, try to route accordingly.
    if isinstance(model, str) and model.startswith("gemini:"):
        if gemini_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                return gemini_generate_text(prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens)
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    logger.error(f"Gemini-only mode enabled and Gemini call failed: {e}")
                    raise
                logger.warning(f"Gemini call failed (will fallback to OpenAI): {e}")
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Gemini client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("mistral:"):
        if mistral_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                result = mistral_generate_text(prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens)
                logger.info(f"[LLM USED] Mistral ({model_short}) - SUCCESS")
                return result
            except Exception as e:
                logger.error(f"[LLM USED] Mistral ({model_short}) - FAILED: {e}, falling back to OpenAI")
                if gemini_only:
                    raise
                model = DEFAULT_MODEL
        else:
            logger.error(
                f"[LLM USED] Mistral client NOT AVAILABLE (mistralai package not loaded), falling back to OpenAI ({DEFAULT_MODEL})"
            )
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("perplexity:"):
        if perplexity_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                result = perplexity_generate_text(
                    prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens
                )
                logger.info(f"[LLM USED] Perplexity ({model_short}) - SUCCESS")
                return result
            except Exception as e:
                logger.error(f"[LLM USED] Perplexity ({model_short}) - FAILED: {e}, falling back to OpenAI")
                if gemini_only:
                    raise
                model = DEFAULT_MODEL
        else:
            logger.error(f"[LLM USED] Perplexity client NOT AVAILABLE, falling back to OpenAI ({DEFAULT_MODEL})")
            model = DEFAULT_MODEL
    logger.info(f"[LLM USED] OpenAI ({model}) - sending request")
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to get chat response (attempt {attempt + 1}/{max_retries}) with model {model}")
            response = client.chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens, temperature=0.7
            )
            logger.info("Successfully got response from OpenAI")
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error getting chat response (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = 2**attempt  # Exponential backoff
                logger.info(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
            else:
                logger.error("All chat response attempts failed")
                raise e


def get_chat_response_stream(messages: list, model_id: str = None, gemini_only: bool = False):
    """Stream chat response tokens from the appropriate LLM provider.

    Same routing logic as get_chat_response() but yields text chunks
    instead of returning the full response.
    """
    model = model_id if model_id else DEFAULT_MODEL
    max_tokens = DEFAULT_MAX_TOKENS

    # Route to Gemini
    if isinstance(model, str) and model.startswith("gemini:"):
        if gemini_generate_text_stream:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                yield from gemini_generate_text_stream(prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens)
                return
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                if bool(gemini_only) or env_gemini_only:
                    raise
                logger.warning(f"Gemini stream failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Gemini stream client not available; falling back to OpenAI ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL

    # Route to Mistral
    if isinstance(model, str) and model.startswith("mistral:"):
        if mistral_generate_text_stream:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                yield from mistral_generate_text_stream(prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens)
                return
            except Exception as e:
                logger.error(f"Mistral stream failed: {e}, falling back to OpenAI")
                if gemini_only:
                    raise
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Mistral stream client not available; falling back to OpenAI ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL

    # Route to Perplexity
    if isinstance(model, str) and model.startswith("perplexity:"):
        if perplexity_generate_text_stream:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                yield from perplexity_generate_text_stream(prompt, model_name=model_short, temperature=0.7, max_tokens=max_tokens)
                return
            except Exception as e:
                logger.error(f"Perplexity stream failed: {e}, falling back to OpenAI")
                if gemini_only:
                    raise
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Perplexity stream client not available; falling back to OpenAI ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL

    # Default: OpenAI streaming
    logger.info(f"[LLM STREAM] OpenAI ({model}) - sending streaming request")
    response = client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=0.7, stream=True
    )
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def get_chat_response_structured(
    messages: list,
    functions: list | None = None,
    function_call: Optional[dict | str] = None,
    model_id: str = None,
    gemini_only: bool = False,
) -> Any:
    """Call OpenAI chat completions with optional function-calling and return the full message (may include function_call).

    - messages: list of message dicts
    - functions: list of function schemas (OpenAI functions)
    - function_call: None (auto), {'name': 'foo'} to force, or 'auto'
    Returns the choice message (object with .content and possibly .function_call)
    """
    import time

    max_retries = 3
    model = model_id if model_id else DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("gemini:"):
        if gemini_generate_text:
            model_short = model.split(":", 1)[1]
            # For structured/function-calling we can't fully emulate OpenAI functions with Gemini yet.
            # Attempt to emulate function-calling by calling Gemini with concatenated messages
            # and trying to parse a JSON function_call object from its textual response.
            prompt = _messages_to_prompt(messages)
            try:
                text = gemini_generate_text(
                    prompt, model_name=model_short, temperature=0.2, max_tokens=DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    logger.error(f"Gemini-only mode enabled and structured Gemini call failed: {e}")
                    raise
                logger.warning(f"Gemini structured call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
                text = None

            class SimpleMsg:
                def __init__(self, content, function_call=None):
                    self.content = content
                    self.function_call = function_call

            # Try to parse the model output as JSON. If it contains a function call-like object,
            # expose it as `.function_call` so the main action flow can use it.
            try:
                parsed = json.loads(text)
                # Look for common shapes: {"function_call": {...}} or {"name":..., "arguments": ...}
                fc = None
                if isinstance(parsed, dict):
                    if "function_call" in parsed and isinstance(parsed["function_call"], dict):
                        fc = parsed["function_call"]
                    elif "name" in parsed and ("arguments" in parsed or "params" in parsed):
                        fc = {"name": parsed.get("name"), "arguments": parsed.get("arguments") or parsed.get("params")}
                if fc:
                    return SimpleMsg(
                        content=(parsed.get("content") if isinstance(parsed, dict) and "content" in parsed else text),
                        function_call=fc,
                    )
            except Exception:
                # Not JSON or not structured as function_call; fall back to plain text
                pass

            return SimpleMsg(text)
        else:
            logger.warning(f"Gemini client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("mistral:"):
        if mistral_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                text = mistral_generate_text(
                    prompt, model_name=model_short, temperature=0.2, max_tokens=DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    raise
                logger.warning(f"Mistral structured call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
                text = None

            if text is not None:

                class SimpleMsg:
                    def __init__(self, content, function_call=None):
                        self.content = content
                        self.function_call = function_call

                try:
                    parsed = json.loads(text)
                    fc = None
                    if isinstance(parsed, dict):
                        if "function_call" in parsed and isinstance(parsed["function_call"], dict):
                            fc = parsed["function_call"]
                        elif "name" in parsed and ("arguments" in parsed or "params" in parsed):
                            fc = {
                                "name": parsed.get("name"),
                                "arguments": parsed.get("arguments") or parsed.get("params"),
                            }
                    if fc:
                        return SimpleMsg(
                            content=(
                                parsed.get("content") if isinstance(parsed, dict) and "content" in parsed else text
                            ),
                            function_call=fc,
                        )
                except Exception:
                    pass
                return SimpleMsg(text)
        else:
            logger.warning(f"Mistral client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("perplexity:"):
        if perplexity_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                text = perplexity_generate_text(
                    prompt, model_name=model_short, temperature=0.2, max_tokens=DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    raise
                logger.warning(f"Perplexity structured call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
                text = None

            if text is not None:

                class SimpleMsg:
                    def __init__(self, content, function_call=None):
                        self.content = content
                        self.function_call = function_call

                try:
                    parsed = json.loads(text)
                    fc = None
                    if isinstance(parsed, dict):
                        if "function_call" in parsed and isinstance(parsed["function_call"], dict):
                            fc = parsed["function_call"]
                        elif "name" in parsed and ("arguments" in parsed or "params" in parsed):
                            fc = {
                                "name": parsed.get("name"),
                                "arguments": parsed.get("arguments") or parsed.get("params"),
                            }
                    if fc:
                        return SimpleMsg(
                            content=(
                                parsed.get("content") if isinstance(parsed, dict) and "content" in parsed else text
                            ),
                            function_call=fc,
                        )
                except Exception:
                    pass
                return SimpleMsg(text)
        else:
            logger.warning(f"Perplexity client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": DEFAULT_MAX_TOKENS,
            }
            if functions is not None:
                kwargs["functions"] = functions
            if function_call is not None:
                kwargs["function_call"] = function_call

            logger.info(f"Calling structured chat (attempt {attempt + 1}) model={model} functions={bool(functions)}")
            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            return message
        except Exception as e:
            logger.error(f"Error in structured chat (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                raise e


def get_chat_response_deterministic(
    messages: list,
    model_id: str | None = None,
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    gemini_only: bool = False,
) -> str:
    """Call the chat completion with deterministic settings (low temperature) and return the string content.

    Use this helper when the response must be reliably parseable (JSON-only outputs etc.).
    """
    import time

    max_retries = 3
    model = model_id if model_id else DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("gemini:"):
        if gemini_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                return gemini_generate_text(
                    prompt, model_name=model_short, temperature=temperature, max_tokens=max_tokens or DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    logger.error(f"Gemini-only mode enabled and deterministic Gemini call failed: {e}")
                    raise
                logger.warning(f"Gemini deterministic call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Gemini client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("mistral:"):
        if mistral_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                return mistral_generate_text(
                    prompt, model_name=model_short, temperature=temperature, max_tokens=max_tokens or DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    raise
                logger.warning(f"Mistral deterministic call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Mistral client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    if isinstance(model, str) and model.startswith("perplexity:"):
        if perplexity_generate_text:
            model_short = model.split(":", 1)[1]
            prompt = _messages_to_prompt(messages)
            try:
                return perplexity_generate_text(
                    prompt, model_name=model_short, temperature=temperature, max_tokens=max_tokens or DEFAULT_MAX_TOKENS
                )
            except Exception as e:
                env_gemini_only = os.getenv("GEMINI_ONLY", "false").lower() in ("1", "true", "yes")
                strict = bool(gemini_only) or env_gemini_only
                if strict:
                    raise
                logger.warning(f"Perplexity deterministic call failed (falling back to OpenAI): {e}")
                model = DEFAULT_MODEL
        else:
            logger.warning(f"Perplexity client not available; falling back to DEFAULT_MODEL ({DEFAULT_MODEL}).")
            model = DEFAULT_MODEL
    # allow overriding max_tokens but fall back to default
    max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS

    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            logger.info(f"Calling deterministic chat (attempt {attempt + 1}) model={model} temperature={temperature}")
            response = client.chat.completions.create(**kwargs)
            logger.info("Successfully got deterministic response from OpenAI")
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error in deterministic chat (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                raise e


def get_chat_response_json(
    messages: list, schema: dict | None = None, model_id: str | None = None, retries: int = 2, gemini_only: bool = False
) -> dict:
    """Call the deterministic chat wrapper and parse its output as JSON.

    If parsing fails and a schema is provided, retry with a clarifying prompt asking the model
    to return only the JSON matching the schema. Returns the parsed JSON (dict/list).
    Raises ValueError if parsing fails after retries.
    """
    import time

    attempt = 0
    last_err = None
    while attempt <= retries:
        try:
            # Use very low temperature for deterministic output
            text = get_chat_response_deterministic(
                messages, model_id=model_id, temperature=0.0, max_tokens=16000, gemini_only=gemini_only
            )
            # Try to parse JSON directly
            try:
                parsed = json.loads(text)
                return parsed
            except Exception:
                # fallback: try to extract the first JSON object in the text
                import re

                m = re.search(r"\{[\s\S]*\}", text)
                if m:
                    try:
                        parsed = json.loads(m.group(0))
                        return parsed
                    except Exception as e_js:
                        last_err = e_js
                else:
                    last_err = ValueError("No JSON object found in model output")

            # If we have a schema, prompt the model again with a clarifying instruction
            if schema is not None:
                schema_text = json.dumps(schema, ensure_ascii=False)
                clarification = [
                    {
                        "role": "system",
                        "content": "You must reply with a single JSON object that exactly matches the provided schema. Do not include any explanation or text.",
                    },
                    {
                        "role": "user",
                        "content": "The required schema is: "
                        + schema_text
                        + "\nPlease return only the JSON object that conforms to it for the request described previously.",
                    },
                ]
                # Prepend original messages for context, if any
                clar_msgs = (messages if messages else []) + clarification
                text = get_chat_response_deterministic(
                    clar_msgs, model_id=model_id, temperature=0.0, max_tokens=16000, gemini_only=gemini_only
                )
                try:
                    parsed = json.loads(text)
                    return parsed
                except Exception as e_js:
                    last_err = e_js

        except Exception as e:
            last_err = e
        attempt += 1
        time.sleep(1)

    raise ValueError(f"Could not parse JSON from model after {retries + 1} attempts: {last_err}")
