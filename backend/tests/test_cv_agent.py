import pytest

import cv_agent
from database import CandidateProfile, CompanyFolder, Document


def test_folders_include_cv_base(db_session, test_company):
    cv = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    plain = CompanyFolder(company_id=test_company.id, name="Docs", is_cv_base=False)
    db_session.add_all([cv, plain])
    db_session.flush()

    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [cv.id, plain.id]) is True
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, [plain.id]) is False
    # folder_ids=None means "all company folders" -> true because a cv_base exists
    assert cv_agent.folders_include_cv_base(db_session, test_company.id, None) is True
    # no company -> false
    assert cv_agent.folders_include_cv_base(db_session, None, [cv.id]) is False


def test_route_cv_intent_returns_tool(monkeypatch):
    from openai_client import ToolCall, ToolCallResponse

    def fake_tools(messages, tools, model_id=None, gemini_only=False):
        # Assert the three tools are offered.
        names = {t["function"]["name"] for t in tools}
        assert names == {"cv_sourcing", "cv_analytics", "cv_qa"}
        return ToolCallResponse(
            content=None, tool_call=ToolCall(name="cv_analytics", arguments={"metric": "count", "dimension": "skill"})
        )

    monkeypatch.setattr(cv_agent, "get_chat_response_with_tools", fake_tools)
    routed = cv_agent.route_cv_intent("Combien maîtrisent React ?", history=None, model_id="gpt-4o-mini")
    assert routed == ("cv_analytics", {"metric": "count", "dimension": "skill"})


def test_route_cv_intent_no_tool_returns_none(monkeypatch):
    from openai_client import ToolCallResponse

    monkeypatch.setattr(
        cv_agent,
        "get_chat_response_with_tools",
        lambda messages, tools, model_id=None, gemini_only=False: ToolCallResponse(content="hello", tool_call=None),
    )
    assert cv_agent.route_cv_intent("Bonjour", history=None, model_id=None) is None


def test_cv_tools_are_valid_openai_schema():
    for t in cv_agent.CV_TOOLS:
        assert t["type"] == "function"
        assert t["function"]["name"] in {"cv_sourcing", "cv_analytics", "cv_qa"}
        assert t["function"]["parameters"]["type"] == "object"


def test_route_cv_intent_exception_returns_none(monkeypatch):
    def boom(messages, tools, model_id=None, gemini_only=False):
        raise RuntimeError("timeout")

    monkeypatch.setattr(cv_agent, "get_chat_response_with_tools", boom)
    assert cv_agent.route_cv_intent("anything", history=None, model_id=None) is None


def test_answer_cv_dispatches_and_falls_back(monkeypatch):
    # No tool chosen -> None (fallback to RAG).
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: None)
    assert (
        cv_agent.answer_cv("hi", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]) is None
    )

    # A tool chosen -> its handler result is returned.
    monkeypatch.setattr(
        cv_agent,
        "route_cv_intent",
        lambda q, history, model_id: ("cv_analytics", {"metric": "count", "dimension": "skill"}),
    )
    monkeypatch.setattr(cv_agent, "_HANDLERS", {"cv_analytics": lambda args, ctx: {"answer": "42", "sources": []}})
    out = cv_agent.answer_cv("combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
    assert out == {"answer": "42", "sources": []}

    # Handler raises -> None (graceful fallback).
    def boom(args, ctx):
        raise RuntimeError("db down")

    monkeypatch.setattr(cv_agent, "_HANDLERS", {"cv_analytics": boom})
    assert (
        cv_agent.answer_cv("combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
        is None
    )


def test_answer_cv_delegates_via_stream_doc_id(monkeypatch):
    monkeypatch.setattr(
        cv_agent,
        "route_cv_intent",
        lambda q, history, model_id: ("cv_qa", {"candidate_name": "X", "question": "résume"}),
    )
    monkeypatch.setattr(
        cv_agent, "_HANDLERS", {"cv_qa": lambda args, ctx: {"stream_doc_id": 11, "question": "résume X"}}
    )
    captured = {}

    import rag_engine

    def fake_get_answer(question, user_id, db, selected_doc_ids=None, **k):
        captured["docs"] = selected_doc_ids
        captured["q"] = question
        return {"answer": "ok", "sources": [{"document_id": 11}]}

    monkeypatch.setattr(rag_engine, "get_answer", fake_get_answer)
    out = cv_agent.answer_cv("résume X", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
    assert captured["docs"] == [11] and captured["q"] == "résume X"
    assert out["answer"] == "ok"


def test_answer_cv_stream_emits_sse(monkeypatch):
    monkeypatch.setattr(
        cv_agent,
        "route_cv_intent",
        lambda q, history, model_id: ("cv_analytics", {"metric": "count", "dimension": "skill"}),
    )
    monkeypatch.setattr(
        cv_agent, "_HANDLERS", {"cv_analytics": lambda args, ctx: {"answer": "42 profils", "sources": []}}
    )

    gen = cv_agent.answer_cv_stream(
        "combien", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]
    )
    events = list(gen)
    blob = "".join(events)
    assert "42 profils" in blob
    assert "event: done" in blob


def test_answer_cv_stream_none_when_no_tool(monkeypatch):
    monkeypatch.setattr(cv_agent, "route_cv_intent", lambda q, history, model_id: None)
    assert (
        cv_agent.answer_cv_stream("hi", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7])
        is None
    )


def test_answer_cv_stream_delegates_via_stream_doc_id(monkeypatch):
    monkeypatch.setattr(
        cv_agent,
        "route_cv_intent",
        lambda q, history, model_id: ("cv_qa", {"candidate_name": "X", "question": "résume"}),
    )
    monkeypatch.setattr(
        cv_agent, "_HANDLERS", {"cv_qa": lambda args, ctx: {"stream_doc_id": 11, "question": "résume X"}}
    )
    captured = {}

    import rag_engine
    from streaming_response import sse_event

    def fake_stream(question, user_id, db, selected_doc_ids=None, **k):
        captured["docs"] = selected_doc_ids
        yield sse_event("token", {"t": "streamed"})
        yield sse_event("done", {"full_text": "streamed", "sources": [], "graph_data": None})

    monkeypatch.setattr(rag_engine, "get_answer_stream", fake_stream)
    events = list(
        cv_agent.answer_cv_stream(
            "résume X", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]
        )
    )
    assert captured["docs"] == [11]
    assert any("streamed" in e for e in events)


