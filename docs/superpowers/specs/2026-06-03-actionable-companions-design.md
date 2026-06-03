# Actionable Companions — Design Spec

## Overview

Add specialized actionable AI companions that can execute Google Workspace tasks (Docs, Sheets, Gmail, Calendar, Slides, Drive) on behalf of users. Built on a plugin architecture for extensibility, with OAuth2 user authentication and mandatory confirmation before every action.

## Goals

- Let users create agents that combine RAG document Q&A with real-world action execution
- Provide a clean plugin system where each Google Workspace integration is self-contained
- Use the user's own Google account (OAuth2) instead of a shared service account
- Require explicit confirmation before every action execution
- Full audit trail for compliance

## Non-Goals (v1)

- Non-Google integrations (Slack, Notion, CRM) — future iterations
- Workflow chaining (multiple actions in sequence) — future iterations
- Specialized industry templates (HR, finance, legal) — future iterations
- Auto-execution without confirmation

---

## Architecture

### Plugin System

```
backend/
  plugins/
    __init__.py              # PluginManager — auto-discovery, registration
    base.py                  # BasePlugin ABC + ActionDefinition + ActionResult
    registry.py              # Global plugin/action registry
    google_docs/
      __init__.py            # GoogleDocsPlugin(BasePlugin)
      actions.py             # create_doc, update_doc, share_doc
      schemas.py             # Function calling JSON schemas
    google_sheets/
      __init__.py            # GoogleSheetsPlugin(BasePlugin)
      actions.py             # create_sheet, update_sheet, read_sheet
      schemas.py
    gmail/
      __init__.py            # GmailPlugin(BasePlugin)
      actions.py             # send_email, reply_email, search_emails
      schemas.py
    google_calendar/
      __init__.py            # GoogleCalendarPlugin(BasePlugin)
      actions.py             # create_event, list_events, update_event
      schemas.py
    google_slides/
      __init__.py            # GoogleSlidesPlugin(BasePlugin)
      actions.py             # create_presentation, add_slide
      schemas.py
    google_drive/
      __init__.py            # GoogleDrivePlugin(BasePlugin)
      actions.py             # create_folder, move_file, share_file, search_files
      schemas.py
```

### BasePlugin Contract

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ActionDefinition:
    name: str                    # "send_email"
    description: str             # "Send an email from the user's Gmail"
    parameters_schema: dict      # JSON Schema for function calling
    display_name: str            # "Send Email" (for frontend)
    icon: str                    # "mail" (for frontend)

@dataclass
class ActionResult:
    success: bool
    data: dict                   # Plugin-specific result data
    display_message: str         # Human-readable result for chat
    resource_url: str | None     # Link to created resource (doc URL, event link, etc.)
    error_message: str | None

class BasePlugin(ABC):
    name: str                    # "gmail"
    display_name: str            # "Gmail"
    description: str             # "Send and manage emails"
    icon: str                    # "gmail"
    required_scopes: list[str]   # ["https://www.googleapis.com/auth/gmail.send", ...]

    @abstractmethod
    def get_actions(self) -> dict[str, ActionDefinition]:
        """Return all actions this plugin provides."""

    @abstractmethod
    def execute(self, action_name: str, args: dict, credentials) -> ActionResult:
        """Execute an action with the user's Google credentials."""
