"""CV metadata extraction: pure normalization/coercion + the LLM extraction wrapper
and the CandidateProfile upsert helper. Kept DB-agnostic where possible so the bulk of
the logic is unit-testable without a database or an LLM."""

import logging

from openai_client import get_chat_response_json

logger = logging.getLogger(__name__)

# Cap the text we send to the extractor; CVs are short and this bounds cost/latency.
_MAX_EXTRACT_CHARS = 24000

_EXTRACTION_SYSTEM_PROMPT = (
    "You extract structured data from a single candidate CV. "
    "Return ONLY a JSON object matching the schema. Use null for unknown fields. "
    "skills and languages must be arrays of short lowercase tokens."
)

# Canonical aliases applied AFTER lowercasing + stripping common suffixes.
_SKILL_ALIASES = {
    "reactjs": "react",
    "nodejs": "node",
}
# Suffixes stripped before alias lookup ("react.js" -> "react").
_SKILL_SUFFIXES = (".js", ".net")


def normalize_skill(raw):
    """Lowercase, trim, strip common suffixes, and map known aliases. Returns '' if empty."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip().lower()
    for suf in _SKILL_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    s = _SKILL_ALIASES.get(s, s)
    return s.strip()


def normalize_skills(raw):
    """Normalize a list of skills, dropping empties and de-duplicating (order-preserving)."""
    if not isinstance(raw, list):
        return []
    seen = []
    for item in raw:
        norm = normalize_skill(item)
        if norm and norm not in seen:
            seen.append(norm)
    return seen


CV_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "full_name": {"type": "string"},
        "current_title": {"type": "string"},
        "seniority": {"type": "string", "description": "junior / confirmé / senior / lead"},
        "years_experience": {"type": "integer"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "education_level": {"type": "string"},
        "location": {"type": "string"},
        "last_company": {"type": "string"},
        "summary": {"type": "string"},
    },
}

# Scalar string fields copied through verbatim (trimmed).
_STR_FIELDS = ("full_name", "current_title", "seniority", "education_level", "location", "last_company", "summary")


def _coerce_int(value):
    """Best-effort int coercion. Returns None when not parseable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_str(value):
    if not value or not isinstance(value, str):
        return None
    return value.strip() or None


def coerce_cv_profile(raw):
    """Coerce a raw LLM extraction dict into a clean profile dict with stable types.

    Always preserves the untouched LLM output under ``raw_extraction`` so we can
    re-derive fields later without re-calling the model. Never raises on bad input.
    """
    raw = raw if isinstance(raw, dict) else {}
    profile = {field: _coerce_str(raw.get(field)) for field in _STR_FIELDS}
    profile["years_experience"] = _coerce_int(raw.get("years_experience"))
    profile["skills"] = normalize_skills(raw.get("skills"))
    profile["languages"] = normalize_skills(raw.get("languages"))
    profile["raw_extraction"] = raw
    return profile


def extract_cv_metadata(text, model_id=None):
    """Run one JSON-mode LLM call to extract candidate metadata from CV text.

    Returns a coerced profile dict (see ``coerce_cv_profile``). Raises if the LLM
    call itself fails after its internal retries.
    """
    snippet = (text or "")[:_MAX_EXTRACT_CHARS]
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": "CV:\n" + snippet},
    ]
    raw = get_chat_response_json(messages, schema=CV_EXTRACTION_SCHEMA, model_id=model_id, retries=2)
    return coerce_cv_profile(raw)
