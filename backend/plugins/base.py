"""Base classes for the plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ActionDefinition:
    """Describes a single action a plugin can perform."""

    name: str
    description: str
    parameters_schema: dict
    display_name: str
    icon: str


@dataclass
class ActionResult:
    """Result returned after executing a plugin action."""

    success: bool
    data: dict
    display_message: str
    resource_url: str | None
    error_message: str | None


class BasePlugin(ABC):
    """Abstract base class for all plugins."""

    name: str
    display_name: str
    description: str
    icon: str
    required_scopes: list[str]

    @abstractmethod
    def get_actions(self) -> dict[str, ActionDefinition]:
        """Return all actions this plugin provides."""

    @abstractmethod
    def execute(self, action_name: str, args: dict, credentials) -> ActionResult:
        """Execute an action with the user's Google credentials."""
