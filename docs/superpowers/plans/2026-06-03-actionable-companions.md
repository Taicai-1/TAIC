# Actionable Companions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a plugin-based system enabling AI agents to execute Google Workspace actions (Docs, Sheets, Gmail, Calendar, Slides, Drive) with OAuth2 user authentication and mandatory confirmation before every action.

**Architecture:** Plugin system with `BasePlugin` ABC, auto-discovery via `PluginManager`, two-stage LLM pipeline (Mistral for RAG + Gemini for function calling), action proposals requiring user confirmation, and OAuth2 per-user Google tokens stored encrypted.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, google-api-python-client, google-auth, google-auth-oauthlib, Fernet encryption, Next.js 14, React 18, Tailwind CSS

---

## File Map

### New Files — Backend

| File | Responsibility |
|------|---------------|
| `backend/plugins/__init__.py` | `PluginManager` class: auto-discovery, registration, lookup |
| `backend/plugins/base.py` | `BasePlugin` ABC, `ActionDefinition`, `ActionResult` dataclasses |
| `backend/plugins/google_docs/__init__.py` | `GoogleDocsPlugin(BasePlugin)` class |
| `backend/plugins/google_docs/actions.py` | `create_doc`, `update_doc`, `share_doc` implementations |
| `backend/plugins/google_docs/schemas.py` | JSON function-calling schemas for Docs actions |
| `backend/plugins/google_sheets/__init__.py` | `GoogleSheetsPlugin(BasePlugin)` class |
| `backend/plugins/google_sheets/actions.py` | `create_sheet`, `update_sheet`, `read_sheet` implementations |
| `backend/plugins/google_sheets/schemas.py` | JSON function-calling schemas for Sheets actions |
| `backend/plugins/gmail/__init__.py` | `GmailPlugin(BasePlugin)` class |
| `backend/plugins/gmail/actions.py` | `send_email`, `reply_email`, `search_emails` implementations |
| `backend/plugins/gmail/schemas.py` | JSON function-calling schemas for Gmail actions |
| `backend/plugins/google_calendar/__init__.py` | `GoogleCalendarPlugin(BasePlugin)` class |
| `backend/plugins/google_calendar/actions.py` | `create_event`, `list_events`, `update_event` implementations |
| `backend/plugins/google_calendar/schemas.py` | JSON function-calling schemas for Calendar actions |
| `backend/plugins/google_slides/__init__.py` | `GoogleSlidesPlugin(BasePlugin)` class |
| `backend/plugins/google_slides/actions.py` | `create_presentation`, `add_slide` implementations |
| `backend/plugins/google_slides/schemas.py` | JSON function-calling schemas for Slides actions |
| `backend/plugins/google_drive/__init__.py` | `GoogleDrivePlugin(BasePlugin)` class |
| `backend/plugins/google_drive/actions.py` | `create_folder`, `move_file`, `share_file`, `search_files` implementations |
| `backend/plugins/google_drive/schemas.py` | JSON function-calling schemas for Drive actions |
| `backend/routers/google_auth.py` | OAuth2 endpoints: `/auth/google/authorize`, `/callback`, `/status`, `/revoke` |
| `backend/routers/plugins.py` | Plugin listing endpoints: `GET /plugins`, `GET /plugins/{name}/actions` |
| `backend/routers/action_executions.py` | Action endpoints: `POST /actions/{id}/confirm`, `/cancel`, `GET /actions/{id}` |
| `backend/google_credentials.py` | Helper to load/refresh Google OAuth2 credentials from DB |
| `backend/alembic/versions/0004_actionable_companions.py` | Migration: `user_google_tokens`, `action_executions`, `agents.enabled_plugins` |
| `backend/tests/test_plugins_base.py` | Unit tests for BasePlugin, PluginManager |
| `backend/tests/test_google_auth.py` | Unit tests for OAuth2 flow |
| `backend/tests/test_action_executions.py` | Unit tests for confirm/cancel/status endpoints |
| `backend/tests/test_plugin_google_docs.py` | Unit tests for Google Docs plugin |
| `backend/tests/test_plugin_gmail.py` | Unit tests for Gmail plugin |
| `backend/tests/test_plugin_google_calendar.py` | Unit tests for Google Calendar plugin |
| `backend/tests/test_plugin_google_sheets.py` | Unit tests for Google Sheets plugin |
| `backend/tests/test_plugin_google_slides.py` | Unit tests for Google Slides plugin |
| `backend/tests/test_plugin_google_drive.py` | Unit tests for Google Drive plugin |
| `backend/tests/test_ask_actionnable.py` | Integration tests for the two-stage pipeline |

### New Files — Frontend

| File | Responsibility |
|------|---------------|
| `frontend/components/PluginSelector.js` | Plugin cards grid component with toggles for agent creation |
| `frontend/components/ActionProposal.js` | Action proposal block in chat with confirm/cancel buttons |
| `frontend/components/GoogleConnectButton.js` | "Connect Google" button with OAuth popup flow |

### Modified Files

| File | Changes |
|------|---------|
| `backend/database.py` | Add `UserGoogleToken`, `ActionExecution` models; add `enabled_plugins` column to `Agent` |
| `backend/helpers/agent_helpers.py` | Add `"actionnable"` to type maps (provider = `"gemini"`) |
| `backend/routers/agents.py` | Accept `enabled_plugins` field in create/update agent |
| `backend/routers/ask.py` | Add Stage 2 action detection for actionnable agents after RAG response |
| `backend/main.py` | Register new routers: `google_auth`, `plugins`, `action_executions` |
| `backend/requirements.txt` | Add `google-auth-oauthlib==1.2.1` |
| `backend/tests/factories.py` | Add `ActionExecutionFactory`, `UserGoogleTokenFactory` |
| `frontend/pages/agents.js` | Add "actionnable" to type dropdown, show `PluginSelector` when type is actionnable |
| `frontend/pages/chat/[agentId].js` | Render `ActionProposal` component when `action_proposal` is in response |
| `frontend/public/locales/en/agents.json` | Add `types.actionnable` i18n |
| `frontend/public/locales/fr/agents.json` | Add `types.actionnable` i18n |
| `frontend/public/locales/en/chat.json` | Add `actions.*` i18n keys |
| `frontend/public/locales/fr/chat.json` | Add `actions.*` i18n keys |

---

## Task 1: Plugin Base Classes and PluginManager

**Files:**
- Create: `backend/plugins/__init__.py`
- Create: `backend/plugins/base.py`
- Test: `backend/tests/test_plugins_base.py`

- [ ] **Step 1: Write the failing test for BasePlugin and PluginManager**

```python
# backend/tests/test_plugins_base.py
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
            success=False, data={}, display_message="", resource_url=None, error_message=f"Unknown action: {action_name}"
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
        r = ActionResult(success=True, data={"key": "val"}, display_message="ok", resource_url="http://x", error_message=None)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_plugins_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins'`

- [ ] **Step 3: Implement base.py**

```python
# backend/plugins/base.py
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
```

- [ ] **Step 4: Implement PluginManager in __init__.py**

```python
# backend/plugins/__init__.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_plugins_base.py -v`
Expected: All 10 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/plugins/__init__.py backend/plugins/base.py backend/tests/test_plugins_base.py
git commit -m "feat(plugins): add BasePlugin ABC and PluginManager with auto-discovery"
```

---

## Task 2: Database Models and Migration

**Files:**
- Modify: `backend/database.py`
- Create: `backend/alembic/versions/0004_actionable_companions.py`
- Modify: `backend/tests/factories.py`
- Modify: `backend/helpers/agent_helpers.py`

- [ ] **Step 1: Add `enabled_plugins` column to Agent model**

In `backend/database.py`, after line 317 (the `recap_hour` field), add:

```python
    # Actionnable plugins
    enabled_plugins = Column(Text, nullable=True)  # JSON array: ["google_docs", "gmail", ...]
```

- [ ] **Step 2: Add UserGoogleToken model**

In `backend/database.py`, after the `Agent` class (after line 329), add:

```python
class UserGoogleToken(Base):
    __tablename__ = "user_google_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    _access_token = Column("access_token", Text, nullable=False)
    _refresh_token = Column("refresh_token", Text, nullable=False)
    token_expiry = Column(DateTime, nullable=False)
    granted_scopes = Column(Text, nullable=False)  # JSON array of scope strings
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    @property
    def access_token(self):
        from encryption import decrypt_value
        return decrypt_value(self._access_token)

    @access_token.setter
    def access_token(self, value):
        from encryption import encrypt_value
        self._access_token = encrypt_value(value)

    @property
    def refresh_token(self):
        from encryption import decrypt_value
        return decrypt_value(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value):
        from encryption import encrypt_value
        self._refresh_token = encrypt_value(value)
