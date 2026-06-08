"""Tests for agent_executor module."""
import json
import pytest
from unittest.mock import patch, MagicMock, call


class TestToolConversion:
    """Test ToolDefinition.to_openai_tool() and tools_to_openai_format()."""

    def test_to_openai_tool_format(self):
        from agent_tools import ToolDefinition
        tool = ToolDefinition(
            name="send_email",
            description="Send an email",
            parameters_schema={
                "type": "object",
                "properties": {"to": {"type": "string", "description": "Recipient"}},
                "required": ["to"],
            },
            plugin_name="gmail",
            side_effect=True,
        )
        result = tool.to_openai_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "send_email"
        assert result["function"]["description"] == "Send an email"
        assert result["function"]["parameters"]["required"] == ["to"]

    def test_tools_to_openai_format(self):
        from agent_tools import ToolDefinition, tools_to_openai_format
        tools = [
            ToolDefinition(name="t1", description="d1", parameters_schema={"type": "object"}, plugin_name="p", side_effect=False),
            ToolDefinition(name="t2", description="d2", parameters_schema={"type": "object"}, plugin_name="p", side_effect=True),
        ]
        result = tools_to_openai_format(tools)
        assert len(result) == 2
        assert result[0]["function"]["name"] == "t1"
        assert result[1]["function"]["name"] == "t2"


