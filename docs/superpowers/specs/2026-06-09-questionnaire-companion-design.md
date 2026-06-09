# Questionnaire Companion — Design Spec

## Summary

Add a new agent type `questionnaire` to TAIC Companion. Users create questionnaire agents with custom questions, invite respondents via email, and respondents answer through a public conversational chat interface. Responses are viewable within the agent and exportable to other agents' RAG pipelines.

## Approach

**Approach A (selected):** New agent type `questionnaire` integrated into the existing Agent system. Reuses the full infrastructure (auth, public page, sidebar, CRUD, email service). The questionnaire appears in the same agent list as other companions.

Alternatives considered and rejected:
- **Separate entity** — too much duplication, inconsistent with "everything is a Companion" concept
- **Plugin on existing agent** — mixes responsibilities, confusing UX

## Data Model

Three new tables, all with `company_id` for tenant isolation (matching existing RLS pattern).

### `questionnaire_questions`

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | |
| `agent_id` | FK → agents.id | Parent questionnaire agent |
| `company_id` | FK → companies.id | Tenant isolation |
| `question_text` | Text | The question text |
| `question_type` | String(20) | `open`, `single_choice`, `multiple_choice`, `rating` |
| `options` | Text (JSON) | For closed: `["Oui", "Non"]`. For rating: `{"min": 1, "max": 5}` |
| `position` | Integer | Display order |
| `required` | Boolean | Whether the question is mandatory |
| `created_at` | DateTime | |

### `questionnaire_responses`

One row per respondent per questionnaire.

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | |
| `agent_id` | FK → agents.id | The questionnaire agent |
| `company_id` | FK → companies.id | Tenant isolation |
| `respondent_email` | String(255) | Respondent email |
| `respondent_name` | String(255) | Name (optional) |
| `token` | String(64) unique | Unique token for public link |
| `status` | String(20) | `pending`, `in_progress`, `completed` |
| `invited_at` | DateTime | Invitation sent date |
| `started_at` | DateTime | First answer timestamp |
| `completed_at` | DateTime | Last question answered |

### `questionnaire_answers`

One row per question per respondent.

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer PK | |
| `response_id` | FK → questionnaire_responses.id | |
| `question_id` | FK → questionnaire_questions.id | |
| `company_id` | FK → companies.id | Tenant isolation |
| `answer_text` | Text | Free text or selected choice(s) as JSON |
| `answered_at` | DateTime | |

### Agent model changes

No new columns on the `Agent` table. The existing `type` field gains a new allowed value: `questionnaire`. The existing `llm_provider` defaults to `mistral` for questionnaire agents.

## User Flows

### Flow 1: Creating a questionnaire agent

1. User clicks "New agent", enters a name, selects type `questionnaire`
2. `agents.js` detects the type and renders the **question builder** instead of the standard RAG settings (contexte, biographie, documents)
3. The question builder contains:
   - **Welcome message** field: used by Mistral to generate a natural greeting
   - **Question list**: ordered cards with drag & drop reordering
   - Per question: text, type selector (open/single choice/multiple choice/rating), options editor if closed, required toggle
   - "Add question" button at the bottom
   - **Closing message** field: displayed after the last question
4. Hidden for questionnaire agents: Documents/RAG section, contexte/biographie, LLM provider selector

### Flow 2: Agent page tabs (questionnaire type)

- **Questions**: The builder described above
- **Invitations**: Enter emails, send invitations, see status (sent/answered)
- **Responses**: List of respondents with status, view each response, export to RAG

### Flow 3: Sending invitations

1. In the Invitations tab, user enters one or more email addresses
2. Clicks "Send" — backend creates `questionnaire_responses` rows with unique tokens and `status=pending`
3. Email sent via existing Brevo SMTP service (`email_service.py`) with branded TAIC template
4. Email contains: questionnaire name, company name, CTA button linking to `{FRONTEND_URL}/questionnaire/{token}`

### Flow 4: Respondent answers (public page)

**URL:** `/questionnaire/[token]`

