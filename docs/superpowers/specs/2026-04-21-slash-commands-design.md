# Slash Commands — Prompt Shortcuts for Companions

**Date:** 2026-04-21
**Status:** Approved

## Overview

Allow organization admins to configure reusable prompt shortcuts (slash commands) that users can trigger in the chat with a `/command` syntax. Each shortcut maps a command name to a full prompt and is scoped to specific companions.

## Data Model

### Field on `Team` model (`backend/database.py`)

```python
slash_commands = Column(Text, nullable=True)  # JSON
```

### JSON Structure

```json
[
  {
    "id": "uuid-v4",
    "command": "analyse",
    "prompt": "Analyse moi les tendances sur l'IA sur les 6 derniers mois...",
    "agent_ids": [12, 45]
  }
]
```

- `id`: UUID generated server-side, used for identifying entries during edit/delete
- `command`: alphanumeric + hyphens/underscores, no spaces, no leading `/`. Must be unique within a team.
- `prompt`: the full text sent to the LLM when the command is triggered
- `agent_ids`: list of Agent IDs that have access to this command. Empty array = no agents.

### Validation Rules

- `command`: regex `^[a-zA-Z0-9_-]+$`, max 32 chars, unique per team
- `prompt`: non-empty, max 5000 chars
- `agent_ids`: each ID must reference an existing agent belonging to the team

## API Endpoints

### `GET /teams/{team_id}/slash-commands`

Returns the list of slash commands for the team. Accepts optional `?agent_id=X` query param to filter commands accessible to a specific agent.

- **Auth:** verified user must be member of the team
- **Response:** `[{ id, command, prompt, agent_ids }]`
- When `agent_id` is provided, returns only commands where `agent_id` is in `agent_ids`

### `PUT /teams/{team_id}/slash-commands`

Replaces the entire slash commands config for the team.

- **Auth:** verified user must be admin of the team
- **Body:** `[{ id?, command, prompt, agent_ids }]`
- Entries without `id` get a new UUID generated server-side
- Validates uniqueness of command names, format, agent_ids existence
- **Response:** the saved array with all IDs populated

### Modification: `DELETE /agents/{id}`

After deleting the agent, iterate through the team's `slash_commands` JSON and remove the deleted agent's ID from all `agent_ids` arrays. If an `agent_ids` array becomes empty, the command entry remains (admin can reassign later).

### Modification: `POST /ask`

No change needed. The frontend resolves the slash command to its prompt before sending. The backend receives the final prompt text directly.

## Frontend: Settings UI

### Location

New section "Raccourcis Prompts" (Prompt Shortcuts) in the organization/team settings page.

### Table

| Column | Content |
|--------|---------|
| Prompt | Truncated prompt text (ellipsis) |
| Commande / | Command name displayed as `/name` badge |
| Companions | List of assigned agent names as badges |
| Actions | Edit + Delete icon buttons |

- "Ajouter un raccourci" button above the table
- Empty state message when no commands configured

### Add/Edit Modal

- **Command name field:** text input with `/` prefix displayed, user types only the name
- **Prompt field:** textarea for the full prompt text
- **Companions field:** multi-select with agent names as removable badges, dropdown to add agents
- **Buttons:** Cancel + Save

## Frontend: Chat Autocomplete

### Trigger

Menu appears when the user types `/` as the first character in the chat input field.

### Behavior

- Menu shows above the input, listing available commands for the current agent
- Each row: command name (purple) + truncated prompt preview (gray)
- Real-time filtering as user types (e.g., `/ana` shows only `/analyse`)
- Keyboard navigation: Arrow Up/Down to highlight, Enter to select
- Click on a row selects the command
- Escape or deleting the `/` closes the menu
- Only commands assigned to the current companion are displayed

### On Selection

1. The input field shows the `/command` text
2. The message is sent immediately
3. In the chat, the user message displays as `/command` (visible to user)
4. The actual prompt text is sent to `POST /ask` (backend receives the full prompt, not the `/command`)

### Data Loading

On chat page load, fetch commands for the current agent via `GET /teams/{team_id}/slash-commands?agent_id={agent_id}`. Cache in component state.

## Execution Flow

```
User types "/" → Autocomplete menu appears
User selects "/analyse" → Input shows "/analyse"
Message sent → Chat displays "/analyse" as user message
Frontend resolves → Sends full prompt to POST /ask
Backend processes → Normal RAG pipeline with the prompt
Response displayed → Normal assistant message
```

## Cleanup on Agent Deletion

When an agent is deleted via `DELETE /agents/{id}`:

1. Delete the agent (existing logic)
2. Load the team's `slash_commands` JSON
3. For each command entry, remove the deleted agent's ID from `agent_ids`
4. Save the updated JSON back to the team

## Files to Modify

### Backend
- `backend/database.py` — Add `slash_commands` column to `Team` model
- `backend/main.py` — Add GET/PUT endpoints for slash commands, modify DELETE agent endpoint

### Frontend
- `frontend/pages/organization.js` — Add "Raccourcis Prompts" section with table + add/edit modal
- `frontend/pages/chat/[agentId].js` — Add autocomplete menu, command resolution logic
