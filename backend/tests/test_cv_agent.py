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
