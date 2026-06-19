"""Plugin system: auto-discovery, registration, and lookup."""

from __future__ import annotations

import logging
from typing import Any

from plugins.base import BasePlugin, ActionDefinition

logger = logging.getLogger(__name__)


class PluginManager:
    """Registry for plugins. Provides lookup and function definition generation."""

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance."""
        self._plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin.name} ({plugin.display_name})")

    def get_plugin(self, name: str) -> BasePlugin | None:
        """Get a plugin by name, or None if not found."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[BasePlugin]:
        """Return all registered plugins."""
        return list(self._plugins.values())

    def get_actions_for_plugins(self, plugin_names: list[str]) -> dict[str, dict[str, Any]]:
        """Return combined action map for a set of plugin names.

        Returns dict of action_name -> {"plugin": plugin_name, "definition": ActionDefinition}.
        """
        result = {}
        for pname in plugin_names:
            plugin = self._plugins.get(pname)
            if plugin is None:
                continue
            for action_name, action_def in plugin.get_actions().items():
                result[action_name] = {"plugin": pname, "definition": action_def}
        return result

    def get_function_definitions(self, plugin_names: list[str]) -> list[dict]:
        """Generate Gemini-compatible function definitions for the given plugins.

        Returns a list of dicts with 'name', 'description', 'parameters'.
        """
        definitions = []
        for pname in plugin_names:
            plugin = self._plugins.get(pname)
            if plugin is None:
                continue
            for action_name, action_def in plugin.get_actions().items():
                definitions.append(
                    {
                        "name": action_def.name,
                        "description": action_def.description,
                        "parameters": action_def.parameters_schema,
                    }
                )
        return definitions


# Global singleton — populated at startup by discover_plugins()
plugin_manager = PluginManager()


def discover_plugins() -> None:
    """Import all plugin subpackages and register their plugins."""
    import importlib
    import pkgutil
    import plugins as plugins_pkg

    for importer, modname, ispkg in pkgutil.iter_modules(plugins_pkg.__path__):
        if not ispkg:
            continue
        try:
            mod = importlib.import_module(f"plugins.{modname}")
            plugin_cls = getattr(mod, "plugin_class", None)
            if plugin_cls and issubclass(plugin_cls, BasePlugin):
                plugin_manager.register(plugin_cls())
                logger.info(f"Auto-discovered plugin: {modname}")
        except Exception:
            logger.exception(f"Failed to load plugin: {modname}")
