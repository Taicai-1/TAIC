# Team Orchestration Design — Hierarchical Delegation with Specialized Companions

**Date:** 2026-06-02
**Status:** Approved
**Approach:** A — Orchestrateur integre (Leader as coordinator + synthesizer)

## Summary

Transform the existing team feature from simple semantic-routing to a full hierarchical orchestration system where the leader agent acts as an intelligent coordinator: analyzing questions via LLM, delegating to specialized sub-agents in parallel, and synthesizing their contributions into a unified response. Users define each member's specialization (free-form, with auto-detection available), and the chat UI shows transparent contribution details.

## Design Decisions

| Aspect | Decision |
|--------|----------|
| Orchestration type | Hierarchical with delegation — leader decides who to consult |
| Specialization definition | Free-form description + auto-detection from agent context/docs |
| Multi-agent consultation | Yes, leader can consult multiple agents per question |
| Transparency | Full detail — accordion showing each agent's individual contribution |
| Routing mechanism | LLM-based decision by leader agent |
| Scope | Full stack (backend + frontend) in a single cycle |

---

## 1. Data Model

### New table: `team_members`

Replaces the JSON `action_agent_ids` field with a proper relational model.

```sql
CREATE TABLE team_members (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL DEFAULT 'member',  -- 'leader' | 'member'
    specialization TEXT,                          -- user-defined specialty description
    auto_specialization TEXT,                     -- system-generated specialty suggestion
    position INTEGER NOT NULL DEFAULT 0,          -- display order
    company_id INTEGER REFERENCES companies(id),  -- tenant isolation
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(team_id, agent_id)
);
```

### Modified table: `teams`

```sql
ALTER TABLE teams ADD COLUMN orchestration_prompt TEXT;
-- After migration: DROP COLUMN leader_agent_id, DROP COLUMN action_agent_ids
```

- `orchestration_prompt`: optional custom routing instructions. When null, a default prompt is used.
- `leader_agent_id` and `action_agent_ids`: kept during transition, computed from `team_members` in GET responses.

### Modified table: `messages`

```sql
ALTER TABLE messages ADD COLUMN contributions_json TEXT;
```

Stores JSON array of individual agent contributions for display in chat history:

```json
[
  {
    "agent_id": 5,
    "agent_name": "Expert Finance",
    "specialization": "comptabilite et analyse financiere",
    "content": "Full response text from this agent..."
  }
]
```

---

## 2. Orchestration Engine (`backend/orchestrator.py`)

New file containing all orchestration logic.

### Phase 1 — Routing (LLM decision)

A dedicated LLM call using the leader agent's configured provider. The prompt includes:

- The user's question
- The list of team members with their specializations
- Instructions to return a JSON with selected agent IDs

**Default routing prompt:**

```
Tu es le coordinateur d'une equipe d'agents specialises.
Analyse la question suivante et determine quel(s) agent(s) consulter.

Agents disponibles:
{for each member: "- Agent #{id} \"{name}\" -- Specialite: {specialization}"}

Regles:
- Selectionne 1 a 3 agents maximum
- Si la question est transverse, selectionne plusieurs agents
- Si aucun agent n'est pertinent, retourne une liste vide (tu repondras toi-meme)

Retourne UNIQUEMENT un JSON: {"agent_ids": [5, 8], "reasoning": "..."}
```

When `teams.orchestration_prompt` is set, it replaces the default prompt above.

The LLM provider and model used for routing is the one configured on the leader agent.

### Phase 2 — Parallel execution

Selected agents are called concurrently via `asyncio.gather`:

- Each agent receives the question + its own context + its own RAG documents
- The existing `get_answer()` function is reused as-is for each agent
- Per-agent timeout: 30 seconds (configurable)
- If an agent fails, other contributions are preserved
- If all agents fail, leader responds alone with a warning

### Phase 3 — Synthesis

A second LLM call to the leader with:

- The original question
- All agent contributions with agent name and specialization
- Instructions to produce a unified, coherent response

**Synthesis prompt:**

```
Tu es le coordinateur de l'equipe "{team_name}". {team_contexte}

Voici les contributions de tes agents specialises:

{for each contribution:
"[Agent \"{name}\" -- {specialization}]:
{content}
"}

Synthetise ces contributions en une reponse claire et complete pour l'utilisateur.
Integre naturellement les informations sans repetition.
```

### Fallback behavior

