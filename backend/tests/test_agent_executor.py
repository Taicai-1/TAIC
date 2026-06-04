"""Tests for agent_executor module."""
import json
import pytest


class TestParseLlmOutput:
    """Test the ReAct output parser."""

    def test_parses_final_answer(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Thought: The email has been sent.\nFinal Answer: J'ai envoyé l'email à alice@example.com."
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FinishStep)
        assert "envoyé" in step.answer

    def test_parses_action_step(self):
        from agent_executor import parse_llm_output, ActionStep
        text = (
            'Thought: I need to search for emails from Pierre.\n'
            'Action: search_emails\n'
            'Action Input: {"query": "from:pierre"}'
        )
        step = parse_llm_output(text, ["search_emails", "send_email"])
        assert isinstance(step, ActionStep)
        assert step.tool_name == "search_emails"
        assert step.tool_args == {"query": "from:pierre"}
        assert "Pierre" in step.thought

    def test_parses_action_with_markdown_fenced_json(self):
        from agent_executor import parse_llm_output, ActionStep
        text = (
            'Thought: Sending the email.\n'
            'Action: send_email\n'
            'Action Input: ```json\n{"to": "alice@test.com", "subject": "Hi", "body": "Hello"}\n```'
        )
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, ActionStep)
        assert step.tool_args["to"] == "alice@test.com"

    def test_fallback_on_unformatted_text(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = "Bonjour, je suis votre assistant."
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FallbackStep)
        assert step.text == text

    def test_rejects_unknown_tool_name(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = (
            'Thought: Doing something.\n'
            'Action: nonexistent_tool\n'
            'Action Input: {"foo": "bar"}'
        )
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FallbackStep)

    def test_handles_invalid_json_gracefully(self):
        from agent_executor import parse_llm_output, FallbackStep
        text = (
            'Thought: Sending email.\n'
            'Action: send_email\n'
            'Action Input: {to: alice, subject: test}'
        )
        step = parse_llm_output(text, ["send_email"])
        assert isinstance(step, FallbackStep)

    def test_final_answer_without_thought(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Final Answer: Voici la réponse."
        step = parse_llm_output(text, [])
        assert isinstance(step, FinishStep)
        assert step.answer == "Voici la réponse."

    def test_multiline_final_answer(self):
        from agent_executor import parse_llm_output, FinishStep
        text = "Thought: Done.\nFinal Answer: Ligne 1\nLigne 2\nLigne 3"
        step = parse_llm_output(text, [])
        assert isinstance(step, FinishStep)
        assert "Ligne 1" in step.answer
        assert "Ligne 3" in step.answer


class TestBuildReactPrompt:
    def test_includes_agent_personality(self):
        from agent_executor import build_react_prompt
        from agent_tools import ToolDefinition
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

    def test_includes_tool_descriptions(self):
        from agent_executor import build_react_prompt
        from agent_tools import ToolDefinition
        tools = [
            ToolDefinition(name="send_email", description="Send an email",
                          parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
                          plugin_name="gmail", side_effect=True),
        ]
        prompt = build_react_prompt("Bot", "", "", tools, "")
        assert "send_email" in prompt
        assert "Send an email" in prompt
        assert "confirmation" in prompt.lower()

    def test_includes_rag_context_when_provided(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "Document X says: blah blah")
        assert "Document X says" in prompt

    def test_omits_rag_context_when_empty(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "Contexte documentaire" not in prompt

    def test_includes_react_format_instructions(self):
        from agent_executor import build_react_prompt
        prompt = build_react_prompt("Bot", "", "", [], "")
        assert "Thought:" in prompt
        assert "Action:" in prompt
        assert "Action Input:" in prompt
        assert "Final Answer:" in prompt


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


from unittest.mock import patch, MagicMock, call


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

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    def test_simple_final_answer_no_tools(self, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        mock_rag.return_value = ("", [])
        mock_llm.return_value = "Final Answer: Bonjour, comment puis-je vous aider ?"

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

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    @patch("agent_executor._execute_read_tool")
    @patch("plugins.plugin_manager")
    def test_read_tool_auto_executed(self, mock_pm, mock_exec, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
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
            'Thought: I need to search emails.\nAction: search_emails\nAction Input: {"query": "from:pierre"}',
            'Thought: Found emails.\nFinal Answer: J\'ai trouve 2 emails de Pierre.',
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

    @patch("agent_executor.get_chat_response")
    @patch("agent_executor.get_rag_context")
    @patch("plugins.plugin_manager")
    def test_write_tool_suspends_loop(self, mock_pm, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
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
        mock_llm.return_value = (
            'Thought: I need to send an email.\n'
            'Action: send_email\n'
            'Action Input: {"to": "alice@test.com", "subject": "Hi", "body": "Hello"}'
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

    @patch("agent_executor.get_chat_response")
    def test_resume_after_confirm(self, mock_llm):
        from agent_executor import AgentExecutor, AgentLoopState
        mock_llm.return_value = "Thought: Email sent.\nFinal Answer: J'ai envoye l'email a alice."

        state = AgentLoopState(
            messages=[{"role": "system", "content": "prompt"}, {"role": "user", "content": "Envoie un mail"}],
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
    @patch("agent_executor.get_rag_context")
    def test_max_iterations_forces_answer(self, mock_rag, mock_llm):
        from agent_executor import AgentExecutor
        mock_rag.return_value = ("", [])
        mock_llm.side_effect = [
            'Thought: Searching.\nAction: search_emails\nAction Input: {"query": "test"}',
        ] * 7 + [
            "I'm stuck but here is what I know."
        ]

        executor = AgentExecutor()
        with patch("agent_executor._execute_read_tool") as mock_exec:
            from plugins.base import ActionResult
            mock_exec.return_value = ActionResult(
                success=True, data={"emails": []}, display_message="", resource_url=None, error_message=None,
            )
            result = executor.run(
                question="infinite loop test",
                agent=self._make_agent(),
                history=[], db=MagicMock(), user_id=42, credentials=MagicMock(),
            )
        assert result["answer"] is not None
