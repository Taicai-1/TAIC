"""Integration tests for POST /ask endpoint."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_event_tracker")
async def test_ask_with_agent_id_returns_mocked_answer(client, test_user, test_agent, auth_cookies):
    """POST /ask with agent_id returns mocked answer from get_answer."""
    with patch("routers.ask.get_answer", return_value="This is a mocked RAG answer."):
        response = await client.post(
            "/ask",
            json={
                "question": "What is RAG?",
                "agent_id": test_agent.id,
                "selected_documents": [],
            },
            cookies=auth_cookies,
        )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert data["answer"] == "This is a mocked RAG answer."


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_event_tracker")
async def test_ask_without_agent_or_team_returns_error(client, test_user, auth_cookies):
    """POST /ask without agent_id or team_id returns 400 error."""
    response = await client.post(
        "/ask",
        json={
            "question": "What is RAG?",
            "selected_documents": [],
        },
        cookies=auth_cookies,
    )

    # According to the code, if neither agent_id nor team_id is provided,
    # answer remains None and raises HTTPException 400
    assert response.status_code == 400
    data = response.json()
    assert "detail" in data
    assert "agent" in data["detail"].lower() or "équipe" in data["detail"].lower()


@pytest.mark.asyncio
async def test_ask_unauthenticated_returns_401(client, test_agent):
    """POST /ask without authentication returns 401."""
    response = await client.post(
        "/ask",
        json={
            "question": "What is RAG?",
            "agent_id": test_agent.id,
            "selected_documents": [],
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_ask_with_empty_question_returns_422(client, test_user, test_agent, auth_cookies):
    """POST /ask with empty question returns 422 validation error."""
    response = await client.post(
        "/ask",
        json={
            "question": "",
            "agent_id": test_agent.id,
            "selected_documents": [],
        },
        cookies=auth_cookies,
    )

    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
@pytest.mark.usefixtures("mock_event_tracker")
async def test_ask_with_conversation_id_includes_history(
    client, test_user, test_agent, test_conversation, auth_cookies, db_session
):
    """POST /ask with conversation_id retrieves and uses conversation history."""
    # Create some messages in the conversation
    from database import Message

    msg1 = Message(
        conversation_id=test_conversation.id,
        role="user",
        content="Previous user question",
    )
    msg2 = Message(
        conversation_id=test_conversation.id,
        role="assistant",
        content="Previous assistant response",
    )
    db_session.add(msg1)
    db_session.add(msg2)
    db_session.flush()

    with patch("routers.ask.get_answer", return_value="New answer with history.") as mock_get_answer:
        response = await client.post(
            "/ask",
            json={
                "question": "Follow-up question",
                "agent_id": test_agent.id,
                "conversation_id": test_conversation.id,
                "selected_documents": [],
            },
            cookies=auth_cookies,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "New answer with history."

    # Verify get_answer was called with history
    assert mock_get_answer.called
    call_kwargs = mock_get_answer.call_args[1]
    assert "history" in call_kwargs
    history = call_kwargs["history"]
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Previous user question"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Previous assistant response"
