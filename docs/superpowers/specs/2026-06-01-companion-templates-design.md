# Companion Templates - Design Spec

## Overview

Companion Templates are reusable blueprints for creating agents within an organization. Admins create templates (e.g., "CTO", "Support Client", "Sales Rep") with pre-configured context, biography, type, and linked documents. Members use these templates as shortcuts when creating new companions — the form opens pre-filled, and the user can personalize before saving.

## Scope

- Organization-level templates (company_id scoped)
- Admin-only creation/editing, all members can use templates
- Core fields only in templates: name, description, category, icon, contexte, biographie, type
- Documents copied at DB level (Document + DocumentChunk rows) to preserve existing RAG pipeline filtering by agent_id
- Traceability: agents track which template they were created from

## Data Model

### Table: `agent_templates`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | Integer | PK, auto-increment | |
| `name` | String(100) | NOT NULL | Template display name ("CTO", "Support") |
| `description` | Text | nullable | What this template is for |
| `category` | String(50) | nullable | Grouping label ("Tech", "RH", "Sales") |
| `icon` | String(50) | nullable | Lucide icon name ("Monitor", "Headset") |
| `default_contexte` | Text | nullable | Pre-filled system prompt |
| `default_biographie` | Text | nullable | Pre-filled user-facing bio |
| `default_type` | String(32) | NOT NULL, default "conversationnel" | Agent type |
| `company_id` | Integer | FK -> companies.id, NOT NULL, indexed | Tenant isolation |
| `created_by_user_id` | Integer | FK -> users.id, NOT NULL | Admin who created |
| `created_at` | DateTime | default utcnow | |
| `updated_at` | DateTime | nullable | Last modification |

### Table: `agent_template_documents`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | Integer | PK, auto-increment | |
| `template_id` | Integer | FK -> agent_templates.id, ON DELETE CASCADE, NOT NULL | |
| `document_id` | Integer | FK -> documents.id, ON DELETE CASCADE, NOT NULL | |

Unique constraint on `(template_id, document_id)`.

### Modification to `agents` table

Add one nullable column:

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `template_id` | Integer | FK -> agent_templates.id, ON DELETE SET NULL, nullable | Source template if created from one |

## API Endpoints

New router: `backend/routers/templates.py`

### Template CRUD

**`GET /api/templates`** — List organization templates
- Auth: any authenticated member of the organization
- Query params: `category` (optional filter)
- Response: `{ templates: [{ id, name, description, category, icon, default_type, document_count, created_at }] }`
- Logic: filter by caller's company_id

**`POST /api/templates`** — Create a template
- Auth: admin only (`require_role(user_id, db, "admin")`)
- Body: `{ name, description?, category?, icon?, default_contexte?, default_biographie?, default_type?, document_ids?: int[] }`
- Response: `{ template: { id, name, ... } }`
- Logic: create AgentTemplate row, create AgentTemplateDocument rows for each document_id, validate documents belong to same company

**`GET /api/templates/{template_id}`** — Get template detail
- Auth: any member of the organization
- Response: `{ template: { id, name, description, category, icon, default_contexte, default_biographie, default_type, created_at, updated_at, documents: [{ id, filename }] } }`

**`PUT /api/templates/{template_id}`** — Update a template
- Auth: admin only
- Body: same as POST (partial update)
- Logic: update fields, replace document associations if `document_ids` provided

**`DELETE /api/templates/{template_id}`** — Delete a template
- Auth: admin only
- Logic: cascade deletes `agent_template_documents` rows. Agents with `template_id` pointing to this template get it set to NULL (ON DELETE SET NULL).

### Template Document Management

**`POST /api/templates/{template_id}/documents`** — Link documents to template
- Auth: admin only
- Body: `{ document_ids: [1, 5, 12] }`
- Logic: validate documents belong to same company, create AgentTemplateDocument rows (skip duplicates)

**`DELETE /api/templates/{template_id}/documents/{document_id}`** — Unlink a document
- Auth: admin only

### Agent Creation from Template

**`POST /api/templates/{template_id}/create-agent`** — Create agent from template
- Auth: any member of the organization
- Body: `{ name: string, contexte?: string, biographie?: string, type?: string }`
  - `name` is required (user must name their companion)
  - Other fields are optional overrides; if omitted, template defaults are used
