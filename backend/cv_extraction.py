"""CV metadata extraction: pure normalization/coercion + the LLM extraction wrapper
and the CandidateProfile upsert helper. Kept DB-agnostic where possible so the bulk of
the logic is unit-testable without a database or an LLM."""

import logging

logger = logging.getLogger(__name__)

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