class TestBuildReactPrompt:
    def test_includes_agent_personality(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt(
            agent_name="TestBot",
            agent_contexte="Tu es un assistant RH.",
            agent_biographie="Expert en recrutement.",
            tools=[],
            rag_context="",
        )
        assert "TestBot" in prompt
        assert "assistant RH" in prompt
        assert "recrutement" in prompt

    def test_includes_rag_context_when_provided(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "Document X says: blah blah")
        assert "Document X says" in prompt

    def test_omits_rag_context_when_empty(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "Contexte documentaire" not in prompt

    def test_no_format_obligatoire(self):
        """The old FORMAT OBLIGATOIRE block should no longer be in the prompt."""
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "FORMAT OBLIGATOIRE" not in prompt
        assert "Thought:" not in prompt
        assert "Action Input:" not in prompt

    def test_includes_rules(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "REGLES" in prompt
        assert "fabrique JAMAIS" in prompt


class TestAgentLoopState:
    def test_serialization_roundtrip(self):
        from agent_executor import AgentLoopState
        state = AgentLoopState(
            messages=[{"role": "system", "content": "test"}],
            iteration=2,
            steps=[{"type": "thought", "content": "thinking"}],
            agent_id=5,
            user_id=42,
            question="send a mail",
            model_id="gemini:gemini-2.0-flash",
            sources=[],
        )
        serialized = state.to_json()
        restored = AgentLoopState.from_json(serialized)
        assert restored.iteration == 2
        assert restored.agent_id == 5
        assert restored.messages == state.messages
        assert restored.question == "send a mail"


class TestAgentExecutorRun:
    """Integration tests for the ReAct loop with mocked LLM."""

    def _make_agent(self, name="TestBot", contexte="", biographie="", enabled_plugins='["gmail"]', agent_type="actionnable"):
        agent = MagicMock()
        agent.id = 1
        agent.name = name
        agent.contexte = contexte
        agent.biographie = biographie
        agent.type = agent_type
        agent.enabled_plugins = enabled_plugins
        agent.company_id = 10
        agent.finetuned_model_id = None
        agent.llm_provider = "gemini"
        return agent

    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    def test_simple_final_answer_no_tool_call(self, mock_rag, mock_llm):
        """When LLM returns content without tool_call, it's a final answer."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse

        mock_rag.return_value = ("", [])
        mock_llm.return_value = ToolCallResponse(
            content="Bonjour, comment puis-je vous aider ?",
            tool_call=None,
        )

        executor = AgentExecutor()
        result = executor.run(
            question="Bonjour",
            agent=self._make_agent(),
            history=[],
            db=MagicMock(),
            user_id=42,
            credentials=MagicMock(),
        )
        assert result["answer"] == "Bonjour, comment puis-je vous aider ?"
        assert result["action_proposal"] is None
        assert result["loop_state"] is None

    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    @patch("agent_executor._execute_read_tool")
    @patch("plugins.plugin_manager")
    def test_read_tool_auto_executed(self, mock_pm, mock_exec, mock_rag, mock_llm):
        """When LLM returns a tool_call for a read-only tool, it's auto-executed."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse, ToolCall
        from plugins.base import ActionResult, ActionDefinition

        # Mock plugin with read-only tool
        mock_plugin = MagicMock()
        mock_plugin.get_actions.return_value = {
            "search_emails": ActionDefinition(
                name="search_emails",
                description="Search emails",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                display_name="Search Emails",
                icon="mail",
                side_effect=False,
            )
        }
        mock_pm.get_plugin.return_value = mock_plugin

        mock_rag.return_value = ("", [])
        mock_llm.side_effect = [
            ToolCallResponse(
                content="Je vais chercher les emails de Pierre.",
                tool_call=ToolCall(name="search_emails", arguments={"query": "from:pierre"}),
            ),
            ToolCallResponse(
                content="J'ai trouve 2 emails de Pierre.",
                tool_call=None,
            ),
        ]
        mock_exec.return_value = ActionResult(
            success=True, data={"emails": [{"subject": "Test"}], "total": 1},
            display_message="Found 1 email", resource_url=None, error_message=None,
        )

        executor = AgentExecutor()
        result = executor.run(
            question="Cherche les mails de Pierre",
            agent=self._make_agent(),
            history=[],
            db=MagicMock(),
            user_id=42,
            credentials=MagicMock(),
        )
        assert "Pierre" in result["answer"]
        assert result["action_proposal"] is None
        mock_exec.assert_called_once()

    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    @patch("plugins.plugin_manager")
    def test_write_tool_suspends_loop(self, mock_pm, mock_rag, mock_llm):
        """When LLM returns a tool_call for a write tool, the loop suspends."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse, ToolCall
        from plugins.base import ActionDefinition

        # Mock plugin with write tool
        mock_plugin = MagicMock()
        mock_plugin.get_actions.return_value = {
            "send_email": ActionDefinition(
                name="send_email",
                description="Send an email",
                parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}},
                display_name="Send Email",
                icon="mail",
                side_effect=True,
            )
        }
        mock_pm.get_plugin.return_value = mock_plugin

        mock_rag.return_value = ("", [])
        mock_llm.return_value = ToolCallResponse(
            content="Je vais envoyer un email.",
            tool_call=ToolCall(name="send_email", arguments={"to": "alice@test.com", "subject": "Hi", "body": "Hello"}),
        )

        mock_db = MagicMock()
        executor = AgentExecutor()
        result = executor.run(
            question="Envoie un mail a alice",
            agent=self._make_agent(),
            history=[],
            db=mock_db,
            user_id=42,
            credentials=MagicMock(),
        )
        assert result["answer"] is None
        assert result["action_proposal"] is not None
        assert result["action_proposal"]["action"] == "send_email"
        assert result["loop_state"] is not None

    @patch("agent_executor.get_chat_response_with_tools")
    def test_resume_after_confirm(self, mock_llm):
        """After confirmation, the loop resumes with the observation and finishes."""
        from agent_executor import AgentExecutor, AgentLoopState
        from openai_client import ToolCallResponse

        mock_llm.return_value = ToolCallResponse(
            content="J'ai envoye l'email a alice.",
            tool_call=None,
        )

        state = AgentLoopState(
            messages=[
                {"role": "system", "content": "prompt"},
                {"role": "user", "content": "Envoie un mail"},
                {"role": "assistant", "content": "Je vais envoyer.", "tool_call": {"name": "send_email", "arguments": {"to": "alice@test.com"}}},
            ],
            iteration=1, steps=[], agent_id=1, user_id=42,
            question="Envoie un mail a alice", model_id="gemini:gemini-2.0-flash", sources=[],
        )

        executor = AgentExecutor()
        result = executor.resume(
            loop_state=state.to_json(),
            observation="Email envoye avec succes (message_id: abc123)",
            db=MagicMock(),
            credentials=MagicMock(),
        )
        assert result["answer"] is not None
        assert "alice" in result["answer"]

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    @patch("agent_executor._execute_read_tool")
    @patch("plugins.plugin_manager")
    def test_max_iterations_forces_answer(self, mock_pm, mock_exec, mock_rag, mock_llm_tools, mock_llm_plain):
        """When max iterations reached, a forced plain text response is used."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse, ToolCall
        from plugins.base import ActionResult, ActionDefinition

        # Mock plugin with read-only tool
        mock_plugin = MagicMock()
        mock_plugin.get_actions.return_value = {
            "search_emails": ActionDefinition(
                name="search_emails",
                description="Search emails",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                display_name="Search Emails",
                icon="mail",
                side_effect=False,
            )
        }
        mock_pm.get_plugin.return_value = mock_plugin

        mock_rag.return_value = ("", [])
        # Every tool call iteration returns a read tool call
        mock_llm_tools.return_value = ToolCallResponse(
            content="Searching.",
            tool_call=ToolCall(name="search_emails", arguments={"query": "test"}),
        )
        mock_exec.return_value = ActionResult(
            success=True, data={"emails": []}, display_message="", resource_url=None, error_message=None,
        )
        # Forced plain text response at the end
        mock_llm_plain.return_value = "Voici ce que je sais."

        executor = AgentExecutor()
        result = executor.run(
            question="infinite loop test",
            agent=self._make_agent(),
            history=[], db=MagicMock(), user_id=42, credentials=MagicMock(),
        )
        assert result["answer"] is not None
        assert result["answer"] == "Voici ce que je sais."

    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    def test_empty_response_returns_error(self, mock_rag, mock_llm):
        """When LLM returns no content and no tool call, return error message."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse

        mock_rag.return_value = ("", [])
        mock_llm.return_value = ToolCallResponse(content=None, tool_call=None)

        executor = AgentExecutor()
        result = executor.run(
            question="Test",
            agent=self._make_agent(),
            history=[], db=MagicMock(), user_id=42, credentials=MagicMock(),
        )
        assert "Désolé" in result["answer"]

    @patch("agent_executor.get_chat_response_with_tools")
    @patch("agent_executor.get_rag_context")
    def test_thought_captured_from_content(self, mock_rag, mock_llm):
        """When LLM returns content alongside a tool call, it's captured as thought."""
        from agent_executor import AgentExecutor
        from openai_client import ToolCallResponse, ToolCall
        from plugins.base import ActionResult

        mock_rag.return_value = ("", [])
        mock_llm.side_effect = [
            ToolCallResponse(
                content="Let me search for that.",
                tool_call=ToolCall(name="search_emails", arguments={"query": "test"}),
            ),
            ToolCallResponse(content="Found results.", tool_call=None),
        ]

        executor = AgentExecutor()
        with patch("agent_executor._execute_read_tool") as mock_exec:
            mock_exec.return_value = ActionResult(
                success=True, data={}, display_message="ok", resource_url=None, error_message=None,
            )
            result = executor.run(
                question="Search",
                agent=self._make_agent(),
                history=[], db=MagicMock(), user_id=42, credentials=MagicMock(),
            )
        # Check that thought was captured in steps
        action_steps = [s for s in result["steps"] if s["type"] == "action"]
        assert len(action_steps) == 1
        assert action_steps[0]["thought"] == "Let me search for that."
