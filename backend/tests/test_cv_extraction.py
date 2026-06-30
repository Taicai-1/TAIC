from cv_extraction import normalize_skill, normalize_skills


def test_normalize_skill_lowercases_and_trims():
    assert normalize_skill("  ReactJS ") == "react"
    assert normalize_skill("React.js") == "react"
    assert normalize_skill("Node.JS") == "node"
    assert normalize_skill("C++") == "c++"


def test_normalize_skills_dedupes_and_drops_empty():
    assert normalize_skills(["React", "react.js", "", None, "Python"]) == ["react", "python"]
    assert normalize_skills(None) == []
    assert normalize_skills("not a list") == []
