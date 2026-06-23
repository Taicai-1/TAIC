# Mission recaps — prompt & documents per scheduled recap (design)

**Date:** 2026-06-23
**Status:** Approved (design)
**Supersedes:** the mission-level prompt/docs delivered earlier today (`2026-06-23-mission-recaps-revamp-design.md`). That iteration put ONE prompt + one doc set on the mission; this iteration moves both to EACH scheduled recap.

## Context

A mission's "Récaps" tab lists scheduled recaps (`MissionRecapSchedule` rows: recurring/once + hour). Today the recap prompt (`Mission.recap_prompt`) and recap-source documents (`Document.is_mission_recap_source`) are defined ONCE per mission and shared by every scheduled recap. The user wants each scheduled recap ("un récap") to carry its OWN prompt and its OWN documents.

## Requirements (validated)

1. **Prompt per recap:** each `MissionRecapSchedule` has its own `recap_prompt`.
2. **Documents per recap:** documents are attached to a specific scheduled recap; a document belongs to exactly one recap and is used only when generating THAT recap.
3. **Shared mission Planning:** the mission's events (Planning tab) stay shared — recap generation still reads mission events. No per-recap planning is added (each recap already has its own timing row).
4. **Manual generation per recap:** each recap has its own "Générer maintenant" button using that recap's prompt + docs.
5. **Mission level removed (UI):** the mission-wide prompt textarea, the mission-wide recap-documents section, and the single mission-wide "Générer maintenant" button are removed from the Récaps tab.

## Decisions

- Documents link to a recap via a new `Document.recap_schedule_id` FK (→ `mission_recap_schedules.id`, `ON DELETE CASCADE`): deleting a recap deletes its docs. A recap doc has `mission_id` set (for tenant/RLS) AND `recap_schedule_id` set.
- The previously-shipped `Mission.recap_prompt` and `Document.is_mission_recap_source` columns are LEFT in the database (inert) to avoid a destructive migration. `is_mission_recap_source` is still set `True` on recap docs so the mission Documents tab keeps excluding them; the active discriminator for "which recap" is `recap_schedule_id`.
- Generation already receives `schedule_id` (`process_mission_recap(..., schedule_id=...)`). It now loads that schedule, uses `schedule.recap_prompt`, and scopes RAG to docs with `recap_schedule_id == schedule_id`.

## Out of scope
- Per-recap event planning (events stay mission-shared).
- Reworking the scheduler timing model, chat, or planning tabs.
- Removing the now-inert mission-level columns/endpoints from the database.

---

## 1. Data model (`backend/database.py`)
- `MissionRecapSchedule.recap_prompt` — `Column(Text, nullable=True)`.
- `Document.recap_schedule_id` — `Column(Integer, ForeignKey("mission_recap_schedules.id", ondelete="CASCADE"), nullable=True, index=True)`.
- `ensure_columns()`:
  - `("mission_recap_schedules", "recap_prompt", "TEXT")`
  - `("documents", "recap_schedule_id", "INTEGER REFERENCES mission_recap_schedules(id) ON DELETE CASCADE")`

## 2. Schemas (`backend/schemas/missions.py`)
- `RecapScheduleCreate` gains `recap_prompt: Optional[str] = Field(None, max_length=10000)` (inherited by `RecapScheduleUpdate`).

## 3. Endpoints (`backend/routers/missions.py`)
- `create_recap_schedule` / `update_recap_schedule`: persist `recap_prompt`.
- `_schedule_detail`: include `"recap_prompt"`.
- Per-recap documents (mirror the existing mission-doc endpoints, sync upload, atomic flag):
  - `POST /api/automations/missions/{mid}/recap-schedules/{sid}/documents` — upload; creates a `Document` with `mission_id`, `recap_schedule_id=sid`, `is_mission_recap_source=True` (atomically, via threaded params).
  - `GET  /api/automations/missions/{mid}/recap-schedules/{sid}/documents` — list docs where `recap_schedule_id == sid`.
  - `DELETE /api/automations/missions/{mid}/recap-schedules/{sid}/documents/{doc_id}` — delete, verifying `recap_schedule_id == sid`.