| Scenario | Behavior |
|----------|----------|
| Routing selects no agents | Leader responds alone (normal agent behavior) |
| All selected agents fail | Leader responds alone with warning |
| Routing JSON malformed | Fallback to semantic similarity (current behavior) |
| Routing LLM call fails | Fallback to semantic similarity (current behavior) |

### LLM cost per team question

| Scenario | LLM calls |
|----------|-----------|
| Routing -> 1 agent -> synthesis | 3 calls |
| Routing -> 2 agents -> synthesis | 4 calls |
| Routing -> 3 agents -> synthesis | 5 calls |
| Routing -> no agent (leader alone) | 2 calls |

### Streaming (`/ask-stream`)

Two-phase streaming:

1. **Routing + execution phase** (buffered, not streamed):
   - SSE event `routing`: `{"agents": [{"id": 5, "name": "Expert Finance"}]}`
   - SSE event `contribution` (per agent): `{"agent_id": 5, "agent_name": "Expert Finance", "content": "..."}`
2. **Synthesis phase** (streamed token-by-token):
   - SSE event `token`: standard token streaming

---

## 3. Auto-detection of Specializations

### Endpoint: `POST /teams/suggest-specialization`

Request: `{ "agent_id": int }`
Response: `{ "specialization": "Expert en comptabilite et analyse financiere" }`

Uses a lightweight LLM call (Mistral small) analyzing:

1. Agent's `contexte` (system prompt) — primary source
2. Agent's document filenames — domain clues
3. Agent's `biographie` — public description

**Prompt:**

```
Analyse les informations suivantes sur un agent IA et genere
une description courte (1-2 phrases) de sa specialite/expertise.

Nom: {agent.name}
Contexte systeme: {agent.contexte[:500]}
Biographie: {agent.biographie[:200]}
Documents: {', '.join(doc.filename for doc in agent.documents[:10])}

Retourne UNIQUEMENT la description de specialite, rien d'autre.
```

### UX behavior

- On adding an agent to team -> auto-detection fires asynchronously
- Specialization field pre-filled with suggestion, labeled "Auto-detected"
- User can edit, accept, or clear
- `auto_specialization` stores the raw suggestion (for regeneration)
- `specialization` stores the user's final version
- "Regenerate" button available to re-run suggestion

---

## 4. API Endpoints

### New endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/teams/suggest-specialization` | Auto-detect agent specialization |
| PUT | `/teams/{team_id}/members` | Replace full team composition |
| PATCH | `/teams/{team_id}/members/{agent_id}` | Update individual member (specialization, position) |

### Modified endpoints

**`POST /teams`** — New payload:

```json
{
  "name": "Equipe Finance",
  "contexte": "Equipe specialisee dans l'analyse financiere",
  "orchestration_prompt": null,
  "members": [
    {"agent_id": 5, "role": "leader", "specialization": "Coordination et synthese financiere"},
    {"agent_id": 8, "role": "member", "specialization": "Analyse des marches"},
    {"agent_id": 12, "role": "member", "specialization": "Comptabilite et fiscalite"}
  ]
}
```

Backward compatibility: old format with `leader_agent_id` + `action_agent_ids` is auto-detected and converted.

Validation rules:
- Exactly 1 member with role "leader"
- At least 1 member with role "member"
- All agents must belong to the authenticated user
- Leader agent must be conversational type

**`GET /teams`** and **`GET /teams/{team_id}`** — Enriched response:

```json
{
  "id": 1,
  "name": "Equipe Finance",
  "contexte": "...",
  "orchestration_prompt": null,
  "members": [
    {
      "agent_id": 5,
      "role": "leader",
      "name": "Agent Principal",
      "specialization": "Coordination et synthese",
      "auto_specialization": "...",
      "position": 0
    },
    {
      "agent_id": 8,
      "role": "member",
      "name": "Analyste Marche",
      "specialization": "Veille concurrentielle",
      "auto_specialization": "...",
      "position": 1
    }
  ],
  "leader_agent_id": 5,
  "action_agent_ids": [8, 12],
  "leader_name": "Agent Principal",
  "action_agent_names": ["Analyste Marche", "Expert Compta"],
  "created_at": "..."
}
```

Legacy fields (`leader_agent_id`, `action_agent_ids`, `leader_name`, `action_agent_names`) computed from `team_members` for backward compatibility.

**`POST /ask`** with `team_id` — Enriched response:

```json
{
  "answer": "Synthesized response by leader...",
  "contributions": [
    {
      "agent_id": 8,
      "agent_name": "Analyste Marche",
      "specialization": "Veille concurrentielle",
      "content": "Selon mes analyses..."
    }
  ],
  "routing_reasoning": "Question transverse necessitant avis marche et comptable",
  "sources": [],
  "conversation_id": 42
}
```