```

- [ ] **Step 3: Add ActionExecution model**

In `backend/database.py`, after the `UserGoogleToken` class, add:

```python
class ActionExecution(Base):
    __tablename__ = "action_executions"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    plugin_name = Column(String(64), nullable=False)
    action_name = Column(String(64), nullable=False)
    action_params = Column(Text, nullable=False)  # JSON
    status = Column(String(32), nullable=False, default="pending_confirmation")
    result = Column(Text, nullable=True)  # JSON
    error_message = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", foreign_keys=[agent_id])
    user = relationship("User", foreign_keys=[user_id])
```

- [ ] **Step 4: Add `actionnable` to agent type helpers**

In `backend/helpers/agent_helpers.py`, modify the maps:

```python
_AGENT_TYPE_MODEL_MAP = {
    "recherche_live": ("PERPLEXITY_MODEL", "perplexity:sonar"),
    "visuel": (None, "imagen:imagen-3.0-generate-002"),
    "actionnable": ("GEMINI_MODEL", "gemini:gemini-2.0-flash"),
}

_AGENT_TYPE_PROVIDER_MAP = {
    "recherche_live": "perplexity",
    "visuel": "imagen",
    "actionnable": "gemini",
}
```

- [ ] **Step 5: Create Alembic migration**

```python
# backend/alembic/versions/0004_actionable_companions.py
"""add actionable companions tables and fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add enabled_plugins to agents
    op.add_column("agents", sa.Column("enabled_plugins", sa.Text(), nullable=True))

    # Create user_google_tokens table
    op.create_table(
        "user_google_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expiry", sa.DateTime(), nullable=False),
        sa.Column("granted_scopes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_user_google_tokens_user_id", "user_google_tokens", ["user_id"], unique=True)

    # Create action_executions table
    op.create_table(
        "action_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        sa.Column("plugin_name", sa.String(64), nullable=False),
        sa.Column("action_name", sa.String(64), nullable=False),
        sa.Column("action_params", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending_confirmation"),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_action_executions_agent", "action_executions", ["agent_id"])
    op.create_index("idx_action_executions_user", "action_executions", ["user_id"])
    op.create_index("idx_action_executions_status", "action_executions", ["status"])


def downgrade() -> None:
    op.drop_table("action_executions")
    op.drop_table("user_google_tokens")
    op.drop_column("agents", "enabled_plugins")
```

- [ ] **Step 6: Update test factories**

In `backend/tests/factories.py`, add at the bottom:

```python
from database import ActionExecution, UserGoogleToken


class ActionExecutionFactory(factory.Factory):
    class Meta:
        model = ActionExecution

    plugin_name = "google_docs"
    action_name = "create_doc"
    action_params = '{"title": "Test Doc"}'
    status = "pending_confirmation"


class UserGoogleTokenFactory(factory.Factory):
    class Meta:
        model = UserGoogleToken

    _access_token = "test-access-token"
    _refresh_token = "test-refresh-token"
    token_expiry = factory.LazyFunction(lambda: __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(hours=1))
    granted_scopes = '["https://www.googleapis.com/auth/documents"]'
```

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/helpers/agent_helpers.py backend/alembic/versions/0004_actionable_companions.py backend/tests/factories.py
git commit -m "feat(db): add UserGoogleToken, ActionExecution models and actionnable agent type"
```

---

## Task 3: Google OAuth2 Credentials Helper

**Files:**
- Create: `backend/google_credentials.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_google_auth.py` (partial — credential helper tests)

- [ ] **Step 1: Add google-auth-oauthlib to requirements**

In `backend/requirements.txt`, add:

```
google-auth-oauthlib==1.2.1
```

- [ ] **Step 2: Write the failing test for credentials helper**

```python
# backend/tests/test_google_auth.py
"""Tests for Google OAuth2 credential management."""

import json
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestGetGoogleCredentials:
    def test_returns_none_when_no_token(self, db_session, test_user):
        from google_credentials import get_google_credentials

        creds = get_google_credentials(test_user.id, db_session)
        assert creds is None

    def test_returns_credentials_when_token_exists(self, db_session, test_user):
        from database import UserGoogleToken

        token = UserGoogleToken(
            user_id=test_user.id,
            token_expiry=datetime.utcnow() + timedelta(hours=1),
            granted_scopes=json.dumps(["https://www.googleapis.com/auth/documents"]),
        )
        token.access_token = "valid-access-token"
        token.refresh_token = "valid-refresh-token"
        db_session.add(token)
        db_session.flush()

        from google_credentials import get_google_credentials

        creds = get_google_credentials(test_user.id, db_session)
        assert creds is not None
        assert creds.token == "valid-access-token"

    def test_refreshes_expired_token(self, db_session, test_user):
        from database import UserGoogleToken

        token = UserGoogleToken(
            user_id=test_user.id,
            token_expiry=datetime.utcnow() - timedelta(hours=1),  # expired
            granted_scopes=json.dumps(["https://www.googleapis.com/auth/documents"]),
        )
        token.access_token = "expired-token"
        token.refresh_token = "valid-refresh-token"
        db_session.add(token)
        db_session.flush()

        with patch("google_credentials.google_requests.Request") as mock_request:
            mock_req_instance = MagicMock()
            mock_request.return_value = mock_req_instance

            from google_credentials import get_google_credentials

            with patch("google.oauth2.credentials.Credentials") as MockCreds:
                mock_cred = MagicMock()
                mock_cred.token = "new-access-token"
                mock_cred.expiry = datetime.utcnow() + timedelta(hours=1)
                mock_cred.expired = True
                mock_cred.valid = False
                mock_cred.refresh_token = "valid-refresh-token"
                MockCreds.return_value = mock_cred

                creds = get_google_credentials(test_user.id, db_session)
                # Should attempt refresh
                assert creds is not None


class TestCheckScopesCovered:
    def test_all_scopes_covered(self):
        from google_credentials import check_scopes_covered

        granted = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive.file"]
        required = ["https://www.googleapis.com/auth/documents"]
        assert check_scopes_covered(granted, required) is True

    def test_missing_scopes(self):
        from google_credentials import check_scopes_covered

        granted = ["https://www.googleapis.com/auth/documents"]
        required = ["https://www.googleapis.com/auth/gmail.send"]
        assert check_scopes_covered(granted, required) is False

    def test_empty_required(self):
        from google_credentials import check_scopes_covered

        assert check_scopes_covered([], []) is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_google_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'google_credentials'`

- [ ] **Step 4: Implement google_credentials.py**

```python
# backend/google_credentials.py
"""Google OAuth2 credential management: load, refresh, and scope checking."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.transport import requests as google_requests
from sqlalchemy.orm import Session

from database import UserGoogleToken

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
TOKEN_URI = "https://oauth2.googleapis.com/token"


def get_google_credentials(user_id: int, db: Session) -> Credentials | None:
    """Load Google OAuth2 credentials for a user. Refreshes if expired.

    Returns None if the user has no stored token.
    """
    token_row = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == user_id).first()
    if token_row is None:
        return None

    granted = json.loads(token_row.granted_scopes) if token_row.granted_scopes else []

    creds = Credentials(
        token=token_row.access_token,
        refresh_token=token_row.refresh_token,
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=granted,
    )

    # Check if token is expired and refresh
    if token_row.token_expiry < datetime.utcnow():
        try:
            creds.refresh(google_requests.Request())
            # Update stored token
            token_row.access_token = creds.token
            token_row.token_expiry = creds.expiry or (datetime.utcnow() + timedelta(hours=1))
            token_row.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"Refreshed Google token for user {user_id}")
        except Exception:
            logger.exception(f"Failed to refresh Google token for user {user_id}")
            return None

    return creds


