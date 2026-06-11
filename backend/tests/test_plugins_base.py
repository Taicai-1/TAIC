"""Tests for the plugin system base classes and manager."""

import pytest
from plugins.base import BasePlugin, ActionDefinition, ActionResult


class FakePlugin(BasePlugin):
    name = "fake"
    display_name = "Fake Plugin"
    description = "A fake plugin for testing"
    icon = "fake-icon"
    required_scopes = ["https://www.googleapis.com/auth/fake"]

    def get_actions(self):
        return {
            "do_thing": ActionDefinition(
                name="do_thing",
                description="Does a thing",
                parameters_schema={
                    "type": "object",
                    "properties": {"input": {"type": "string"}},
                    "required": ["input"],
                },
                display_name="Do Thing",
                icon="zap",
            )
        }

    def execute(self, action_name, args, credentials):
        if action_name == "do_thing":
            return ActionResult(
                success=True,
                data={"output": args["input"].upper()},
                display_message=f"Did the thing: {args['input'].upper()}",
                resource_url=None,
                error_message=None,
            )
        return ActionResult(
            success=False,
            data={},
            display_message="",
            resource_url=None,
            error_message=f"Unknown action: {action_name}",
        )


class TestActionDefinition:
    def test_fields(self):
        ad = ActionDefinition(
            name="test", description="desc", parameters_schema={"type": "object"}, display_name="Test", icon="icon"
        )
        assert ad.name == "test"
        assert ad.description == "desc"
        assert ad.parameters_schema == {"type": "object"}
        assert ad.display_name == "Test"
        assert ad.icon == "icon"


class TestActionResult:
    def test_success_result(self):
        r = ActionResult(
            success=True, data={"key": "val"}, display_message="ok", resource_url="http://x", error_message=None
        )
        assert r.success is True
        assert r.resource_url == "http://x"

    def test_failure_result(self):
        r = ActionResult(success=False, data={}, display_message="", resource_url=None, error_message="boom")
        assert r.success is False
        assert r.error_message == "boom"


class TestBasePlugin:
    def test_fake_plugin_get_actions(self):
        p = FakePlugin()
        actions = p.get_actions()
        assert "do_thing" in actions
        assert actions["do_thing"].name == "do_thing"

    def test_fake_plugin_execute(self):
        p = FakePlugin()
        result = p.execute("do_thing", {"input": "hello"}, credentials=None)
        assert result.success is True
        assert result.data == {"output": "HELLO"}

    def test_fake_plugin_execute_unknown(self):
        p = FakePlugin()
        result = p.execute("unknown", {}, credentials=None)
        assert result.success is False
        assert "Unknown action" in result.error_message


class TestPluginManager:
    def test_register_and_get(self):
        from plugins import PluginManager

        mgr = PluginManager()
        mgr.register(FakePlugin())
        assert mgr.get_plugin("fake") is not None
        assert mgr.get_plugin("fake").display_name == "Fake Plugin"

    def test_get_unknown_returns_none(self):
        from plugins import PluginManager

        mgr = PluginManager()
        assert mgr.get_plugin("nonexistent") is None

    def test_list_plugins(self):
        from plugins import PluginManager

        mgr = PluginManager()
        mgr.register(FakePlugin())
        plugins = mgr.list_plugins()
        assert len(plugins) == 1
        assert plugins[0].name == "fake"

    def test_get_actions_for_plugins(self):
        from plugins import PluginManager

        mgr = PluginManager()
        mgr.register(FakePlugin())
        actions = mgr.get_actions_for_plugins(["fake"])
        assert "do_thing" in actions
        assert actions["do_thing"]["plugin"] == "fake"

    def test_get_actions_for_plugins_ignores_unknown(self):
        from plugins import PluginManager

        mgr = PluginManager()
        mgr.register(FakePlugin())
        actions = mgr.get_actions_for_plugins(["fake", "nonexistent"])
        assert len(actions) == 1

    def test_get_function_definitions(self):
        from plugins import PluginManager

        mgr = PluginManager()
        mgr.register(FakePlugin())
        defs = mgr.get_function_definitions(["fake"])
        assert len(defs) == 1
        assert defs[0]["name"] == "do_thing"
        assert "parameters" in defs[0]
