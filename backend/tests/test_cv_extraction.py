import cv_extraction
import mistral_embeddings
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
        "years_experience": "8",  # string -> int
        "skills": ["Python", "react.js"],  # normalized
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
    assert p["years_experience"] is None  # unparseable -> None
    assert p["skills"] == []  # non-list -> []
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


def test_get_embeddings_batch_preserves_order_and_uses_cache(monkeypatch):
    # No Redis cache in the test: force misses.
    monkeypatch.setattr(mistral_embeddings, "_get_cached_embedding", lambda t: None)
    monkeypatch.setattr(mistral_embeddings, "_set_cached_embedding", lambda t, e: None)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, inputs):
            # One data item per input, embedding encodes the input length for assertion.
            self.data = [type("D", (), {"embedding": [float(len(s))]})() for s in inputs]

    class _Client:
        class embeddings:
            @staticmethod
            def create(model, inputs):
                calls["n"] += 1
                return _Resp(inputs)

    monkeypatch.setattr(mistral_embeddings, "_get_client", lambda: _Client())

    out = mistral_embeddings.get_embeddings_batch(["a", "bbb", "cc"], batch_size=2)
    assert out == [[1.0], [3.0], [2.0]]  # order preserved
    assert calls["n"] == 2  # 3 items, batch_size 2 -> 2 API calls


def test_get_embeddings_batch_empty():
    assert mistral_embeddings.get_embeddings_batch([]) == []


def test_get_embeddings_batch_mixes_cache_hits_and_misses(monkeypatch):
    # "cc" is a cache hit; the others miss and go to the API.
    def fake_cache_get(t):
        return [99.0] if t == "cc" else None

    monkeypatch.setattr(mistral_embeddings, "_get_cached_embedding", fake_cache_get)
    monkeypatch.setattr(mistral_embeddings, "_set_cached_embedding", lambda t, e: None)

    sent = {"inputs": []}

    class _Resp:
        def __init__(self, inputs):
            self.data = [type("D", (), {"embedding": [float(len(s))]})() for s in inputs]

    class _Client:
        class embeddings:
            @staticmethod
            def create(model, inputs):
                sent["inputs"].extend(inputs)
                return _Resp(inputs)

    monkeypatch.setattr(mistral_embeddings, "_get_client", lambda: _Client())

    out = mistral_embeddings.get_embeddings_batch(["a", "cc", "bbb"])
    # cache hit lands at its original index; misses come from the API, order preserved
    assert out == [[1.0], [99.0], [3.0]]
    # only the misses were sent to the API (the cache hit was NOT re-fetched)
    assert sent["inputs"] == ["a", "bbb"]