---

## 5. Frontend — Team Creation Form (`pages/teams.js`)

### Multi-step form replacing current modal

**Step 1 — Basic info:**
- Team name (text input)
- Team context (textarea)

**Step 2 — Team composition:**

Leader selection:
- Dropdown of user's conversational agents
- On selection: specialization field appears, pre-filled by auto-detection
- Badge "Auto-detected" / "Customized"

Member addition:
- List of available agents with "+" button to add
- Each added member shows a card with:
  - Agent name
  - Specialization field (pre-filled by auto-detection, editable)
  - Badge indicating auto-detected vs customized
  - "Regenerate" button (refresh icon)
  - "Remove" button (x icon)
- Arrow buttons for reordering

**Step 3 — Preview and confirmation:**

Visual summary of the team structure (leader at top, members listed below with specializations). Create button.

### Team editing

- Edit button (pencil icon) on each team card in the grid
- Opens same form pre-filled with team data
- Allows add/remove members, change specializations, swap leader

### Technical details

- Steps managed by `step` state (1, 2, 3) with forward/back navigation
- Auto-detection calls are asynchronous and non-blocking
- Translations added in `teams` namespace
- No new page file; form stays in `teams.js`

---

## 6. Frontend — Chat Contributions Display

### Routing banner (during loading)

Triggered by SSE `routing` event. Shows cards for each consulted agent with pulse animation. Cards transition to "done" (checkmark) on receiving `contribution` event.

### Response with contributions accordion

After the synthesized response:
- Accordion labeled "Contributions" — **closed by default**
- Click to expand/collapse
- Each contribution shows: agent name, specialization, full content
- Stored in `contributions_json` on the message for history replay

### Special cases

| Case | Behavior |
|------|----------|
| Leader responds alone | No routing banner, no accordion. Normal response. |
| Single agent consulted | Accordion with one contribution, singular label |
| Agent error/timeout | Card shows red "Unavailable". Not in accordion. |

### New components in `ConversationComponents.js`

- `TeamRoutingBanner`: animated agent cards during consultation
- `TeamContributions`: collapsible accordion for contribution details

---

## 7. Migration and Backward Compatibility

### Data migration function: `migrate_teams_to_members()`

Added to `database.py`, executed at startup (idempotent, same pattern as `migrate_existing_company_memberships`):

```
For each existing Team:
1. Create TeamMember(team_id, agent_id=team.leader_agent_id, role="leader", position=0)
2. Parse team.action_agent_ids JSON array
3. For each agent_id: create TeamMember(role="member", position=i+1, specialization=null)
```

Auto-detection of specializations is not run during migration (can be triggered on-demand via UI).

### API backward compatibility

- Old POST format (`leader_agent_id` + `action_agent_ids`) auto-detected and converted
- Old GET fields (`leader_agent_id`, `action_agent_ids`, `leader_name`, `action_agent_names`) computed from `team_members`
- Deprecated fields removed in a future cycle after frontend migration

### Team deletion

`DELETE /teams/{team_id}` works unchanged. The `ON DELETE CASCADE` on `team_members.team_id` ensures all members are removed automatically when a team is deleted.

### Deployment order

1. Backend deployed first (new model + old fields still served)
2. Migration runs at startup (`migrate_teams_to_members`)
3. Frontend deployed second (uses new format)
4. Both coexist during transition

---

## 8. Files Impacted

| File | Change |
|------|--------|
| `backend/database.py` | New `TeamMember` model, `orchestration_prompt` on `Team`, `contributions_json` on `Message`, `migrate_teams_to_members()` |
| `backend/orchestrator.py` | **New file** — routing LLM, parallel execution, synthesis, auto-detection |
| `backend/routers/agents.py` | Modified team CRUD endpoints, new `/teams/suggest-specialization`, `PUT /teams/{id}/members`, `PATCH /teams/{id}/members/{agent_id}` |
| `backend/routers/ask.py` | Integrate orchestrator in `/ask` and `/ask-stream`, new SSE events |
| `backend/validation.py` | New Pydantic schemas: `TeamCreateV2`, `TeamMemberSchema`, `SuggestSpecializationRequest` |
| `frontend/pages/teams.js` | Multi-step creation form with specializations, team editing |
| `frontend/components/ConversationComponents.js` | New `TeamContributions` + `TeamRoutingBanner` components |
| `frontend/public/locales/*/teams.json` | New translation keys for form steps, specializations, contributions |