def _cv_doc_with_profile(db_session, test_company, folder_id, name):
    doc = Document(
        filename=f"{name}.pdf",
        content="x",
        user_id=1,
        company_id=test_company.id,
        is_company_rag=True,
        folder_id=folder_id,
    )
    db_session.add(doc)
    db_session.flush()
    prof = CandidateProfile(
        document_id=doc.id,
        company_id=test_company.id,
        folder_id=folder_id,
        full_name=name,
        extraction_status="done",
    )
    db_session.add(prof)
    db_session.flush()
    return doc


def test_find_candidate_by_name(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()
    _cv_doc_with_profile(db_session, test_company, folder.id, "Jean Dupont")
    _cv_doc_with_profile(db_session, test_company, folder.id, "Marie Martin")

    hits = cv_agent.find_candidate_by_name(db_session, test_company.id, [folder.id], "dupont")
    assert len(hits) == 1 and hits[0]["full_name"] == "Jean Dupont"
    assert cv_agent.find_candidate_by_name(db_session, test_company.id, [folder.id], "Nobody") == []
    # tenant isolation: other company sees nothing
    assert cv_agent.find_candidate_by_name(db_session, test_company.id + 999, [folder.id], "dupont") == []


def test_find_candidate_by_name_escapes_like_metachars():
    # A DB-less check that '%' in the name does not become a wildcard: we capture the pattern
    # passed to ilike via a fake query object.
    captured = {}

    class _FakeCol:
        def ilike(self, pattern, escape=None):
            captured["pattern"] = pattern
            captured["escape"] = escape
            return "ilike-clause"

    class _FakeQ:
        def filter(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def all(self):
            return []

    class _FakeDB:
        def query(self, *a, **k):
            return _FakeQ()

    import cv_agent
    from database import CandidateProfile

    # Patch the ORM column's ilike by swapping the attribute lookup: simplest is to monkeypatch
    # CandidateProfile.full_name with a fake exposing .ilike. Use monkeypatch-free manual swap.
    orig = CandidateProfile.full_name
    try:
        CandidateProfile.full_name = _FakeCol()
        cv_agent.find_candidate_by_name(_FakeDB(), 1, None, "50%_off")
    finally:
        CandidateProfile.full_name = orig

    assert captured["escape"] == "\\"
    assert "\\%" in captured["pattern"] and "\\_" in captured["pattern"]


def test_handle_cv_qa_single_candidate_returns_marker(monkeypatch):
    # A single match returns a delegation marker; the orchestrator runs the targeted RAG (no get_answer here).
    monkeypatch.setattr(
        cv_agent,
        "find_candidate_by_name",
        lambda db, cid, fids, name: [{"document_id": 11, "full_name": "Jean Dupont"}],
    )
    ctx = cv_agent._CvContext("résume Jean", 1, None, 2, None, "gpt-4o-mini", 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Jean Dupont", "question": "résume son parcours"}, ctx)
    assert out == {"stream_doc_id": 11, "question": "résume son parcours"}


def test_answer_cv_qa_runs_targeted_rag(monkeypatch):
    # End-to-end: router picks cv_qa, single match -> answer_cv runs get_answer scoped to that doc.
    monkeypatch.setattr(
        cv_agent, "route_cv_intent", lambda q, h, m: ("cv_qa", {"candidate_name": "Jean Dupont", "question": "résume"})
    )
    monkeypatch.setattr(
        cv_agent,
        "find_candidate_by_name",
        lambda db, cid, fids, name: [{"document_id": 11, "full_name": "Jean Dupont"}],
    )
    captured = {}

    import rag_engine

    def fake_get_answer(question, user_id, db, selected_doc_ids=None, **k):
        captured["docs"] = selected_doc_ids
        return {"answer": "Jean is a senior engineer.", "sources": [{"document_id": 11}]}

    monkeypatch.setattr(rag_engine, "get_answer", fake_get_answer)
    out = cv_agent.answer_cv(
        "résume Jean", 1, None, agent_id=2, history=None, model_id=None, company_id=5, folder_ids=[7]
    )
    assert captured["docs"] == [11] and "senior engineer" in out["answer"]


def test_handle_cv_qa_no_candidate(monkeypatch):
    monkeypatch.setattr(cv_agent, "find_candidate_by_name", lambda db, cid, fids, name: [])
    ctx = cv_agent._CvContext("résume X", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Ghost", "question": "?"}, ctx)
    assert "Ghost" in out["answer"] and out["sources"] == []


def test_handle_cv_qa_ambiguous(monkeypatch):
    monkeypatch.setattr(
        cv_agent,
        "find_candidate_by_name",
        lambda db, cid, fids, name: [
            {"document_id": 1, "full_name": "Jean Dupont"},
            {"document_id": 2, "full_name": "Jean Durand"},
        ],
    )
    ctx = cv_agent._CvContext("résume Jean", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_qa({"candidate_name": "Jean", "question": "?"}, ctx)
    assert "Jean Dupont" in out["answer"] and "Jean Durand" in out["answer"]  # asks to disambiguate


def test_cv_qa_registered():
    assert "cv_qa" in cv_agent._HANDLERS


def test_handle_cv_qa_empty_name_returns_none():
    ctx = cv_agent._CvContext("résume ce candidat", 1, None, 2, None, None, 5, [7])
    assert cv_agent._handle_cv_qa({"candidate_name": "", "question": "résume"}, ctx) is None
    assert cv_agent._handle_cv_qa({"question": "résume"}, ctx) is None


def test_rank_candidates_orders_by_criteria_then_vector():
    rows = [
        {"document_id": 1, "matched_skills": ["python"], "similarity": 0.9},
        {"document_id": 2, "matched_skills": ["python", "react"], "similarity": 0.1},
        {"document_id": 3, "matched_skills": [], "similarity": 0.5},
    ]
    ranked = cv_agent._rank_candidates(rows)
    assert [r["document_id"] for r in ranked] == [2, 1, 3]  # more matched skills first, then similarity


def test_search_candidates_filters_and_groups(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    def mk(name, skills, seniority, years):
        doc = Document(
            filename=f"{name}.pdf",
            content="x",
            user_id=1,
            company_id=test_company.id,
            is_company_rag=True,
            folder_id=folder.id,
        )
        db_session.add(doc)
        db_session.flush()
        db_session.add(
            CandidateProfile(
                document_id=doc.id,
                company_id=test_company.id,
                folder_id=folder.id,
                full_name=name,
                skills=skills,
                seniority=seniority,
                years_experience=years,
                extraction_status="done",
            )
        )
        db_session.flush()

    mk("A Py", ["python", "sql"], "senior", 8)
    mk("B React", ["react"], "junior", 1)
    mk("C PyReact", ["python", "react"], "lead", 12)

    res = cv_agent.search_candidates(db_session, test_company.id, [folder.id], skills=["python"], limit=10)
    names = {r["full_name"] for r in res}
    assert names == {"A Py", "C PyReact"}  # both have python; B filtered out
    res2 = cv_agent.search_candidates(db_session, test_company.id, [folder.id], skills=["python"], min_years=10)
    assert {r["full_name"] for r in res2} == {"C PyReact"}


def test_handle_cv_sourcing(monkeypatch):
    monkeypatch.setattr(
        cv_agent,
        "search_candidates",
        lambda db, cid, fids, **kw: [
            {
                "document_id": 3,
                "full_name": "C PyReact",
                "current_title": "Lead",
                "seniority": "lead",
                "years_experience": 12,
                "matched_skills": ["python", "react"],
                "similarity": 0.4,
            },
        ],
    )
    monkeypatch.setattr(cv_agent, "get_embedding_fast", lambda t: [0.0] * 1024)
    monkeypatch.setattr(
        cv_agent, "get_chat_response", lambda messages, model_id=None: "Voici 1 candidat : C PyReact (Lead)."
    )

    ctx = cv_agent._CvContext("trouve des devs python react", 1, None, 2, None, "gpt-4o-mini", 5, [7])
    out = cv_agent._handle_cv_sourcing({"skills": ["python", "react"], "free_text": "dev python react"}, ctx)
    assert "C PyReact" in out["answer"]
    assert out["sources"] and out["sources"][0]["document_id"] == 3


def test_handle_cv_sourcing_no_match(monkeypatch):
    monkeypatch.setattr(cv_agent, "search_candidates", lambda db, cid, fids, **kw: [])
    monkeypatch.setattr(cv_agent, "get_embedding_fast", lambda t: [0.0] * 1024)
    ctx = cv_agent._CvContext("trouve des devs cobol", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_sourcing({"skills": ["cobol"]}, ctx)
    assert "aucun" in out["answer"].lower()


def test_cv_sourcing_registered():
    assert "cv_sourcing" in cv_agent._HANDLERS


def test_handle_cv_sourcing_embedding_failure_falls_back_to_sql(monkeypatch):
    captured = {}

    def boom(t):
        raise RuntimeError("Mistral API down")

    monkeypatch.setattr(cv_agent, "get_embedding_fast", boom)
    monkeypatch.setattr(
        cv_agent,
        "search_candidates",
        lambda db, cid, fids, query_embedding=None, **kw: (
            captured.__setitem__("embedding", query_embedding)
            or [
                {
                    "document_id": 1,
                    "full_name": "A Py",
                    "current_title": "Dev",
                    "seniority": "senior",
                    "years_experience": 5,
                    "matched_skills": ["python"],
                    "similarity": 0.0,
                }
            ]
        ),
    )
    monkeypatch.setattr(cv_agent, "get_chat_response", lambda messages, model_id=None: "A Py est disponible.")
    ctx = cv_agent._CvContext("trouve des devs python", 1, None, 2, None, None, 5, [7])
    out = cv_agent._handle_cv_sourcing({"skills": ["python"], "free_text": "python dev"}, ctx)
    assert captured["embedding"] is None  # embedding was None after the failure
    assert out["sources"][0]["document_id"] == 1  # SQL path still ran


def test_aggregate_rejects_unknown_metric_dimension():
    with pytest.raises(ValueError):
        cv_agent.aggregate_candidates(None, 1, [1], metric="drop_table", dimension="skill")
    with pytest.raises(ValueError):
        cv_agent.aggregate_candidates(None, 1, [1], metric="count", dimension="ssn")


def test_aggregate_candidates_db(db_session, test_company):
    folder = CompanyFolder(company_id=test_company.id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    def mk(name, skills, seniority, years):
        doc = Document(
            filename=f"{name}.pdf",
            content="x",
            user_id=1,
            company_id=test_company.id,
            is_company_rag=True,
            folder_id=folder.id,
        )
        db_session.add(doc)
        db_session.flush()
        db_session.add(
            CandidateProfile(
                document_id=doc.id,
                company_id=test_company.id,
                folder_id=folder.id,
                full_name=name,
                skills=skills,
                seniority=seniority,
                years_experience=years,
                extraction_status="done",
            )
        )
        db_session.flush()

    mk("A", ["python", "sql"], "senior", 8)
    mk("B", ["python"], "junior", 2)
    mk("C", ["react"], "senior", 6)

    by_skill = cv_agent.aggregate_candidates(
        db_session, test_company.id, [folder.id], metric="count", dimension="skill"
    )
    counts = {r["key"]: r["value"] for r in by_skill["rows"]}
    assert counts["python"] == 2 and counts["sql"] == 1 and counts["react"] == 1

    avg = cv_agent.aggregate_candidates(
        db_session, test_company.id, [folder.id], metric="avg_experience", dimension="seniority"
    )
    assert round(avg["rows"][0]["value"]) == round((8 + 2 + 6) / 3)

    dist = cv_agent.aggregate_candidates(
        db_session, test_company.id, [folder.id], metric="distribution", dimension="seniority"
    )
    dcounts = {r["key"]: r["value"] for r in dist["rows"]}
    assert dcounts["senior"] == 2 and dcounts["junior"] == 1