def check_scopes_covered(granted_scopes: list[str], required_scopes: list[str]) -> bool:
    """Check if all required scopes are covered by the granted scopes."""
    return set(required_scopes).issubset(set(granted_scopes))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_google_auth.py -v`
Expected: PASS (some tests may skip if DB is unavailable — that's expected)

- [ ] **Step 6: Commit**

```bash
git add backend/google_credentials.py backend/requirements.txt backend/tests/test_google_auth.py
git commit -m "feat(auth): add Google OAuth2 credential helper with token refresh"
```

---

## Task 4: Google OAuth2 Router

**Files:**
- Create: `backend/routers/google_auth.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Implement the OAuth2 router**

```python
# backend/routers/google_auth.py
"""Google OAuth2 endpoints for connecting user Google accounts."""

import json
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, UserGoogleToken
from google_credentials import check_scopes_covered

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/google", tags=["google-auth"])

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8080/auth/google/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")


def _build_client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


@router.get("/authorize")
async def google_authorize(
    scopes: str = Query(..., description="Comma-separated Google API scopes"),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Generate a Google OAuth2 authorization URL."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
    if not scope_list:
        raise HTTPException(status_code=400, detail="At least one scope is required")

    flow = Flow.from_client_config(
        _build_client_config(),
        scopes=scope_list,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=user_id,  # Pass user_id in state for callback
    )
    return {"authorization_url": authorization_url}


@router.get("/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Handle OAuth2 callback from Google. Exchange code for tokens and store."""
    user_id = int(state)

    flow = Flow.from_client_config(
        _build_client_config(),
        scopes=[],  # Scopes already granted in authorize step
        redirect_uri=GOOGLE_REDIRECT_URI,
    )
    flow.fetch_token(code=code)
    credentials = flow.credentials

    granted_scopes = list(credentials.scopes) if credentials.scopes else []

    # Upsert token
    existing = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == user_id).first()
    if existing:
        existing.access_token = credentials.token
        existing.refresh_token = credentials.refresh_token or existing.refresh_token
        existing.token_expiry = credentials.expiry or (datetime.utcnow() + timedelta(hours=1))
        # Merge scopes
        old_scopes = json.loads(existing.granted_scopes) if existing.granted_scopes else []
        merged = list(set(old_scopes + granted_scopes))
        existing.granted_scopes = json.dumps(merged)
        existing.updated_at = datetime.utcnow()
    else:
        token_row = UserGoogleToken(
            user_id=user_id,
            token_expiry=credentials.expiry or (datetime.utcnow() + timedelta(hours=1)),
            granted_scopes=json.dumps(granted_scopes),
        )
        token_row.access_token = credentials.token
        token_row.refresh_token = credentials.refresh_token
        db.add(token_row)

    db.commit()
    logger.info(f"Stored Google OAuth token for user {user_id}, scopes={granted_scopes}")

    return RedirectResponse(url=f"{FRONTEND_URL}/agents?google_connected=true")


@router.get("/status")
async def google_status(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Check if the user has a connected Google account and which scopes are granted."""
    token = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == int(user_id)).first()
    if not token:
        return {"connected": False, "granted_scopes": []}

    granted = json.loads(token.granted_scopes) if token.granted_scopes else []
    expired = token.token_expiry < datetime.utcnow()
    return {"connected": True, "granted_scopes": granted, "token_expired": expired}


@router.delete("/revoke")
async def google_revoke(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Revoke Google tokens and delete from database."""
    token = db.query(UserGoogleToken).filter(UserGoogleToken.user_id == int(user_id)).first()
    if not token:
        raise HTTPException(status_code=404, detail="No Google account connected")

    # Attempt to revoke at Google
    try:
        import requests

        requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": token.access_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
    except Exception:
        logger.warning(f"Failed to revoke token at Google for user {user_id}")

    db.delete(token)
    db.commit()
    return {"status": "revoked"}
```

- [ ] **Step 2: Register the router in main.py**

In `backend/main.py`, after line 500 (the templates router import), add:

```python
from routers.google_auth import router as google_auth_router  # noqa: E402
```

After line 517 (the last `app.include_router`), add:

```python
app.include_router(google_auth_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/google_auth.py backend/main.py
git commit -m "feat(auth): add Google OAuth2 router with authorize, callback, status, revoke"
```

---

## Task 5: Plugins Router and Action Executions Router

**Files:**
- Create: `backend/routers/plugins.py`
- Create: `backend/routers/action_executions.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_action_executions.py`

- [ ] **Step 1: Write the failing test for action execution endpoints**

```python
# backend/tests/test_action_executions.py
"""Tests for action execution confirm/cancel/status endpoints."""

import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from database import ActionExecution


@pytest.mark.asyncio
async def test_confirm_action_pending(client, db_session, test_user, test_agent, auth_cookies):
    """Confirming a pending action should execute it and return the result."""
    ae = ActionExecution(
        agent_id=test_agent.id,
        user_id=test_user.id,
        plugin_name="google_docs",
        action_name="create_doc",
        action_params=json.dumps({"title": "Test Doc"}),
        status="pending_confirmation",
    )
    db_session.add(ae)
    db_session.flush()
    ae_id = ae.id

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = {"doc_id": "abc123"}
    mock_result.display_message = "Created doc"
    mock_result.resource_url = "https://docs.google.com/abc123"
    mock_result.error_message = None

    with patch("routers.action_executions._execute_action", return_value=mock_result):
        resp = await client.post(f"/actions/{ae_id}/confirm", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["resource_url"] == "https://docs.google.com/abc123"


@pytest.mark.asyncio
async def test_cancel_action(client, db_session, test_user, test_agent, auth_cookies):
    """Cancelling a pending action should set status to cancelled."""
    ae = ActionExecution(
        agent_id=test_agent.id,
        user_id=test_user.id,
        plugin_name="google_docs",
        action_name="create_doc",
        action_params=json.dumps({"title": "Test Doc"}),
        status="pending_confirmation",
    )
    db_session.add(ae)
    db_session.flush()
    ae_id = ae.id

    resp = await client.post(f"/actions/{ae_id}/cancel", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_confirm_nonexistent_action(client, auth_cookies):
    """Confirming a nonexistent action should return 404."""
    resp = await client.post("/actions/99999/confirm", cookies=auth_cookies)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_confirm_already_completed(client, db_session, test_user, test_agent, auth_cookies):
    """Confirming an already-completed action should return 400."""
    ae = ActionExecution(
        agent_id=test_agent.id,
        user_id=test_user.id,
        plugin_name="google_docs",
        action_name="create_doc",
        action_params=json.dumps({"title": "Test Doc"}),
        status="completed",
    )
    db_session.add(ae)
    db_session.flush()
    ae_id = ae.id

    resp = await client.post(f"/actions/{ae_id}/confirm", cookies=auth_cookies)
    assert resp.status_code == 400
```

- [ ] **Step 2: Implement plugins router**

```python
# backend/routers/plugins.py
"""Plugin listing endpoints."""

import logging

from fastapi import APIRouter, Depends

from auth import verify_token
from plugins import plugin_manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["plugins"])


@router.get("/plugins")
async def list_plugins(user_id: str = Depends(verify_token)):
    """List all available plugins with metadata."""
    plugins = plugin_manager.list_plugins()
    return {
        "plugins": [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "icon": p.icon,
                "required_scopes": p.required_scopes,
                "actions": [
                    {"name": a.name, "display_name": a.display_name, "description": a.description, "icon": a.icon}
                    for a in p.get_actions().values()
                ],
            }
            for p in plugins
        ]
    }


@router.get("/plugins/{plugin_name}/actions")
async def list_plugin_actions(plugin_name: str, user_id: str = Depends(verify_token)):
    """List actions for a specific plugin."""
    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
    actions = plugin.get_actions()
    return {
        "plugin": plugin_name,
        "actions": [
            {
                "name": a.name,
                "display_name": a.display_name,
                "description": a.description,
                "icon": a.icon,
                "parameters_schema": a.parameters_schema,
            }
            for a in actions.values()
        ],
    }
```

- [ ] **Step 3: Implement action_executions router**

