"""Convert plugin actions into tool definitions for the ReAct agent."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins import PluginManager


@dataclass
class ToolDefinition:
    """A tool available to the ReAct agent."""

    name: str
    description: str
    parameters_schema: dict
    plugin_name: str
    side_effect: bool  # True = write (needs confirmation), False = read-only
    display_name: str = ""  # Human-readable name for UI display

    def to_openai_tool(self) -> dict:
        """Convert to OpenAI function-calling tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def to_prompt_str(self) -> str:
        """Format this tool for inclusion in the ReAct system prompt."""
        params_desc = []
        props = self.parameters_schema.get("properties", {})
        required = set(self.parameters_schema.get("required", []))
        for pname, pinfo in props.items():
            req_mark = " (obligatoire)" if pname in required else " (optionnel)"
            desc = pinfo.get("description", "")
            params_desc.append(f"    - {pname}: {desc}{req_mark}")
        params_text = "\n".join(params_desc) if params_desc else "    (aucun parametre)"
        side_label = "action (necessite confirmation)" if self.side_effect else "lecture seule"
        return (
            f"- {self.name}: {self.description}\n"
            f"  Type: {side_label}\n"
            f"  Parametres:\n{params_text}"
        )


def tools_to_openai_format(tools: list["ToolDefinition"]) -> list[dict]:
    """Convert a list of ToolDefinitions to OpenAI function-calling format."""
    return [t.to_openai_tool() for t in tools]


def build_tools_from_plugins(
    plugin_names: list[str], manager: "PluginManager"
) -> list[ToolDefinition]:
    """Build ToolDefinition list from enabled plugin names."""
    tools: list[ToolDefinition] = []
    for pname in plugin_names:
        plugin = manager.get_plugin(pname)
        if plugin is None:
            continue
        for action_name, action_def in plugin.get_actions().items():
            tools.append(
                ToolDefinition(
                    name=action_def.name,
                    description=action_def.description,
                    parameters_schema=action_def.parameters_schema,
                    plugin_name=pname,
                    side_effect=action_def.side_effect,
                    display_name=action_def.display_name,
                )
            )
    return tools
