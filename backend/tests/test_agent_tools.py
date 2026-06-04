"""Tests for agent_tools module."""
from unittest.mock import MagicMock
from plugins.base import ActionDefinition


class TestBuildToolsFromPlugins:
    def test_converts_plugin_actions_to_tool_definitions(self):
        from agent_tools import ToolDefinition, build_tools_from_plugins

        mock_manager = MagicMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "gmail"
        mock_plugin.get_actions.return_value = {
            "send_email": ActionDefinition(
                name="send_email", description="Send an email",
                parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
                display_name="Send Email", icon="send", side_effect=True,
            ),
            "search_emails": ActionDefinition(
                name="search_emails", description="Search emails",
                parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                display_name="Search Emails", icon="search", side_effect=False,
            ),
        }
        mock_manager.get_plugin.return_value = mock_plugin
        tools = build_tools_from_plugins(["gmail"], mock_manager)

        assert len(tools) == 2
        by_name = {t.name: t for t in tools}
        assert by_name["send_email"].side_effect is True
        assert by_name["send_email"].plugin_name == "gmail"
        assert by_name["search_emails"].side_effect is False

    def test_skips_unknown_plugin(self):
        from agent_tools import build_tools_from_plugins

        mock_manager = MagicMock()
        mock_manager.get_plugin.return_value = None
        tools = build_tools_from_plugins(["nonexistent"], mock_manager)
        assert tools == []

    def test_tool_definition_prompt_format(self):
        from agent_tools import ToolDefinition

        tool = ToolDefinition(
            name="send_email", description="Send an email",
            parameters_schema={"type": "object", "properties": {"to": {"type": "string"}}, "required": ["to"]},
            plugin_name="gmail", side_effect=True,
        )
        text = tool.to_prompt_str()
        assert "send_email" in text
        assert "Send an email" in text
        assert "to" in text
        assert "confirmation" in text.lower()

    def test_read_tool_prompt_says_lecture(self):
        from agent_tools import ToolDefinition

        tool = ToolDefinition(
            name="search_emails", description="Search emails",
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            plugin_name="gmail", side_effect=False,
        )
        text = tool.to_prompt_str()
        assert "lecture seule" in text.lower()
