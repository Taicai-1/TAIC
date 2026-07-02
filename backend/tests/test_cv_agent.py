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
