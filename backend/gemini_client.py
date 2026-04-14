import os
import logging
import requests
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

logger = logging.getLogger(__name__)


def _get_project_and_location():
    # Allow overriding via env. Prefer GEMINI_LOCATION, then cloud-run region if available,
    # otherwise fall back to a sensible regional default (us-central1). Using 'global' is
    # incorrect for many publisher models which are regional-only and caused 404s.
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    # Try explicit GEMINI_LOCATION, then CLOUD_RUN_REGION, then GOOGLE_CLOUD_REGION, then default
    location = (
        os.getenv("GEMINI_LOCATION")
        or os.getenv("CLOUD_RUN_REGION")
        or os.getenv("GOOGLE_CLOUD_REGION")
        or "europe-west1"
    )
    return project, location


def generate_text(
    prompt: str,
    model_name: str = "gemini-2.0-flash",
    temperature: float = 0.0,
    max_tokens: int = 16000,
    timeout: int = 30,
) -> str:
    """
    Minimal wrapper to call Vertex AI Generative Models (Gemini) REST API.

    Authentication: this function requires Google Application Default Credentials (ADC).
    It will use an AuthorizedSession (google-auth). The API-key fallback path is
    intentionally disabled to avoid storing/using long-lived keys in production.

    model_name: short model id (e.g., "gemini-medium"), when caller passes 'gemini:NAME' we strip the prefix.
    """
    # normalize model_name if user passed provider prefix
    if isinstance(model_name, str) and model_name.startswith("gemini:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""

    # Map vague names to concrete defaults. This can be overridden with GEMINI_DEFAULT_MODEL env var.
    # Provide aliases for common human-friendly names (e.g., 'flash-lite').
    ALIASES = {
        # human-friendly -> concrete publisher model id. Prefer the stable gemini-2.0-flash model.
        "flash-lite": "gemini-2.0-flash",
        "gemini-flash-lite": "gemini-2.0-flash",
        "gemini-2.0-flash": "gemini-2.0-flash",
        # legacy names
        "chat-bison@001": "chat-bison@001",
        # fallback: use GEMINI_DEFAULT_MODEL env if present, otherwise stable flash
        "default": os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash"),
        "": os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash"),
    }

    # Normalize model_short via aliases if present
    if isinstance(model_short, str):
        ms_lower = model_short.lower()
        if ms_lower in ALIASES:
            model_short = ALIASES[ms_lower]
        # else leave model_short as-is (assume caller provided concrete publisher id)

    project, location = _get_project_and_location()

    def _sanitize_url(u: str) -> str:
        """Remove or redact sensitive query parameters (like 'key') from a URL for safe logging."""
        try:
            p = urlparse(u)
            qs = dict(parse_qsl(p.query, keep_blank_values=True))
            if "key" in qs:
                qs["key"] = "<REDACTED>"
            new_q = urlencode(qs, doseq=True)
            return urlunparse(p._replace(query=new_q))
        except Exception:
            return "<redacted_url>"

    # Try Application Default Credentials flow (google-auth)
    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        # Attempt to get ADC
        credentials, proj = google.auth.default()
        if not project:
            project = proj

        # Helper: detect if we are running on GCP metadata server (rough check)
        def _running_on_gcp_metadata() -> bool:
            try:
                import requests as _req

                resp = _req.get(
                    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/",
                    headers={"Metadata-Flavor": "Google"},
                    timeout=1,
                )
                return resp.status_code == 200
            except Exception:
                return False

        if not credentials:
            # No ADC available — provide richer diagnostic info in the logs
            on_gcp = _running_on_gcp_metadata()
            gac_env = bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
            logger.error(
                "No application default credentials available for Gemini/Vertex ADC. on_gcp=%s GOOGLE_APPLICATION_CREDENTIALS_set=%s",
                on_gcp,
                gac_env,
            )
            raise Exception("No application default credentials available")

        # Log which service account/email we're using if available
        try:
            sa_email = getattr(credentials, "service_account_email", None) or getattr(
                credentials, "_service_account_email", None
            )
            if sa_email:
                logger.info(f"Using ADC service account/email: {sa_email}")
        except Exception:
            # not critical
            pass

        session = AuthorizedSession(credentials)

        # Simplified flow: resolve alias to a versioned model id, use a single region
        # (from GEMINI_LOCATION or default) and call the publisher :generateContent
        # endpoint for Gemini. This function intentionally drops old fallbacks.

        predict_project = project or proj or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not predict_project:
            raise RuntimeError(
                "Unable to determine GCP project for Vertex generateContent URL (set GOOGLE_CLOUD_PROJECT or ensure ADC provides a project id)."
            )

        # Alias mapping (keep minimal mapping here; extend if needed)
        ALIAS_MAP = {
            "gemini-2.0-flash-lite": "gemini-2.0-flash-lite-001",
            "gemini-2.0-flash": "gemini-2.0-flash-001",
            "gemini-1.5-flash": "gemini-1.5-flash@001",
            # map older 2.5 alias to the stable 2.0 flash version to avoid region/model 404s
            "gemini-2.5-flash": "gemini-2.0-flash-001",
        }

        # Resolve model id
        resolved_model = ALIAS_MAP.get(model_short, model_short)
        # If still a plain gemini id without version, append @001 as a sensible default
        if (
            resolved_model
            and resolved_model.lower().startswith("gemini")
            and "@" not in resolved_model
            and "-" not in resolved_model
        ):
            resolved_model = f"{resolved_model}@001"

        # Build the generateContent URL (single region - already in 'location')
        url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{predict_project}/locations/{location}/publishers/google/models/{resolved_model}:generateContent"
        safe_url = _sanitize_url(url)
        logger.info(f"Calling Vertex generateContent: model={resolved_model} url={safe_url}")

        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }

        resp = session.post(url, json=body, timeout=timeout)
        if resp.status_code >= 400:
            try:
                logger.error(f"Vertex generateContent non-2xx status {resp.status_code}: {resp.text}")
            except Exception:
                logger.exception("Failed to read Vertex response body")
        resp.raise_for_status()
        data = resp.json()

        # Minimal parsing: prefer candidates -> content -> parts -> text, else stringify
        candidates = data.get("candidates")
        if isinstance(candidates, list) and len(candidates) > 0:
            first = candidates[0]
            if isinstance(first, dict):
                cont = first.get("content")
                # Newer Gemini shape: content is a dict with 'parts': [{"text": "..."}, ...]
                if isinstance(cont, dict):
                    parts = cont.get("parts") or cont.get("parts")
                    if isinstance(parts, list) and len(parts) > 0:
                        p0 = parts[0]
                        if isinstance(p0, dict) and "text" in p0 and isinstance(p0["text"], str):
                            return p0["text"]
                # Older shape: content as a list (each item may be dict with 'text')
                if isinstance(cont, list) and len(cont) > 0:
                    item = cont[0]
                    if isinstance(item, dict) and "text" in item:
                        return item["text"]
                    if isinstance(item, str):
                        return item
                # Fallback: sometimes the text is directly on the candidate
                if "text" in first and isinstance(first["text"], str):
                    return first["text"]

        # fall back to older shapes
        predictions = data.get("predictions") or data.get("output") or []
        if isinstance(predictions, list) and len(predictions) > 0:
            first = predictions[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                if "content" in first and isinstance(first["content"], str):
                    return first["content"]

        if "content" in data and isinstance(data["content"], str):
            return data["content"]

        # If we got here, try one more pass: sometimes the API returned a structure
        # that we didn't match, or the response was stringified JSON. Attempt to
        # coerce string->json and re-run extraction.
        try:
            import json as _json

            if isinstance(data, str) and data.strip().startswith("{"):
                parsed = _json.loads(data)
                # Try to extract from parsed dict using same logic
                candidates = parsed.get("candidates")
                if isinstance(candidates, list) and candidates:
                    first = candidates[0]
                    cont = first.get("content") if isinstance(first, dict) else None
                    if isinstance(cont, dict):
                        parts = cont.get("parts")
                        if isinstance(parts, list) and parts and isinstance(parts[0], dict) and "text" in parts[0]:
                            return parts[0]["text"]
                # final fallback: return the original string
        except Exception:
            pass

        return str(data)
        # Attempt to extract text from common response shapes
        # Vertex generative models often return predictions[0].content or predictions[0].candidates[0].content
        predictions = data.get("predictions") or data.get("output") or []
        if isinstance(predictions, list) and len(predictions) > 0:
            first = predictions[0]
            if isinstance(first, dict):
                # try several keys
                for key in ("content", "candidates", "text", "output"):
                    if key in first:
                        val = first[key]
                        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "content" in val[0]:
                            return val[0]["content"]
                        if isinstance(val, str):
                            return val
                # fallback: stringify
                return str(first)
            elif isinstance(first, str):
                return first

        # Fallback: try top-level fields
        if "content" in data:
            return data["content"]

        return str(data)

    except Exception as e:
        # Log full exception for ADC attempts so we can see why ADC path failed
        logger.exception(f"Vertex ADC attempt failed: {e}")

        # Provide an enriched error message to aid debugging in runtime
        on_gcp = False
        try:
            import requests as _req

            on_gcp = (
                _req.get(
                    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/",
                    headers={"Metadata-Flavor": "Google"},
                    timeout=1,
                ).status_code
                == 200
            )
        except Exception:
            on_gcp = False

        gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        hint_parts = [f"original_error={repr(e)}"]
        hint_parts.append(f"on_gcp={on_gcp}")
        hint_parts.append(f"GOOGLE_APPLICATION_CREDENTIALS_set={bool(gac)}")
        hint_text = "; ".join(hint_parts)

        raise RuntimeError(
            "No application default credentials found for Gemini/Vertex AI. "
            "Ensure the Cloud Run service account has ADC available (if running on GCP, attach the correct service account to the Cloud Run service) or set GOOGLE_APPLICATION_CREDENTIALS for local testing. "
            "Also ensure the service account has the roles/aiplatform.user role. " + "Debug: " + hint_text
        ) from e


def generate_raw(
    prompt: str,
    model_name: str = "gemini-2.0-flash",
    temperature: float = 0.0,
    max_tokens: int = 16000,
    timeout: int = 30,
) -> dict:
    """Call Vertex generateContent and return the raw JSON response (dict).

    Use this when the caller needs structured data (e.g., to detect function_call objects)
    instead of the simplified text returned by generate_text().
    """
    # reuse much of the same logic as generate_text but return the raw JSON
    if isinstance(model_name, str) and model_name.startswith("gemini:"):
        model_short = model_name.split(":", 1)[1]
    else:
        model_short = model_name or ""

    project, location = _get_project_and_location()

    try:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, proj = google.auth.default()
        if not project:
            project = proj

        if not credentials:
            raise Exception("No application default credentials available")

        session = AuthorizedSession(credentials)

        ALIAS_MAP = {
            "gemini-2.0-flash-lite": "gemini-2.0-flash-lite-001",
            "gemini-2.0-flash": "gemini-2.0-flash-001",
            "gemini-1.5-flash": "gemini-1.5-flash@001",
            "gemini-2.5-flash": "gemini-2.0-flash-001",
        }

        resolved_model = ALIAS_MAP.get(model_short, model_short)
        if (
            resolved_model
            and resolved_model.lower().startswith("gemini")
            and "@" not in resolved_model
            and "-" not in resolved_model
        ):
            resolved_model = f"{resolved_model}@001"

        predict_project = project or proj or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not predict_project:
            raise RuntimeError("Unable to determine GCP project for Vertex generateContent URL")

        url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{predict_project}/locations/{location}/publishers/google/models/{resolved_model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        resp = session.post(url, json=body, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    except Exception as e:
        logger.exception(f"generate_raw ADC attempt failed: {e}")
        raise