```python
# backend/routers/action_executions.py
"""Action execution endpoints: confirm, cancel, status."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, ActionExecution
from google_credentials import get_google_credentials
from plugins import plugin_manager
from plugins.base import ActionResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])


def _execute_action(plugin_name: str, action_name: str, params: dict, credentials) -> ActionResult:
    """Execute a plugin action. Separated for testability."""
    plugin = plugin_manager.get_plugin(plugin_name)
    if not plugin:
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Plugin '{plugin_name}' not found"
        )
    return plugin.execute(action_name, params, credentials)


@router.post("/actions/{execution_id}/confirm")
async def confirm_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Confirm and execute a pending action."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Action is not pending confirmation (status: {ae.status})")

    ae.status = "confirmed"
    ae.confirmed_at = datetime.utcnow()
    db.flush()

    # Get user credentials
    credentials = get_google_credentials(int(user_id), db)
    if not credentials:
        ae.status = "failed"
        ae.error_message = "Google account not connected. Please connect your Google account first."
        db.commit()
        raise HTTPException(status_code=400, detail="Google account not connected")

    # Execute
    ae.status = "executing"
    db.flush()

    params = json.loads(ae.action_params)
    result = _execute_action(ae.plugin_name, ae.action_name, params, credentials)

    if result.success:
        ae.status = "completed"
        ae.result = json.dumps(result.data)
        ae.executed_at = datetime.utcnow()
    else:
        ae.status = "failed"
        ae.error_message = result.error_message
        ae.executed_at = datetime.utcnow()

    db.commit()

    return {
        "status": ae.status,
        "display_message": result.display_message,
        "resource_url": result.resource_url,
        "data": result.data,
        "error_message": result.error_message,
    }


@router.post("/actions/{execution_id}/cancel")
async def cancel_action(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Cancel a pending action."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")
    if ae.status != "pending_confirmation":
        raise HTTPException(status_code=400, detail=f"Cannot cancel action with status: {ae.status}")

    ae.status = "cancelled"
    db.commit()
    return {"status": "cancelled"}


@router.get("/actions/{execution_id}")
async def get_action_status(
    execution_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get the status and result of an action execution."""
    ae = db.query(ActionExecution).filter(
        ActionExecution.id == execution_id,
        ActionExecution.user_id == int(user_id),
    ).first()
    if not ae:
        raise HTTPException(status_code=404, detail="Action execution not found")

    return {
        "id": ae.id,
        "plugin_name": ae.plugin_name,
        "action_name": ae.action_name,
        "action_params": json.loads(ae.action_params),
        "status": ae.status,
        "result": json.loads(ae.result) if ae.result else None,
        "error_message": ae.error_message,
        "confirmed_at": ae.confirmed_at.isoformat() if ae.confirmed_at else None,
        "executed_at": ae.executed_at.isoformat() if ae.executed_at else None,
        "created_at": ae.created_at.isoformat() if ae.created_at else None,
    }
```

- [ ] **Step 4: Register both routers in main.py**

In `backend/main.py`, after the google_auth_router import, add:

```python
from routers.plugins import router as plugins_router  # noqa: E402
from routers.action_executions import router as action_executions_router  # noqa: E402
```

After the google_auth_router include, add:

```python
app.include_router(plugins_router)
app.include_router(action_executions_router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_action_executions.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/plugins.py backend/routers/action_executions.py backend/main.py backend/tests/test_action_executions.py
git commit -m "feat(api): add plugins listing and action execution confirm/cancel endpoints"
```

---

## Task 6: Google Docs Plugin

**Files:**
- Create: `backend/plugins/google_docs/__init__.py`
- Create: `backend/plugins/google_docs/actions.py`
- Create: `backend/plugins/google_docs/schemas.py`
- Test: `backend/tests/test_plugin_google_docs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_plugin_google_docs.py
"""Tests for the Google Docs plugin."""

import pytest
from unittest.mock import patch, MagicMock


class TestGoogleDocsPlugin:
    def test_plugin_metadata(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        assert p.name == "google_docs"
        assert p.display_name == "Google Docs"
        assert len(p.required_scopes) > 0

    def test_get_actions(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        actions = p.get_actions()
        assert "create_doc" in actions
        assert "update_doc" in actions
        assert "share_doc" in actions

    @patch("plugins.google_docs.actions.build")
    def test_create_doc(self, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.documents().create().execute.return_value = {"documentId": "doc123"}

        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        mock_creds = MagicMock()
        result = p.execute("create_doc", {"title": "My Doc"}, mock_creds)
        assert result.success is True
        assert "doc123" in result.resource_url

    def test_execute_unknown_action(self):
        from plugins.google_docs import GoogleDocsPlugin

        p = GoogleDocsPlugin()
        result = p.execute("unknown", {}, None)
        assert result.success is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_plugin_google_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plugins.google_docs'`

- [ ] **Step 3: Implement schemas.py**

```python
# backend/plugins/google_docs/schemas.py
"""Function calling schemas for Google Docs actions."""

CREATE_DOC = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "The title of the document"},
        "content": {"type": "string", "description": "Optional initial content for the document"},
    },
    "required": ["title"],
}

UPDATE_DOC = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string", "description": "The Google Doc document ID"},
        "content": {"type": "string", "description": "Content to append to the document"},
    },
    "required": ["doc_id", "content"],
}

SHARE_DOC = {
    "type": "object",
    "properties": {
        "doc_id": {"type": "string", "description": "The Google Doc document ID"},
        "email": {"type": "string", "description": "Email address to share with"},
        "role": {"type": "string", "enum": ["reader", "writer", "commenter"], "description": "Permission role"},
    },
    "required": ["doc_id", "email", "role"],
}
```

- [ ] **Step 4: Implement actions.py**

```python
# backend/plugins/google_docs/actions.py
"""Google Docs action implementations."""

from __future__ import annotations

import logging

from googleapiclient.discovery import build
from plugins.base import ActionResult

logger = logging.getLogger(__name__)


def create_doc(args: dict, credentials) -> ActionResult:
    """Create a new Google Doc."""
    title = args.get("title", "Untitled Document")
    content = args.get("content")

    try:
        service = build("docs", "v1", credentials=credentials)
        doc = service.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]

        if content:
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "url": url},
            display_message=f"Created Google Doc '{title}'",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to create Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to create document: {e}"
        )


def update_doc(args: dict, credentials) -> ActionResult:
    """Append content to an existing Google Doc."""
    doc_id = args.get("doc_id")
    content = args.get("content", "")

    try:
        service = build("docs", "v1", credentials=credentials)
        # Get current document length
        doc = service.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1

        requests = [{"insertText": {"location": {"index": end_index}, "text": "\n" + content}}]
        service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "url": url},
            display_message=f"Updated Google Doc",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to update Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to update document: {e}"
        )


def share_doc(args: dict, credentials) -> ActionResult:
    """Share a Google Doc with a user."""
    doc_id = args.get("doc_id")
    email = args.get("email")
    role = args.get("role", "reader")

    try:
        drive_service = build("drive", "v3", credentials=credentials)
        drive_service.permissions().create(
            fileId=doc_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
        ).execute()

        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return ActionResult(
            success=True,
            data={"document_id": doc_id, "shared_with": email, "role": role},
            display_message=f"Shared document with {email} as {role}",
            resource_url=url,
            error_message=None,
        )
    except Exception as e:
        logger.exception(f"Failed to share Google Doc: {e}")
        return ActionResult(
            success=False, data={}, display_message="", resource_url=None, error_message=f"Failed to share document: {e}"
        )
```

- [ ] **Step 5: Implement plugin __init__.py**

```python
# backend/plugins/google_docs/__init__.py
"""Google Docs plugin."""

from plugins.base import BasePlugin, ActionDefinition, ActionResult
from plugins.google_docs import actions, schemas


class GoogleDocsPlugin(BasePlugin):
    name = "google_docs"
    display_name = "Google Docs"
    description = "Create and manage Google Docs documents"
    icon = "file-text"
    required_scopes = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive.file",
    ]

    def get_actions(self):
        return {
            "create_doc": ActionDefinition(
                name="create_doc",
                description="Create a new Google Docs document with an optional title and content",
                parameters_schema=schemas.CREATE_DOC,
                display_name="Create Document",
                icon="file-plus",
            ),
            "update_doc": ActionDefinition(
                name="update_doc",
                description="Append content to an existing Google Docs document",
                parameters_schema=schemas.UPDATE_DOC,
                display_name="Update Document",
                icon="file-edit",
            ),
            "share_doc": ActionDefinition(
                name="share_doc",
                description="Share a Google Docs document with another user by email",
                parameters_schema=schemas.SHARE_DOC,
                display_name="Share Document",
                icon="share",
            ),
        }

    def execute(self, action_name, args, credentials):
        action_map = {
            "create_doc": actions.create_doc,
            "update_doc": actions.update_doc,
            "share_doc": actions.share_doc,
        }
        fn = action_map.get(action_name)
        if not fn:
            return ActionResult(
                success=False, data={}, display_message="", resource_url=None,
                error_message=f"Unknown action: {action_name}",
            )
        return fn(args, credentials)


# Used by PluginManager auto-discovery
plugin_class = GoogleDocsPlugin
```

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/test_plugin_google_docs.py -v`
Expected: All 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/plugins/google_docs/
git commit -m "feat(plugins): add Google Docs plugin with create, update, share actions"
```