- Per-recap manual generation:
  - `POST /api/automations/missions/{mid}/recap-schedules/{sid}/generate` — calls `process_mission_recap(mission, db, trigger="manual", schedule_id=sid)`.
- The mission-level recap-document endpoints (`/missions/{id}/recap-documents`) and the mission-level `/recaps/generate` become unused by the UI. Leave them in place (harmless) OR remove — implementation may remove the three `/recap-documents` endpoints and the no-arg `/recaps/generate` to avoid dead code, since nothing else calls them. Keep `GET /recaps` (the generated-recaps list) and the schedule CRUD.

## 4. Generation (`backend/mission_recap.py` + `backend/rag_engine.py`)
- `process_mission_recap`: when `schedule_id` is provided, load the `MissionRecapSchedule`; use `schedule.recap_prompt` as `custom_prompt`; pass `schedule_id` into `enrich_events_with_docs` for doc scoping. (When `schedule_id` is None — legacy/scheduler-without-id — fall back to no custom prompt and no recap-doc scoping, i.e. no doc snippets.)
- `enrich_events_with_docs(mission, events, db, schedule_id=None)`: pass `recap_schedule_id=schedule_id` into the RAG search.
- `search_similar_texts_for_user`: replace/augment the `recap_source_only` param with `recap_schedule_id: int = None`; when set, filter `Document.recap_schedule_id == recap_schedule_id` inside the `if mission_id:` branch (tenant `company_id` filter unchanged). The old `recap_source_only` param is removed (it had one caller).
- The scheduler (`recap_scheduler.py`) already passes `schedule_id` when firing a scheduled recap — verify it does; scheduled recaps then automatically use that recap's prompt + docs.

## 5. Frontend (`frontend/components/automations/missions/`)
- `RecapsTab.js`: remove the mission-level prompt section, the mission-level recap-documents section, and the mission-level "Générer maintenant" button. Keep the generated-recaps list and the lifecycle section (companion/archive/delete). The schedules list (now expanded) is the main content.
- `RecapSchedules.js` → each `ScheduleRow` becomes an expandable card containing, below the existing timing controls:
  - a **prompt** textarea (bound to `schedule.recap_prompt`, saved via the schedule PUT — reuse the existing `commit()` which already PUTs the whole schedule),
  - a **documents** sub-section (upload / list / delete against `/recap-schedules/{sid}/documents`, mirroring the doc UI; sync upload, no polling),
  - a **"Générer maintenant"** button calling `/recap-schedules/{sid}/generate`.
- i18n (`automations.json` fr/en): add per-recap keys (prompt label/placeholder, documents label/hint/empty/upload/uploading/deleteConfirm/uploaded, generate/generating, the no-companion hint). Reuse existing keys where present.

## 6. Testing
- **Backend:** `RecapScheduleCreate` accepts `recap_prompt`; schedule create/update persists it and `_schedule_detail` returns it; per-recap doc upload sets `recap_schedule_id` + appears only in that recap's list; delete scoped to the recap; deleting a recap cascades its docs; `process_mission_recap(schedule_id=...)` uses the schedule's prompt; `search_similar_texts_for_user(recap_schedule_id=...)` filters to that recap's docs.
- **Regression:** the mission Documents tab still excludes recap docs; a recap with no docs generates from events + prompt only.

## File touch-list
- `backend/database.py`
- `backend/schemas/missions.py`
- `backend/routers/missions.py`
- `backend/mission_recap.py`, `backend/rag_engine.py`
- `frontend/components/automations/missions/RecapsTab.js`, `RecapSchedules.js`
- `frontend/public/locales/{fr,en}/automations.json`
- `backend/tests/test_missions.py`
