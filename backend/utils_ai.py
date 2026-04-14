"""
AI/ML utility functions for model output normalization and JSON extraction.
"""

import json
import re
from typing import Any, Optional


def normalize_model_output(obj: Any) -> str:
    """Normalize various model response shapes to a plain text string.

    This is intentionally conservative and only extracts the most common text
    shapes returned by Vertex/Gemini so callers (and the frontend) receive a
    plain string rather than the full provider JSON.

    Args:
        obj: Model response object (dict, str, or object with .content attribute)

    Returns:
        Normalized plain text string
    """
    try:
        if isinstance(obj, str):
            return obj
        if obj is None:
            return ""
        # dict-like shapes from Vertex
        if isinstance(obj, dict):
            # candidates -> content -> parts -> text
            candidates = obj.get("candidates")
            if isinstance(candidates, list) and candidates:
                first = candidates[0]
                if isinstance(first, dict):
                    cont = first.get("content")
                    if isinstance(cont, list) and cont:
                        item = cont[0]
                        if isinstance(item, dict) and "text" in item and isinstance(item["text"], str):
                            return item["text"]
                        if isinstance(item, str):
                            return item
                    if isinstance(cont, dict) and "text" in cont and isinstance(cont["text"], str):
                        return cont["text"]
                    if "text" in first and isinstance(first["text"], str):
                        return first["text"]

            # top-level content
            if "content" in obj and isinstance(obj["content"], str):
                return obj["content"]

            # predictions/output
            preds = obj.get("predictions") or obj.get("output")
            if isinstance(preds, list) and preds:
                p = preds[0]
                if isinstance(p, str):
                    return p
                if isinstance(p, dict) and "content" in p and isinstance(p["content"], str):
                    return p["content"]

        # objects with .content attribute
        if hasattr(obj, "content"):
            c = getattr(obj, "content")
            if isinstance(c, str):
                return c

        return str(obj)
    except Exception:
        try:
            return str(obj)
        except Exception:
            return ""


def extract_json_object_from_text(text: str) -> Optional[dict]:
    """Try to extract and parse the first balanced JSON object from a free-form text blob.

    This is more robust than a single regex because it handles nested braces by
    scanning for a matching closing brace. Returns the parsed JSON object or None.

    Args:
        text: Free-form text that may contain JSON

    Returns:
        Parsed JSON object or None if not found
    """
    if not text or not isinstance(text, str):
        return None
    try:
        # Fast path: try to json.loads the whole text (sometimes model outputs pure JSON)
        try:
            return json.loads(text)
        except Exception:
            pass

        # Find candidate starts for JSON objects and try to parse balanced spans
        starts = [m.start() for m in re.finditer(r"\{", text)]
        for s in starts:
            depth = 0
            for i in range(s, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[s : i + 1]
                        try:
                            return json.loads(candidate)
                        except Exception:
                            # try next possible start
                            break

        # Fallback: try to extract any {...} non-greedy matches and parse them
        for m in re.findall(r"\{[\s\S]*?\}", text):
            try:
                return json.loads(m)
            except Exception:
                continue
    except Exception:
        return None
    return None