---

## Task 7: Remaining Google Workspace Plugins (Sheets, Gmail, Calendar, Slides, Drive)

This task creates the remaining 5 plugins following the same pattern as Google Docs. Each plugin has `__init__.py`, `actions.py`, `schemas.py`, and a test file.

**Files:**
- Create: `backend/plugins/google_sheets/__init__.py`, `actions.py`, `schemas.py`
- Create: `backend/plugins/gmail/__init__.py`, `actions.py`, `schemas.py`
- Create: `backend/plugins/google_calendar/__init__.py`, `actions.py`, `schemas.py`
- Create: `backend/plugins/google_slides/__init__.py`, `actions.py`, `schemas.py`
- Create: `backend/plugins/google_drive/__init__.py`, `actions.py`, `schemas.py`
- Test: `backend/tests/test_plugin_google_sheets.py`
- Test: `backend/tests/test_plugin_gmail.py`
- Test: `backend/tests/test_plugin_google_calendar.py`
- Test: `backend/tests/test_plugin_google_slides.py`
- Test: `backend/tests/test_plugin_google_drive.py`

Due to the repetitive nature, here are the key details for each. Each plugin follows the exact same structure as Task 6 (Google Docs).

### 7a: Google Sheets Plugin

- [ ] **Step 1: Create schemas, actions, __init__, and test**

Plugin metadata:
- `name`: `"google_sheets"`
- `display_name`: `"Google Sheets"`
- `icon`: `"table"`
- `required_scopes`: `["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]`

Actions:
- `create_sheet(title, sheets: [{name, headers, rows}])` — uses `build("sheets", "v4", credentials=credentials)`, `service.spreadsheets().create()`
- `update_sheet(spreadsheet_id, range, values)` — uses `service.spreadsheets().values().update()`
- `read_sheet(spreadsheet_id, range)` — uses `service.spreadsheets().values().get()`