- Response: `{ agent: { id, name, ... } }` (same shape as `POST /agents`)
- Logic:
  1. Load template + its documents
  2. Validate caller belongs to same company
  3. Create Agent with:
     - `name` from request body
     - `contexte` = override or `template.default_contexte`
     - `biographie` = override or `template.default_biographie`
     - `type` = override or `template.default_type`
     - `llm_provider` = resolved from type via `resolve_llm_provider()`
     - `template_id` = template.id
     - `company_id` = template.company_id
     - `user_id` = caller
     - `statut` = "prive" (default)
  4. For each template document: update `document.agent_id` is NOT changed (documents stay shared). Instead, the RAG query will need to include template-linked documents. Alternative: duplicate the Document-Agent association. Given the current architecture where documents have a single `agent_id`, we link the template documents to the new agent by creating new Document rows that reference the same `gcs_url` and chunks. This keeps the existing `agent_id`-based RAG filtering working without changes.

  **Document linking strategy (refined):** The current codebase filters RAG chunks by `Document.agent_id`. To avoid modifying the RAG engine, when creating an agent from a template:
  - For each template document, create a lightweight Document copy: same `filename`, `content`, `gcs_url`, `company_id`, `document_type`, but with `agent_id` = new agent's id.
  - Copy all DocumentChunk rows for that document (same `chunk_text`, `embedding_vec`, `company_id`), pointing to the new Document copy.
  - This means template documents get duplicated per agent at the chunk level, which consumes more DB storage but keeps the RAG pipeline unchanged and each agent's documents independent.

  5. Call `update_agent_embedding(agent, db)` if contexte is set
  6. Return created agent

## Frontend

### Sidebar (`components/Sidebar.js`)

Add entry to `NAV_ITEMS` after the agents item:

```javascript
{ href: '/templates', labelKey: 'navigation.templates', Icon: LayoutTemplate }
```

Import `LayoutTemplate` from `lucide-react`. Visible to all authenticated users (the page itself handles admin vs member view).

### Page `/templates` (`pages/templates.js`)

**Layout:** Uses existing `Layout` component. Page title "Templates".

**Admin view:**
- Header with title + "+ Nouveau template" button
- Category filter pills (All, Tech, RH, Sales, etc. — derived from existing templates)
- Grid of template cards (3 columns on desktop, 2 on tablet, 1 on mobile)
- Each card shows: icon, name, description (truncated), category badge, document count
- Click card → opens edit modal
- Card has "..." menu or hover actions for edit/delete

**Member view:**
- Same grid, no "+ Nouveau template" button, no edit/delete actions
- Cards are read-only, serve as a catalog
- Each card has a "Creer un companion" button that navigates to `/agents` with `?template_id=X` query param, triggering the pre-filled creation flow

**Template creation/edit modal:**
- Name input (required)
- Description textarea
- Category input (free text or select from existing categories)
- Icon picker: text input for Lucide icon name (e.g. "Monitor", "Headset", "ShieldCheck") with a help link to lucide.dev/icons
- Contexte textarea (system prompt)
- Biographie textarea
- Type select (conversationnel / recherche_live / visuel)
- Document picker: searchable list of organization's documents with checkboxes

### Modified Agent Creation Flow (`pages/agents.js`)

The "+ Nouveau companion" button now opens a 2-step modal:

**Step 1: Choose how to start**
- "Partir de zero" option → advances to step 2 with empty form (current behavior)
- Grid of available templates → clicking one advances to step 2 with form pre-filled from template defaults
- Templates fetched via `GET /api/templates` on modal open
- If no templates exist for the organization, step 1 is skipped entirely and the modal opens directly to step 2 (empty form) — same as current behavior

**Step 2: Agent creation form**
- Same form as current, but fields pre-filled if a template was chosen
- Small banner at top: "Base sur le template CTO" (if from template)
- User can modify any pre-filled field
- Submit calls `POST /api/templates/{id}/create-agent` (if from template) or `POST /agents` (if from scratch)

**Query param support:** If page loads with `?template_id=X`:
- Auto-open the creation modal
- Skip step 1, go directly to step 2 with template data pre-filled
- This supports the "Creer un companion" button from the templates page

### Internationalization

Add translation keys to `public/locales/{fr,en}/`:
- `common.json`: `navigation.templates` key
- New `templates.json` namespace with keys for page title, buttons, form labels, toasts, empty states

## Files to Create

| File | Purpose |
|------|---------|
| `backend/routers/templates.py` | Template API router |
| `backend/schemas/templates.py` | Pydantic request/response schemas |
| `frontend/pages/templates.js` | Templates page |
| `frontend/public/locales/fr/templates.json` | French translations |
| `frontend/public/locales/en/templates.json` | English translations |

## Files to Modify

| File | Change |
|------|--------|
| `backend/database.py` | Add `AgentTemplate`, `AgentTemplateDocument` models, add `template_id` to Agent |
| `backend/main.py` | Import and include templates router |
| `backend/validation.py` | Add `TemplateCreateValidated` schema |
| `frontend/components/Sidebar.js` | Add Templates nav item |
| `frontend/pages/agents.js` | 2-step creation modal with template picker |
| `frontend/public/locales/fr/common.json` | Add `navigation.templates` |
| `frontend/public/locales/en/common.json` | Add `navigation.templates` |

## Error Handling

- Template CRUD: standard 400/403/404 responses consistent with existing patterns
- Create agent from template: if a template document was deleted between template creation and agent creation, skip it silently (log warning) rather than failing
- Template deletion: agents keep `template_id = NULL` (ON DELETE SET NULL), no impact on existing agents

## Migration

Alembic migration to:
1. Create `agent_templates` table
2. Create `agent_template_documents` table
3. Add `template_id` column to `agents` table
