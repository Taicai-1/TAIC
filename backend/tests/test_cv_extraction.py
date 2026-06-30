import cv_extraction
from cv_extraction import CV_EXTRACTION_SCHEMA, coerce_cv_profile, normalize_skill, normalize_skills


def test_normalize_skill_lowercases_and_trims():
    assert normalize_skill("  ReactJS ") == "react"
    assert normalize_skill("React.js") == "react"
    assert normalize_skill("Node.JS") == "node"
    assert normalize_skill("C++") == "c++"


def test_normalize_skills_dedupes_and_drops_empty():
    assert normalize_skills(["React", "react.js", "", None, "Python"]) == ["react", "python"]
    assert normalize_skills(None) == []
    assert normalize_skills("not a list") == []


def test_coerce_cv_profile_happy_path():
    raw = {
        "full_name": "Jean Dupont",
        "current_title": "Senior Backend Engineer",
        "seniority": "senior",
        "years_experience": "8",          # string -> int
        "skills": ["Python", "react.js"], # normalized
        "languages": ["French", "English"],
        "education_level": "Master",
        "location": "Paris",
        "last_company": "ACME",
        "summary": "Experienced engineer.",
    }
    p = coerce_cv_profile(raw)
    assert p["full_name"] == "Jean Dupont"
    assert p["years_experience"] == 8
    assert p["skills"] == ["python", "react"]
    assert p["languages"] == ["french", "english"]


def test_coerce_cv_profile_handles_missing_and_garbage():
    p = coerce_cv_profile({"years_experience": "n/a", "skills": "Python"})
    assert p["full_name"] is None
    assert p["years_experience"] is None      # unparseable -> None
    assert p["skills"] == []                   # non-list -> []
    assert p["raw_extraction"] == {"years_experience": "n/a", "skills": "Python"}


def test_schema_lists_expected_fields():
    props = CV_EXTRACTION_SCHEMA["properties"]
    for field in ("full_name", "skills", "years_experience", "seniority", "location"):
        assert field in props


def test_extract_cv_metadata_calls_llm_and_coerces(monkeypatch):
    captured = {}

    def fake_json(messages, schema=None, model_id=None, retries=2):
        captured["schema"] = schema
        captured["model_id"] = model_id
        captured["text"] = messages[-1]["content"]
        return {"full_name": "Jane Doe", "years_experience": "5", "skills": ["React"]}

    monkeypatch.setattr(cv_extraction, "get_chat_response_json", fake_json)

    profile = cv_extraction.extract_cv_metadata("CV TEXT HERE", model_id="gpt-4o-mini")

    assert profile["full_name"] == "Jane Doe"
    assert profile["years_experience"] == 5
    assert profile["skills"] == ["react"]
    assert captured["schema"] is cv_extraction.CV_EXTRACTION_SCHEMA
    assert captured["model_id"] == "gpt-4o-mini"
    assert "CV TEXT HERE" in captured["text"]


def test_extract_cv_metadata_truncates_long_text(monkeypatch):
    monkeypatch.setattr(cv_extraction, "get_chat_response_json", lambda *a, **k: {})
    # Should not raise on very long input.
    cv_extraction.extract_cv_metadata("x" * 100_000)
