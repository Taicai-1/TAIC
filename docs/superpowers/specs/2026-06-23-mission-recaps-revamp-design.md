# Mission recaps revamp — design

**Date:** 2026-06-23
**Status:** Approved (design) — pending spec review

## Context

A mission's detail view has 5 tabs: `planning · documents · recaps · chat · settings`.
The `settings` (Réglages) tab holds recap schedules + companion assignment + mission
archive/delete. Mission recaps today have **no custom prompt** and use ALL the
mission's documents as RAG sources. We want recaps to be configurable like companion
recaps (custom prompt + dedicated source documents), the recap UI consolidated, and
the chat tab renamed/moved.

## Requirements (validated)

1. **Merge** the `recaps` and `settings` tabs into a single **Récaps** tab.
2. **Recap prompt:** one per mission (`Mission.recap_prompt`), used for all its recaps
   (mirrors companion `weekly_recap_prompt`).
3. **Recap source documents:** documents uploaded specifically in the recap section,
   used **only** as recap sources, separate from the mission's general Documents tab.
4. **Rename** the `chat` tab to **Aide** and move it to the far right (last).

## Decisions

- Recap source docs are flagged on `Document` (`is_mission_recap_source` boolean), not a
  new association table (a recap doc belongs to one mission's recap → a flag suffices).
- Recap generation sources **only** the recap-source docs (not the mission's general docs).

## Out of scope
- Per-schedule prompts (one prompt per mission only).
- Reworking the mission chat or planning tabs.

---

## 1. Tabs (`frontend/components/automations/missions/MissionDetail.js`)

- `SUB_TABS` becomes `['planning', 'documents', 'recaps', 'aide']`.
  - `settings` removed; its content moves into the merged Récaps tab.
  - `chat` renamed to `aide` (label only — still renders `ChatTab`), positioned last.
- i18n (`frontend/public/locales/{fr,en}/automations.json`, `missions.detail.tabs`):
  add `aide` ("Aide" / "Help"), remove/keep `chat` and `settings` keys as needed.

## 2. Data model (`backend/database.py`)

- **`Mission.recap_prompt`** — `Column(Text, nullable=True)`. The mission's recap prompt.
- **`Document.is_mission_recap_source`** — `Column(Boolean, nullable=False, default=False, server_default="false")`.
  A recap source doc has `mission_id` set AND `is_mission_recap_source = True`.
- Both added to the model AND to `ensure_columns()` (ADD COLUMN IF NOT EXISTS):
  - `("missions", "recap_prompt", "TEXT")`
  - `("documents", "is_mission_recap_source", "BOOLEAN NOT NULL DEFAULT FALSE")`

## 3. Backend endpoints (`backend/routers/missions.py`)

Mirror the existing mission-documents endpoints (upload/list/delete), but for recap docs:
- **`POST /api/automations/missions/{mission_id}/recap-documents`** — upload; creates a
  `Document` with `mission_id` + `is_mission_recap_source=True` (same processing pipeline as
  mission docs: validation, GCS, chunking).
- **`GET /api/automations/missions/{mission_id}/recap-documents`** — list `Document` where
  `mission_id == mission.id AND is_mission_recap_source == True`.
- **`DELETE /api/automations/missions/{mission_id}/recap-documents/{document_id}`** — delete,
  verifying it belongs to the mission and is a recap source.
- The existing mission-documents **list endpoint** must now EXCLUDE recap-source docs
  (`is_mission_recap_source == False`) so the two sets don't overlap.
- **`recap_prompt`** added to the mission update path: extend `MissionUpdate`
  (`backend/schemas/missions.py`) with `recap_prompt: Optional[str]`, apply it in the mission
  update endpoint, and include `recap_prompt` in the mission detail response.

## 4. Recap generation (`backend/mission_recap.py`)

- `build_mission_recap_prompt(...)` gains a `custom_prompt: str | None = None` param; when
  provided it **replaces** the default hardcoded system prompt (same pattern as
  `weekly_recap.build_recap_prompt`'s `custom_prompt`).
- `process_mission_recap(...)` reads `mission.recap_prompt` and passes it as `custom_prompt`.
- `enrich_events_with_docs(...)` (the RAG source step) filters the document/chunk query to
  the mission's **recap-source docs only** (`is_mission_recap_source == True`) instead of all
  `mission_id` docs. If there are none, the recap is generated from events + agent context only.

## 5. Frontend — merged Récaps tab

A single component (extend `RecapsTab.js` or a new `MissionRecapTab.js`) stacking, top→bottom:
1. **Recap prompt** — textarea bound to `mission.recap_prompt` + Save (PUT mission update).
2. **Recap documents** — upload / list / delete, calling the new `/recap-documents`
   endpoints (mirror `DocumentsTab.js`).
3. **Schedules** — the existing `RecapSchedules` component.
4. **Generated recaps** — the existing recaps list + "Générer maintenant" button.
5. **Mission lifecycle** — companion assignment dropdown + Archive + Delete (from `SettingsTab`).

`SettingsTab.js` is removed (its pieces relocate into the merged tab). `ChatTab` stays as-is,
shown under the `aide` tab.

## 6. Testing

- **Backend:** `recap_prompt` persists via mission update + appears in detail; recap-doc
  upload sets `is_mission_recap_source=True`; recap-doc list returns only those; the mission
  documents list excludes recap-source docs; `build_mission_recap_prompt(custom_prompt=...)`
  uses the custom prompt; `enrich_events_with_docs` only pulls recap-source docs.
- **Regression:** a normal mission document still appears in the Documents tab and is NOT
  used by the recap; existing recap schedules/generation still work when no prompt/docs set.

## File touch-list (for the plan)
- `backend/database.py` (Mission.recap_prompt, Document.is_mission_recap_source, ensure_columns)
- `backend/schemas/missions.py` (MissionUpdate.recap_prompt)
- `backend/routers/missions.py` (recap-documents endpoints, exclude recap docs from mission docs list, recap_prompt in update + detail)
- `backend/mission_recap.py` (custom_prompt + recap-source doc filtering)
- `frontend/components/automations/missions/MissionDetail.js` (tabs)
- `frontend/components/automations/missions/RecapsTab.js` (merged tab) — absorbs `SettingsTab.js` (removed)
- `frontend/public/locales/{fr,en}/automations.json` (tab labels)
- Tests: `backend/tests/test_missions.py` (extend)