Test: Same pattern as `test_plugin_google_docs.py` — mock `build`, verify metadata, test each action.

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/test_plugin_google_sheets.py -v`

- [ ] **Step 3: Commit**

```bash
git add backend/plugins/google_sheets/ backend/tests/test_plugin_google_sheets.py
git commit -m "feat(plugins): add Google Sheets plugin with create, update, read actions"
```

### 7b: Gmail Plugin

- [ ] **Step 4: Create schemas, actions, __init__, and test**

Plugin metadata:
- `name`: `"gmail"`
- `display_name`: `"Gmail"`
- `icon`: `"mail"`
- `required_scopes`: `["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]`

Actions:
- `send_email(to, subject, body, cc?, bcc?)` — uses `build("gmail", "v1", credentials=credentials)`, constructs MIME message, `service.users().messages().send()`
- `reply_email(thread_id, body)` — uses `service.users().messages().send()` with `threadId`
- `search_emails(query, max_results?)` — uses `service.users().messages().list(q=query)`

The `send_email` action needs to construct a proper MIME message:

```python
import base64
from email.mime.text import MIMEText

def send_email(args, credentials):
    to = args.get("to", [])
    subject = args.get("subject", "")
    body = args.get("body", "")
    cc = args.get("cc", [])
    bcc = args.get("bcc", [])

    msg = MIMEText(body)
    msg["To"] = ", ".join(to) if isinstance(to, list) else to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
    if bcc:
        msg["Bcc"] = ", ".join(bcc) if isinstance(bcc, list) else bcc

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service = build("gmail", "v1", credentials=credentials)
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return ActionResult(success=True, data={"message_id": sent["id"]}, ...)
```

- [ ] **Step 5: Run tests and commit**

```bash
git add backend/plugins/gmail/ backend/tests/test_plugin_gmail.py
git commit -m "feat(plugins): add Gmail plugin with send, reply, search actions"
```

### 7c: Google Calendar Plugin

- [ ] **Step 6: Create schemas, actions, __init__, and test**

Plugin metadata:
- `name`: `"google_calendar"`
- `display_name`: `"Google Calendar"`
- `icon`: `"calendar"`
- `required_scopes`: `["https://www.googleapis.com/auth/calendar.events"]`

Actions:
- `create_event(title, start, end, attendees?, description?)` — uses `build("calendar", "v3", credentials=credentials)`, `service.events().insert(calendarId="primary", ...)`
- `list_events(time_min, time_max, max_results?)` — uses `service.events().list(calendarId="primary", ...)`
- `update_event(event_id, ...)` — uses `service.events().patch(calendarId="primary", eventId=event_id, ...)`

Date format: ISO 8601 with timezone (e.g., `2026-06-04T10:00:00+02:00`).

- [ ] **Step 7: Run tests and commit**

```bash
git add backend/plugins/google_calendar/ backend/tests/test_plugin_google_calendar.py
git commit -m "feat(plugins): add Google Calendar plugin with create, list, update actions"
```

### 7d: Google Slides Plugin

- [ ] **Step 8: Create schemas, actions, __init__, and test**

Plugin metadata:
- `name`: `"google_slides"`
- `display_name`: `"Google Slides"`
- `icon`: `"presentation"`
- `required_scopes`: `["https://www.googleapis.com/auth/presentations", "https://www.googleapis.com/auth/drive.file"]`

Actions:
- `create_presentation(title, slides: [{title, body}])` — uses `build("slides", "v1", credentials=credentials)`, `service.presentations().create()`, then `batchUpdate` to add slides
- `add_slide(presentation_id, title, body)` — uses `service.presentations().batchUpdate()`

- [ ] **Step 9: Run tests and commit**

```bash
git add backend/plugins/google_slides/ backend/tests/test_plugin_google_slides.py
git commit -m "feat(plugins): add Google Slides plugin with create_presentation and add_slide actions"
```

### 7e: Google Drive Plugin

- [ ] **Step 10: Create schemas, actions, __init__, and test**

Plugin metadata:
- `name`: `"google_drive"`
- `display_name`: `"Google Drive"`
- `icon`: `"hard-drive"`
- `required_scopes`: `["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/drive.readonly"]`

Actions:
- `create_folder(name, parent_id?)` — uses `build("drive", "v3", credentials=credentials)`, `service.files().create(body={"name": name, "mimeType": "application/vnd.google-apps.folder", ...})`
- `move_file(file_id, folder_id)` — uses `service.files().update(fileId=file_id, addParents=folder_id, removeParents=...)`
- `share_file(file_id, email, role)` — uses `service.permissions().create(fileId=file_id, ...)`
- `search_files(query, max_results?)` — uses `service.files().list(q=query, ...)`

- [ ] **Step 11: Run tests and commit**

```bash
git add backend/plugins/google_drive/ backend/tests/test_plugin_google_drive.py
git commit -m "feat(plugins): add Google Drive plugin with create_folder, move, share, search actions"
```

---

## Task 8: Agent Creation — Accept enabled_plugins

**Files:**
- Modify: `backend/routers/agents.py`

- [ ] **Step 1: Add `enabled_plugins` to the create_agent endpoint**

In `backend/routers/agents.py`, in the `create_agent` function signature (around line 139), add the parameter:

```python
    enabled_plugins: str = Form(None),  # JSON array of plugin names
```

- [ ] **Step 2: Store enabled_plugins on the agent**

In the same function, after `recap_hour` is parsed (around line 225), add:

```python
        # Parse enabled_plugins for actionnable agents
        parsed_plugins = None
        if type == "actionnable" and enabled_plugins:
            try:
                parsed_plugins = json.dumps(json.loads(enabled_plugins))
            except json.JSONDecodeError:
                parsed_plugins = json.dumps([p.strip() for p in enabled_plugins.split(",") if p.strip()])
```

Then in the `Agent()` constructor (around line 228), add `enabled_plugins=parsed_plugins,` to the arguments.

- [ ] **Step 3: Add enabled_plugins to the update_agent endpoint**

Find the `update_agent` endpoint (PUT `/agents/{agent_id}`). Add `enabled_plugins: str = Form(None)` to the function signature and add the parsing + update logic inside the handler:

```python
        if enabled_plugins is not None:
            if agent.type == "actionnable":
                try:
                    agent.enabled_plugins = json.dumps(json.loads(enabled_plugins))
                except json.JSONDecodeError:
                    agent.enabled_plugins = json.dumps([p.strip() for p in enabled_plugins.split(",") if p.strip()])
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/agents.py
git commit -m "feat(agents): accept enabled_plugins field for actionnable agent creation/update"
```

---

## Task 9: Two-Stage Pipeline in Ask Endpoint

**Files:**
- Modify: `backend/routers/ask.py`
- Test: `backend/tests/test_ask_actionnable.py`

This is the core integration: after the RAG response (Stage 1), run Gemini function calling (Stage 2) for actionnable agents.

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/test_ask_actionnable.py
"""Integration tests for the actionnable agent two-stage pipeline."""

import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_actionnable_agent_proposes_action(client, db_session, test_user, auth_cookies):
    """An actionnable agent should return action_proposal when Gemini detects an action."""
    from database import Agent
    from helpers.agent_helpers import resolve_llm_provider

    agent = Agent(
        name="Action Agent",
        contexte="You create documents.",
        type="actionnable",
        llm_provider=resolve_llm_provider("actionnable"),
        enabled_plugins=json.dumps(["google_docs"]),
        user_id=test_user.id,
    )
    db_session.add(agent)
    db_session.flush()

    # Mock RAG response (Stage 1)
    mock_rag_result = {
        "answer": "I can create that document for you.",
        "sources": [],
        "graph_data": None,
    }

    # Mock Gemini function call response (Stage 2)
    mock_gemini_response = {
        "function_call": {
            "name": "create_doc",
            "arguments": {"title": "Meeting Notes", "content": "Notes from today's meeting"},
        }
    }

    with patch("routers.ask.get_answer", return_value=mock_rag_result), \
         patch("routers.ask.detect_action_with_gemini", return_value=mock_gemini_response):
        resp = await client.post(
            "/ask",
            json={"question": "Create a document with meeting notes", "agent_id": agent.id},
            cookies=auth_cookies,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "I can create that document for you."
    assert data["action_proposal"] is not None
    assert data["action_proposal"]["plugin"] == "google_docs"
    assert data["action_proposal"]["action"] == "create_doc"


@pytest.mark.asyncio
async def test_actionnable_agent_no_action(client, db_session, test_user, auth_cookies):
    """An actionnable agent should return no action_proposal for normal questions."""
    from database import Agent
    from helpers.agent_helpers import resolve_llm_provider

    agent = Agent(
        name="Action Agent",
        contexte="You help with documents.",
        type="actionnable",
        llm_provider=resolve_llm_provider("actionnable"),
        enabled_plugins=json.dumps(["google_docs"]),
        user_id=test_user.id,
    )
    db_session.add(agent)
    db_session.flush()

    mock_rag_result = {
        "answer": "The document discusses Q4 revenue growth of 15%.",
        "sources": [{"chunk_id": 1}],
        "graph_data": None,
    }

    with patch("routers.ask.get_answer", return_value=mock_rag_result), \
         patch("routers.ask.detect_action_with_gemini", return_value=None):
        resp = await client.post(
            "/ask",
            json={"question": "What does the Q4 report say about revenue?", "agent_id": agent.id},
            cookies=auth_cookies,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["action_proposal"] is None
```

- [ ] **Step 2: Implement the action detection function**

In `backend/routers/ask.py`, add at the top of the file (after existing imports):

```python
from plugins import plugin_manager
from database import ActionExecution
```

Then add this function before the `ask_question` endpoint:

```python
def detect_action_with_gemini(user_message: str, rag_response: str, function_definitions: list) -> dict | None:
    """Stage 2: Use Gemini to detect if an action should be proposed.

    Returns a dict with 'function_call' key if action detected, None otherwise.
    """
    if not function_definitions:
        return None

    from gemini_client import generate_text
    import json as _json

    # Build the prompt with function definitions
    funcs_desc = _json.dumps(function_definitions, indent=2)
    prompt = (
        "You are an action detection system. Analyze the user's message and determine "
        "if any of the available actions should be executed.\n\n"
        f"Available actions:\n{funcs_desc}\n\n"
        f"User message: {user_message}\n\n"
        f"Assistant's RAG response: {rag_response}\n\n"
        "If an action should be executed, respond ONLY with a JSON object:\n"
        '{"function_call": {"name": "<action_name>", "arguments": {<arguments>}}}\n\n'
        "If NO action is needed, respond ONLY with: null\n"
        "Respond with nothing else."
    )

    try:
        result = generate_text(prompt, model_name="gemini-2.0-flash", temperature=0.0)
        result = result.strip()
        if result == "null" or not result:
            return None
        parsed = _json.loads(result)
        if isinstance(parsed, dict) and "function_call" in parsed:
            return parsed
        return None
    except Exception:
        logger.exception("Gemini action detection failed")
        return None
```

- [ ] **Step 3: Modify the ask_question endpoint to add Stage 2**

In `backend/routers/ask.py`, inside the `ask_question` function, after the RAG result is obtained (around line 88), add the Stage 2 logic:

```python
        action_proposal = None

        # Stage 2: Action detection for actionnable agents
        if agent and getattr(agent, "type", "") == "actionnable":
            import json as _json

            enabled = []
            if agent.enabled_plugins:
                try:
                    enabled = _json.loads(agent.enabled_plugins)
                except Exception:
                    enabled = []

            if enabled:
                func_defs = plugin_manager.get_function_definitions(enabled)
                detection = detect_action_with_gemini(request.question, answer, func_defs)

                if detection and "function_call" in detection:
                    fc = detection["function_call"]
                    action_name = fc.get("name", "")
                    action_args = fc.get("arguments", {})

                    # Find which plugin owns this action
                    actions_map = plugin_manager.get_actions_for_plugins(enabled)
                    action_info = actions_map.get(action_name)
                    plugin_name = action_info["plugin"] if action_info else "unknown"

                    # Create ActionExecution record
                    from helpers.tenant import _get_caller_company_id

                    company_id = agent.company_id or _get_caller_company_id(user_id, db)
                    ae = ActionExecution(
                        agent_id=agent.id,
                        user_id=int(user_id),
                        company_id=company_id,
                        plugin_name=plugin_name,
                        action_name=action_name,
                        action_params=_json.dumps(action_args),
                        status="pending_confirmation",
                    )
                    db.add(ae)
                    db.commit()
                    db.refresh(ae)

                    # Build display summary
                    display_summary = f"{action_name}({', '.join(f'{k}={v!r}' for k, v in list(action_args.items())[:3])})"

                    action_proposal = {
                        "execution_id": ae.id,
                        "plugin": plugin_name,
                        "action": action_name,
                        "params": action_args,
                        "display_summary": display_summary,
                    }
```

Then modify the return statement (line 143) to include `action_proposal`:

```python
        return {"answer": answer, "sources": sources, "graph_data": graph_data, "action_proposal": action_proposal}
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_ask_actionnable.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/ask.py backend/tests/test_ask_actionnable.py
git commit -m "feat(ask): add two-stage pipeline with Gemini action detection for actionnable agents"
```

---

## Task 10: Frontend — i18n Updates

**Files:**
- Modify: `frontend/public/locales/en/agents.json`
- Modify: `frontend/public/locales/fr/agents.json`
- Modify: `frontend/public/locales/en/chat.json`
- Modify: `frontend/public/locales/fr/chat.json`

- [ ] **Step 1: Add actionnable type to English agents.json**

In `frontend/public/locales/en/agents.json`, inside the `"types"` object, after `"visuel"`, add:

```json
    "actionnable": {
      "name": "Actionable",
      "description": "Execute tasks in Google Workspace"
    }
```

Also add under `"form"`:

```json
    "plugins": {
      "label": "Enabled plugins",
      "description": "Select which Google Workspace integrations this companion can use",
      "connectGoogle": "Connect Google Account",
      "googleConnected": "Google Account Connected",
      "scopesMissing": "Additional permissions required"
    }
```

- [ ] **Step 2: Add actionnable type to French agents.json**

In `frontend/public/locales/fr/agents.json`, inside `"types"`, add:

```json
    "actionnable": {
      "name": "Actionnable",
      "description": "Exécuter des tâches dans Google Workspace"
    }
```

Also add under `"form"`:

```json
    "plugins": {
      "label": "Plugins activés",
      "description": "Sélectionnez les intégrations Google Workspace que ce companion peut utiliser",
      "connectGoogle": "Connecter un compte Google",
      "googleConnected": "Compte Google connecté",
      "scopesMissing": "Permissions supplémentaires requises"
    }
```

- [ ] **Step 3: Add action strings to English chat.json**

In `frontend/public/locales/en/chat.json`, add a new `"actions"` section:

```json
  "actions": {
    "confirm": "Execute",
    "cancel": "Cancel",
    "pendingConfirmation": "Awaiting confirmation",
    "executing": "Executing...",
    "completed": "Completed",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "connectGooglePrompt": "Connect your Google account to enable actions",
    "actionProposed": "Action proposed"
  }
```

- [ ] **Step 4: Add action strings to French chat.json**

In `frontend/public/locales/fr/chat.json`, add:

```json
  "actions": {
    "confirm": "Exécuter",
    "cancel": "Annuler",
    "pendingConfirmation": "En attente de confirmation",
    "executing": "Exécution en cours...",
    "completed": "Terminé",
    "failed": "Échec",
    "cancelled": "Annulé",
    "connectGooglePrompt": "Connectez votre compte Google pour activer les actions",
    "actionProposed": "Action proposée"
  }
```

- [ ] **Step 5: Commit**

```bash
git add frontend/public/locales/
git commit -m "feat(i18n): add actionnable agent type and action strings in EN and FR"
```

---

## Task 11: Frontend — PluginSelector Component

**Files:**
- Create: `frontend/components/PluginSelector.js`

- [ ] **Step 1: Create the PluginSelector component**

```jsx
// frontend/components/PluginSelector.js
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { FileText, Table, Mail, Calendar, Presentation, HardDrive, Check, ExternalLink } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function PluginSelector({ enabledPlugins, onChange }) {
  const { t } = useTranslation(['agents']);
  const [plugins, setPlugins] = useState([]);
  const [googleStatus, setGoogleStatus] = useState({ connected: false, granted_scopes: [] });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [pluginsRes, statusRes] = await Promise.all([
          api.get('/plugins'),
          api.get('/auth/google/status'),
        ]);
        setPlugins(pluginsRes.data.plugins || []);
        setGoogleStatus(statusRes.data);
      } catch (e) {
        console.error('Failed to load plugins:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const togglePlugin = (pluginName) => {
    const current = enabledPlugins || [];
    const updated = current.includes(pluginName)
      ? current.filter(p => p !== pluginName)
      : [...current, pluginName];
    onChange(updated);
  };

  const connectGoogle = async () => {
    const allScopes = plugins
      .filter(p => (enabledPlugins || []).includes(p.name))
      .flatMap(p => p.required_scopes);
    const uniqueScopes = [...new Set(allScopes)];

    try {
      const res = await api.get(`/auth/google/authorize?scopes=${uniqueScopes.join(',')}`);
      window.open(res.data.authorization_url, '_blank', 'width=600,height=700');
    } catch (e) {
      console.error('Failed to start Google auth:', e);
    }
  };

  if (loading) {
    return <div className="animate-pulse h-32 bg-gray-100 rounded-card" />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-gray-700">
          {t('agents:form.plugins.label')}
        </label>
        {googleStatus.connected ? (
          <span className="inline-flex items-center px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
            <Check className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.googleConnected')}
          </span>
        ) : (
          <button
            type="button"
            onClick={connectGoogle}
            className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-button hover:bg-blue-700 transition-colors"
          >
            <ExternalLink className="w-3 h-3 mr-1" />
            {t('agents:form.plugins.connectGoogle')}
          </button>
        )}
      </div>

      <p className="text-xs text-gray-500">{t('agents:form.plugins.description')}</p>

      <div className="grid grid-cols-2 gap-3">
        {plugins.map(plugin => {
          const Icon = PLUGIN_ICONS[plugin.name] || FileText;
          const isEnabled = (enabledPlugins || []).includes(plugin.name);

          return (
            <button
              key={plugin.name}
              type="button"
              onClick={() => togglePlugin(plugin.name)}
              className={`flex items-center p-3 rounded-card border-2 transition-all text-left ${
                isEnabled
                  ? 'border-primary-500 bg-primary-50 shadow-sm'
                  : 'border-gray-200 bg-white hover:border-gray-300'
              }`}
            >
              <div className={`p-2 rounded-button mr-3 ${isEnabled ? 'bg-primary-100' : 'bg-gray-100'}`}>
                <Icon className={`w-5 h-5 ${isEnabled ? 'text-primary-600' : 'text-gray-500'}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-900">{plugin.display_name}</div>
                <div className="text-xs text-gray-500 truncate">{plugin.description}</div>
              </div>
              {isEnabled && (
                <Check className="w-5 h-5 text-primary-600 flex-shrink-0 ml-2" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/PluginSelector.js
git commit -m "feat(ui): add PluginSelector component for actionnable agent configuration"
```

---

## Task 12: Frontend — ActionProposal Component

**Files:**
- Create: `frontend/components/ActionProposal.js`

- [ ] **Step 1: Create the ActionProposal component**

```jsx
// frontend/components/ActionProposal.js
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { Play, X, Check, AlertCircle, Loader2, ExternalLink, FileText, Table, Mail, Calendar, Presentation, HardDrive } from 'lucide-react';
import api from '../lib/api';

const PLUGIN_ICONS = {
  google_docs: FileText,
  google_sheets: Table,
  gmail: Mail,
  google_calendar: Calendar,
  google_slides: Presentation,
  google_drive: HardDrive,
};

export default function ActionProposal({ proposal, onResult }) {
  const { t } = useTranslation(['chat']);
  const [status, setStatus] = useState('pending');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const Icon = PLUGIN_ICONS[proposal.plugin] || FileText;

  const handleConfirm = async () => {
    setLoading(true);
    setStatus('executing');
    try {
      const res = await api.post(`/actions/${proposal.execution_id}/confirm`);
      setStatus(res.data.status);
      setResult(res.data);
      if (onResult) onResult(res.data);
    } catch (e) {
      setStatus('failed');
      setResult({ error_message: e.response?.data?.detail || 'Execution failed' });
    } finally {
      setLoading(false);
    }
  };

  const handleCancel = async () => {
    try {
      await api.post(`/actions/${proposal.execution_id}/cancel`);
      setStatus('cancelled');
    } catch (e) {
      console.error('Failed to cancel action:', e);
    }
  };

  return (
    <div className="mt-3 border border-gray-200 rounded-card overflow-hidden bg-gray-50">
      {/* Header */}
      <div className="flex items-center px-4 py-2 bg-gray-100 border-b border-gray-200">
        <Icon className="w-4 h-4 text-gray-600 mr-2" />
        <span className="text-sm font-medium text-gray-700">{t('chat:actions.actionProposed')}</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3">
        <p className="text-sm text-gray-800 mb-2">{proposal.display_summary}</p>

        {/* Action buttons — only show when pending */}
        {status === 'pending' && (
          <div className="flex gap-2 mt-3">
            <button
              onClick={handleConfirm}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-button hover:bg-green-700 transition-colors disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Play className="w-4 h-4 mr-1" />}
              {t('chat:actions.confirm')}
            </button>
            <button
              onClick={handleCancel}
              disabled={loading}
              className="inline-flex items-center px-4 py-2 text-sm font-medium text-gray-700 bg-gray-200 rounded-button hover:bg-gray-300 transition-colors disabled:opacity-50"
            >
              <X className="w-4 h-4 mr-1" />
              {t('chat:actions.cancel')}
            </button>
          </div>
        )}

        {/* Status badges */}
        {status === 'executing' && (
          <div className="flex items-center mt-3 text-sm text-blue-600">
            <Loader2 className="w-4 h-4 mr-1 animate-spin" />
            {t('chat:actions.executing')}
          </div>
        )}

        {status === 'completed' && result && (
          <div className="mt-3 p-3 bg-green-50 rounded-button border border-green-200">
            <div className="flex items-center text-sm text-green-700">
              <Check className="w-4 h-4 mr-1" />
              {t('chat:actions.completed')}
            </div>
            {result.display_message && (
              <p className="text-sm text-green-800 mt-1">{result.display_message}</p>
            )}
            {result.resource_url && (
              <a
                href={result.resource_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center mt-2 text-sm text-blue-600 hover:underline"
              >
                <ExternalLink className="w-3 h-3 mr-1" />
                {t('chat:messages.openButton')}
              </a>
            )}
          </div>
        )}

        {status === 'failed' && (
          <div className="mt-3 p-3 bg-red-50 rounded-button border border-red-200">
            <div className="flex items-center text-sm text-red-700">
              <AlertCircle className="w-4 h-4 mr-1" />
              {t('chat:actions.failed')}
            </div>
            {result?.error_message && (
              <p className="text-sm text-red-600 mt-1">{result.error_message}</p>
            )}
          </div>
        )}

        {status === 'cancelled' && (
          <div className="mt-3 flex items-center text-sm text-gray-500">
            <X className="w-4 h-4 mr-1" />
            {t('chat:actions.cancelled')}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/ActionProposal.js
git commit -m "feat(ui): add ActionProposal component with confirm/cancel/status display"
```

---

## Task 13: Frontend — Wire Up Agent Creation and Chat

**Files:**
- Modify: `frontend/pages/agents.js`
- Modify: `frontend/pages/chat/[agentId].js`

- [ ] **Step 1: Add actionnable option to agents.js type dropdown**

In `frontend/pages/agents.js`, around line 372, after the `visuel` option, add:

```jsx
                  <option value="actionnable">{t('agents:types.actionnable.name')} - {t('agents:types.actionnable.description')}</option>
```

- [ ] **Step 2: Add PluginSelector to agents.js**

At the top of `frontend/pages/agents.js`, add the import:

```jsx
import PluginSelector from '../components/PluginSelector';
```

In the form state initialization (find `useState` for `form`), add `enabled_plugins: []` to the initial state.

After the type dropdown `</div>` (around line 374), add:

```jsx
              {form.type === 'actionnable' && (
                <PluginSelector
                  enabledPlugins={form.enabled_plugins}
                  onChange={(plugins) => setForm(f => ({ ...f, enabled_plugins: plugins }))}
                />
              )}
```

In the form submit handler, when building the `FormData`, add:

```javascript
        if (form.type === 'actionnable' && form.enabled_plugins?.length > 0) {
          formData.append('enabled_plugins', JSON.stringify(form.enabled_plugins));
        }
```

- [ ] **Step 3: Add ActionProposal rendering to chat/[agentId].js**

At the top of `frontend/pages/chat/[agentId].js`, add the import:

```jsx
import ActionProposal from '../../components/ActionProposal';
```

In the message rendering section (where messages are mapped to JSX), after the message content rendering, add:

```jsx
                {msg.action_proposal && (
                  <ActionProposal
                    proposal={msg.action_proposal}
                    onResult={(result) => {
                      // Optionally update message or show toast
                    }}
                  />
                )}
```

In the `ask` handler (around line 626, where the `/ask` response is processed), after `iaAnswer` is set, add:

```javascript
          const actionProposal = resAsk.data.action_proposal || null;
          // Store action_proposal on the message for rendering
          setMessages(prev => prev.map((m, i) =>
            i === streamingMsgIdx.current
              ? { ...m, content: iaAnswer, streaming: false, sources: iaSources, graph_data: iaGraphData, action_proposal: actionProposal }
              : m
          ));
```

Replace the existing `setMessages` call at line 629 with the above (which now includes `action_proposal`).

- [ ] **Step 4: Commit**

```bash
git add frontend/pages/agents.js frontend/pages/chat/[agentId].js
git commit -m "feat(ui): wire up actionnable agent creation with plugin selector and action proposals in chat"
```

---

## Task 14: Register Plugins at Startup

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Call discover_plugins at startup**

In `backend/main.py`, after all router imports (around line 520), add:

```python
# Discover and register all plugins
from plugins import discover_plugins  # noqa: E402
discover_plugins()
```

- [ ] **Step 2: Verify all 6 plugins load**

Run: `cd backend && python -c "from plugins import discover_plugins, plugin_manager; discover_plugins(); print([p.name for p in plugin_manager.list_plugins()])"`
Expected output: `['google_docs', 'google_sheets', 'gmail', 'google_calendar', 'google_slides', 'google_drive']`

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(startup): auto-discover and register all plugins at backend startup"
```

---

## Task 15: Remove Legacy Actionnable Code

**Files:**
- Modify: `backend/rag_engine.py` (4 locations)
- Modify: `backend/routers/ask.py` (old function calling block, if still present)

- [ ] **Step 1: Remove gemini_only flags from rag_engine.py**

Search for `gemini_only` in `rag_engine.py` and remove the 4 occurrences:

1. In `get_answer()` (around line 470-475): Remove the `gemini_only_flag` variable and the `gemini_only=gemini_only_flag` argument from `get_chat_response()`.
2. In `get_answer_stream()` (around line 705-712): Same removal.

The `gemini_only` parameter in `get_chat_response` and `get_chat_response_stream` can stay (it may be used elsewhere), but the actionnable-specific flag logic is removed.

- [ ] **Step 2: Remove old function calling from actions.py**

In `backend/actions.py`, remove the `gemini_only_flag` logic from `action_create_google_doc` (lines 307-328) and `action_create_google_sheet` (lines 565-584). These functions will be deprecated in favor of the plugin implementations. Do NOT delete the entire file yet — keep it for backward compatibility with existing `AgentAction` records.

Add a deprecation comment at the top:

```python
"""DEPRECATED: Legacy action implementations. New actions use the plugin system (backend/plugins/).
This file is kept for backward compatibility with existing AgentAction records."""
```

- [ ] **Step 3: Commit**

```bash
git add backend/rag_engine.py backend/actions.py
git commit -m "refactor: remove legacy gemini_only flags and deprecate old actions.py"
```

---

## Task 16: GoogleConnectButton Component

**Files:**
- Create: `frontend/components/GoogleConnectButton.js`

- [ ] **Step 1: Create the component**

```jsx
// frontend/components/GoogleConnectButton.js
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import { ExternalLink, Check } from 'lucide-react';
import api from '../lib/api';

export default function GoogleConnectButton({ requiredScopes = [] }) {
  const { t } = useTranslation(['agents']);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/auth/google/status')
      .then(res => setStatus(res.data))
      .catch(() => setStatus({ connected: false, granted_scopes: [] }))
      .finally(() => setLoading(false));
  }, []);

  const handleConnect = async () => {
    const scopes = requiredScopes.length > 0 ? requiredScopes : [];
    try {
      const res = await api.get(`/auth/google/authorize?scopes=${scopes.join(',')}`);
      window.open(res.data.authorization_url, '_blank', 'width=600,height=700');
    } catch (e) {
      console.error('Failed to start Google auth:', e);
    }
  };

  if (loading) return null;

  if (status?.connected) {
    return (
      <span className="inline-flex items-center px-2 py-1 text-xs font-medium text-green-700 bg-green-100 rounded-full">
        <Check className="w-3 h-3 mr-1" />
        {t('agents:form.plugins.googleConnected')}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={handleConnect}
      className="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-button hover:bg-blue-700 transition-colors"
    >
      <ExternalLink className="w-3 h-3 mr-1" />
      {t('agents:form.plugins.connectGoogle')}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/GoogleConnectButton.js
git commit -m "feat(ui): add GoogleConnectButton component for OAuth2 connection"
```

---

## Task 17: End-to-End Smoke Test

No new code files — this is a manual verification checklist.

- [ ] **Step 1: Start backend**

Run: `cd backend && python -m uvicorn main:app --reload --port 8080`
Verify: No import errors, plugins discovered in startup logs.

- [ ] **Step 2: Start frontend**

Run: `cd frontend && npm run dev`
Verify: No build errors.

- [ ] **Step 3: Verify plugin discovery endpoint**

Run: `curl -s http://localhost:8080/plugins -H "Cookie: token=<valid_jwt>" | python -m json.tool`
Expected: JSON with 6 plugins listed.

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All new tests pass. Existing tests unaffected.

- [ ] **Step 5: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors on new files.

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found during smoke testing"
```
