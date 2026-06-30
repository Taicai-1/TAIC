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