```

### PluginManager

- On startup, scans `backend/plugins/` for submodules containing a `BasePlugin` subclass
- Registers all discovered plugins in a global registry
- Provides methods: `get_plugin(name)`, `list_plugins()`, `get_actions_for_plugins(plugin_names)`
- Generates combined function definitions for Gemini from the active plugins of an agent

---

## OAuth2 Google Authentication

### Flow

1. User clicks "Connect Google" in agent settings or during actionable agent creation
2. Backend generates OAuth2 authorization URL with scopes matching activated plugins
3. User authorizes on Google consent screen
4. Google redirects to callback with authorization code
5. Backend exchanges code for access_token + refresh_token
6. Tokens stored encrypted in `user_google_tokens` table

### Incremental Consent

When a user activates a new plugin requiring additional scopes:
- Check if existing token already covers the required scopes (via `granted_scopes`)
- If not, prompt re-authorization with the additional scopes
- Google's incremental consent merges new scopes with existing grants

### Token Refresh

Before every Google API call:
- Check `token_expiry`
- If expired, use `refresh_token` to get a new `access_token`
- Update stored token

### Data Model

```sql
CREATE TABLE user_google_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,           -- Encrypted
    refresh_token TEXT NOT NULL,          -- Encrypted
    token_expiry TIMESTAMP NOT NULL,
    granted_scopes JSONB NOT NULL,        -- ["gmail.send", "documents", ...]
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id)
);
```

### Endpoints

- `GET /auth/google/authorize?scopes=scope1,scope2` — Returns Google OAuth2 URL
- `GET /auth/google/callback?code=...&state=...` — Exchanges code, stores tokens, redirects to frontend
- `GET /auth/google/status` — Returns connection status + granted scopes
- `DELETE /auth/google/revoke` — Revokes tokens at Google + deletes from database

---

## Database Changes

### Agent Model — New Field

```sql
ALTER TABLE agents ADD COLUMN enabled_plugins JSONB DEFAULT '[]';
-- Example: ["google_docs", "gmail", "google_calendar"]
```

When `type = 'actionnable'`, this field determines which plugins (and thus which actions) are available. For non-actionnable agents, this field is ignored.

### ActionExecution Model (replaces AgentAction)

```sql
CREATE TABLE action_executions (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    company_id INTEGER REFERENCES companies(id),
    conversation_id INTEGER REFERENCES conversations(id),
    message_id INTEGER REFERENCES messages(id),
    plugin_name VARCHAR(64) NOT NULL,       -- "gmail"
    action_name VARCHAR(64) NOT NULL,       -- "send_email"
    action_params JSONB NOT NULL,           -- Full parameters
    status VARCHAR(32) NOT NULL DEFAULT 'pending_confirmation',
        -- pending_confirmation | confirmed | executing | completed | failed | cancelled
    result JSONB,                           -- Action result data
    error_message TEXT,
    confirmed_at TIMESTAMP,
    executed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_action_executions_agent ON action_executions(agent_id);
CREATE INDEX idx_action_executions_user ON action_executions(user_id);
CREATE INDEX idx_action_executions_status ON action_executions(status);
```

### RLS Policies

```sql
ALTER TABLE action_executions ENABLE ROW LEVEL SECURITY;

CREATE POLICY action_executions_tenant_isolation ON action_executions
    USING (company_id = current_setting('app.company_id', true)::int);

CREATE POLICY action_executions_service_bypass ON action_executions
    USING (current_setting('app.service_bypass', true)::text = 'true');
```

---

## Function Calling Pipeline

### Two-Stage Pipeline

**Stage 1 — RAG + Conversation (Mistral)**
- Retrieve relevant document chunks via FAISS
- Build context with agent's `contexte` + retrieved documents
- Generate conversational response via Mistral
- This response is always shown to the user

**Stage 2 — Action Detection (Gemini, only for actionnable agents)**
- Collect function definitions from the agent's enabled plugins
- Send to Gemini: user message + RAG response + function definitions
- Gemini decides: action needed or not
- If action needed: returns structured `function_call` with name + arguments
- If no action: Stage 1 response is used as-is

### Why Two Stages

- Mistral handles conversational quality and RAG well
- Gemini has native function calling support (structured tool_calls, not prompt-engineered JSON)
- Separation means actionnable agents still give good conversational responses even when no action is triggered
- If Gemini's action detection fails, the user still gets a useful text response

### System Prompt for Stage 2

```
You are an action detection system. Analyze the user's message and determine
if any of the available actions should be executed. If an action is needed,
call the appropriate function. If no action is needed, respond with an empty
message. Only propose ONE action per message.
```

### Response Format to Frontend

When an action is detected:

```json
{
  "answer": "Je vais créer un document Google Docs avec le résumé de votre rapport.",
  "action_proposal": {
    "execution_id": 42,
    "plugin": "google_docs",
    "action": "create_doc",
    "params": {
      "title": "Résumé du rapport Q4",
      "content": "..."
    },
    "display_summary": "Créer un Google Doc 'Résumé du rapport Q4'"
  },
  "sources": [...],
  "graph_data": null
}
```

When no action is detected (normal RAG response):

```json
{
  "answer": "D'après vos documents, le rapport Q4 montre une croissance de 15%...",
  "action_proposal": null,
  "sources": [...],
  "graph_data": null
}
```

---

## API Endpoints

### Plugin Management

- `GET /plugins` — List all available plugins with metadata (name, display_name, description, icon, required_scopes)
- `GET /plugins/{plugin_name}/actions` — List actions for a specific plugin

### Action Execution

- `POST /actions/{execution_id}/confirm` — Confirm and execute a pending action
- `POST /actions/{execution_id}/cancel` — Cancel a pending action
- `GET /actions/{execution_id}` — Get execution status and result
- `GET /agents/{agent_id}/actions` — List action history for an agent

### Agent Creation/Update (modified)

- `POST /agents` — Add `enabled_plugins` field (JSON array) when type is "actionnable"
- `PUT /agents/{agent_id}` — Allow updating `enabled_plugins`

---

## Frontend Changes

### Agent Creation Page (agents.js)

1. **Add "Actionnable" option** to agent type dropdown with i18n support
2. **Plugin selector panel** — shown when type is "actionnable":
   - Grid of plugin cards (icon + name + description + toggle)
   - Each card shows required scopes
   - If Google not connected, show "Connect Google" button
   - Visual feedback for active/inactive plugins

### Chat Page (index.js)

1. **Action proposal block** — rendered when `action_proposal` is present in response:
   - Plugin icon + action display name
   - Parameter summary (human-readable)
   - "Execute" button (green) + "Cancel" button (gray)
2. **Action result block** — after execution:
   - Success: green checkmark + result summary + link to resource
   - Error: red icon + error message
   - Cancelled: gray "Cancelled" badge
3. **Google connection status** — indicator in agent settings showing OAuth status

### i18n (agents.json, chat.json)

```json
// agents.json
"types": {
  "actionnable": {
    "name": "Actionable",
    "description": "Execute tasks in Google Workspace"
  }
}

// chat.json
"actions": {
  "confirm": "Execute",
  "cancel": "Cancel",
  "pending": "Awaiting confirmation",
  "executing": "Executing...",
  "completed": "Completed",
  "failed": "Failed",
  "cancelled": "Cancelled"
}
```

---

## Plugin Details

### Google Docs Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `create_doc` | title, content (optional) | Create a new Google Doc |
| `update_doc` | doc_id, content | Update content of existing doc |
| `share_doc` | doc_id, email, role | Share doc with a user |

Scopes: `https://www.googleapis.com/auth/documents`, `https://www.googleapis.com/auth/drive.file`

### Google Sheets Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `create_sheet` | title, sheets (array of {name, headers, rows}) | Create spreadsheet |
| `update_sheet` | spreadsheet_id, range, values | Update cells |
| `read_sheet` | spreadsheet_id, range | Read cell values |

Scopes: `https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/drive.file`

### Gmail Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `send_email` | to, subject, body, cc (optional), bcc (optional) | Send email |
| `reply_email` | thread_id, body | Reply to a thread |
| `search_emails` | query, max_results | Search inbox |

Scopes: `https://www.googleapis.com/auth/gmail.send`, `https://www.googleapis.com/auth/gmail.readonly`

### Google Calendar Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `create_event` | title, start, end, attendees (optional), description (optional) | Create event |
| `list_events` | time_min, time_max, max_results | List upcoming events |
| `update_event` | event_id, fields to update | Modify event |

Scopes: `https://www.googleapis.com/auth/calendar.events`

### Google Slides Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `create_presentation` | title, slides (array of {title, body}) | Create presentation |
| `add_slide` | presentation_id, title, body | Add slide to existing presentation |

Scopes: `https://www.googleapis.com/auth/presentations`, `https://www.googleapis.com/auth/drive.file`

### Google Drive Plugin

| Action | Parameters | Description |
|--------|-----------|-------------|
| `create_folder` | name, parent_id (optional) | Create folder |
| `move_file` | file_id, folder_id | Move file to folder |
| `share_file` | file_id, email, role | Share file/folder |
| `search_files` | query, max_results | Search Drive |

Scopes: `https://www.googleapis.com/auth/drive.file`, `https://www.googleapis.com/auth/drive.readonly`

---

## Security

- **Token encryption**: OAuth tokens encrypted at rest using the same mechanism as Slack tokens (Fernet symmetric encryption via `encryption.py`)
- **Automatic token refresh**: Access tokens refreshed before every API call if expired
- **Rate limiting**: Per-user rate limit on action executions (configurable, default: 60 actions/hour)
- **Audit trail**: Every action execution logged with full params, result, timestamps, user/company context
- **Multi-tenant isolation**: RLS policies on `action_executions`, tokens scoped to user_id
- **Scope minimization**: Only request OAuth scopes for plugins the user has actually enabled
- **Google API errors**: Translated to user-friendly messages in the chat (quota exceeded, permission denied, etc.)
- **Revocation**: User can disconnect Google at any time; all tokens deleted, pending actions cancelled
- **Missing credentials**: If a user chats with an actionnable agent but hasn't connected Google, the agent responds conversationally (RAG only) and includes a message prompting the user to connect Google to enable actions

---

## Migration from Existing Code

The current actionnable agent code (Gemini-only flags in rag_engine.py, artisanal function calling in ask.py, actions in actions.py) will be replaced:

1. **Remove** `gemini_only` flag logic from `rag_engine.py` (4 locations)
2. **Remove** function calling prompt engineering from `routers/ask.py` (lines 370-645)
3. **Remove** old `actions.py` actions — replaced by plugin implementations
4. **Keep** `AgentAction` table temporarily for backward compatibility, mark as deprecated
5. **Migrate** existing `create_google_doc` and `create_google_sheet` logic into their respective plugins
6. **Update** `routers/ask.py` to use the new two-stage pipeline for actionnable agents

---

## Testing Strategy

- **Unit tests**: Each plugin tested independently with mocked Google API responses
- **Integration tests**: Full pipeline test (user message → action proposal → confirmation → execution)
- **OAuth flow tests**: Mock Google OAuth endpoints, test token storage/refresh/revocation
- **Frontend tests**: Action proposal rendering, confirmation flow, error states
- **Security tests**: Verify tenant isolation, token encryption, rate limiting