1. Page verifies token. If valid and not completed, displays chat interface.
2. **Welcome**: Mistral generates a natural greeting from the configured welcome message. Displayed as an "assistant" chat bubble.
3. **Question flow**: Questions displayed one at a time as assistant messages. Input adapts by type:
   - **Open**: Standard text input
   - **Single choice**: Clickable chips/buttons below the bubble
   - **Multiple choice**: Checkbox chips + "Validate" button
   - **Rating**: Clickable star/number row (1-5 or 1-10)
4. Respondent answers → appears as "user" message → next question appears as assistant message
5. **After last question**: Mistral generates a closing message. Status set to `completed`.
6. **Already completed**: Shows "You have already answered this questionnaire. Thank you!"

**Visual design**: Same chat UI as `/chat/[agentId]` but simplified — no sidebar, no multiple conversations, no RAG sources. Just header with questionnaire name + message thread.

### Flow 5: Viewing responses

1. In the Responses tab: table with respondent name, email, status (pending/in progress/completed), completion date
2. Counter at top: "12 responses / 20 invitations sent"
3. Filter by status
4. Click a respondent → structured recap view (not chat format): each question with its answer below
   - Ratings shown visually (filled stars)
   - "Download PDF" button
   - "Export to agent" button

### Flow 6: Exporting to RAG

1. Select one or more responses via checkboxes in the list view
2. Click "Export to agent" → modal with agent selector (only `conversationnel`/`actionnable` agents from the same company)
3. Export creates a `Document` in the target agent:
   - `filename`: "Questionnaire - [name] - [respondent].md"
   - `content`: Structured Markdown (see format below)
   - `document_type`: "rag"
4. Document enters the existing RAG pipeline (chunking → Mistral embedding → pgvector). No pipeline modifications needed.

**Markdown format for RAG export:**

```markdown
# Questionnaire : [Questionnaire Name]
## Respondent : [Name] ([email])
## Date : [completion date]

### [Question 1 text]
[Answer]

### [Question 2 text]
Note : 4/5

### [Question 3 text]
Choices : Option A, Option C
```

## API Endpoints

### Authenticated endpoints — new router `backend/routers/questionnaires.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/agents/{id}/questions` | List questions for a questionnaire agent |
| `POST` | `/agents/{id}/questions` | Add a question |
| `PATCH` | `/agents/{id}/questions/{qid}` | Update a question |
| `DELETE` | `/agents/{id}/questions/{qid}` | Delete a question |
| `PUT` | `/agents/{id}/questions/reorder` | Reorder questions (receives ordered ID array) |
| `POST` | `/agents/{id}/invite` | Send invitations (list of emails) |
| `GET` | `/agents/{id}/responses` | List responses with status and filters |
| `GET` | `/agents/{id}/responses/{rid}` | Response detail with all answers |
| `GET` | `/agents/{id}/responses/{rid}/pdf` | Download PDF of a response |
| `POST` | `/agents/{id}/responses/export` | Export selected responses to target agent RAG |

### Public endpoints (no auth) — added to `backend/routers/public.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/questionnaire/{token}` | Get questionnaire data (name, questions, welcome message). Validates token and checks not already completed |
| `POST` | `/questionnaire/{token}/answer` | Submit answer to a question (`{question_id, answer_text}`) |
| `POST` | `/questionnaire/{token}/complete` | Mark questionnaire as completed, call Mistral for closing message |

## Technical Details

- **LLM**: Mistral for welcome/closing message generation (using existing `mistral_client.py`)
- **Email**: Brevo SMTP via existing `email_service.py` (`send_email` + `_wrap_template`)
- **PDF generation**: `weasyprint` (HTML template → PDF, simpler than reportlab for structured content)
- **Frontend**: Question builder components extracted into separate files under `frontend/components/questionnaire/` to avoid bloating `agents.js`
- **Public page**: New page at `frontend/pages/questionnaire/[token].js`, reusing chat UI components from `frontend/components/ConversationComponents.js`
- **Tenant isolation**: All new tables include `company_id` with existing RLS policies
