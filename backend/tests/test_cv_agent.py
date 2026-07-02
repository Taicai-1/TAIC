import cv_agent
from database import CompanyFolder


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


def test_answer_cv_stream_doc_id_delegates_to_get_answer(monkeypatch):
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
