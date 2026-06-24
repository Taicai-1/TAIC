# Mission Recaps Per-Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` checkboxes.

**Goal:** Move the recap prompt and recap source documents from the mission level to each scheduled recap (`MissionRecapSchedule`), with a per-recap "Generate now"; keep mission events shared.

**Architecture:** Add `MissionRecapSchedule.recap_prompt` and `Document.recap_schedule_id` (FK, cascade). Per-recap document endpoints under `/recap-schedules/{sid}/documents`; a per-recap `/generate`. Generation (already given `schedule_id`) loads the schedule, uses its prompt, and scopes RAG to that recap's docs. Frontend turns each schedule row into a card with prompt + docs + generate.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, Next.js (Pages Router), next-i18next.

**Grounding (current code):**
- `MissionRecapSchedule` model: database.py:873 (fields kind/weekday/run_date/hour/enabled/last_run_at).
- `Document` flags incl. `is_mission_recap_source`: database.py ~612; doc processing threads params through `ingest_text_content` (creates `Document(...)`, ~rag_engine.py:1103-1120) and `process_document_for_user` (rag_engine.py:1169) — both already accept `is_mission_recap_source`.
- `search_similar_texts_for_user`: rag_engine.py:836; mission branch at :906-910 currently has `if recap_source_only: filter(is_mission_recap_source.is_(True))`.
- `enrich_events_with_docs`: mission_recap.py:42 (passes `recap_source_only=True`).
- `process_mission_recap(mission, db, trigger, run_date, schedule_id)`: mission_recap.py:139; builds prompt with `custom_prompt=getattr(mission,"recap_prompt",None)` at :186-188; calls `enrich_events_with_docs(mission, upcoming, db)` at :185.
- Schedule endpoints: routers/missions.py:442-533; `_schedule_detail`: :430; mission-level recap-doc endpoints: :639-715; `list_recaps`: :720; mission-level `/recaps/generate`: :752.
- Scheduler already calls `process_mission_recap(..., schedule_id=schedule.id)`: recap_scheduler.py:143.
- Frontend: `RecapSchedules.js` (ScheduleRow with `commit()` PUTting the whole schedule); `RecapsTab.js` (mission-level prompt + docs + generate sections to remove); `DocumentsTab.js` (doc UI to mirror).

---

## Task 1: Data model + migration

**Files:** `backend/database.py`; Test `backend/tests/test_missions.py`.

- [ ] **Step 1:** Add to `MissionRecapSchedule` (after `last_run_at`, ~database.py:884):
```python
    recap_prompt = Column(Text, nullable=True)  # this recap's own prompt
```

- [ ] **Step 2:** Add to the `Document` model (next to `is_mission_recap_source`):
```python
    recap_schedule_id = Column(
        Integer,
        ForeignKey("mission_recap_schedules.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )  # the scheduled recap this document is a source for
```

- [ ] **Step 3:** Add to `ensure_columns()` migrations list:
```python
        ("mission_recap_schedules", "recap_prompt", "TEXT"),
        ("documents", "recap_schedule_id", "INTEGER REFERENCES mission_recap_schedules(id) ON DELETE CASCADE"),
```

- [ ] **Step 4: Test** (append to test_missions.py):
```python
def test_recap_schedule_prompt_and_doc_schedule_link_columns_exist():
    from database import Document, MissionRecapSchedule

    assert hasattr(MissionRecapSchedule, "recap_prompt")
    assert hasattr(Document, "recap_schedule_id")
```
Run: `cd backend && python -m pytest tests/test_missions.py -k schedule_prompt_and_doc_schedule_link -q` → PASS.

- [ ] **Step 5: Commit** `feat(missions): per-recap recap_prompt + Document.recap_schedule_id columns`.

---

## Task 2: recap_prompt in schedule create/update/detail

**Files:** `backend/schemas/missions.py`, `backend/routers/missions.py`.

- [ ] **Step 1:** In `schemas/missions.py`, add to `RecapScheduleCreate` (inherited by `RecapScheduleUpdate`):
```python
    recap_prompt: Optional[str] = Field(None, max_length=10000)
```

- [ ] **Step 2:** In `create_recap_schedule` (missions.py:468), add `recap_prompt=body.recap_prompt,` to the `MissionRecapSchedule(...)` constructor.

- [ ] **Step 3:** In `update_recap_schedule` (missions.py:503-507 block), add:
```python
    schedule.recap_prompt = body.recap_prompt
```

- [ ] **Step 4:** In `_schedule_detail` (missions.py:430), add to the returned dict:
```python
        "recap_prompt": s.recap_prompt,
```

- [ ] **Step 5: Test:**
```python
def test_recap_schedule_create_schema_accepts_recap_prompt():
    from schemas.missions import RecapScheduleCreate

    s = RecapScheduleCreate(kind="recurring", weekday=0, hour=8, recap_prompt="hi")
    assert s.recap_prompt == "hi"
```
Run `cd backend && python -m pytest tests/test_missions.py -q`. Commit `feat(missions): persist + expose recap_prompt on each scheduled recap`.

---

## Task 3: Per-recap document endpoints + thread recap_schedule_id

**Files:** `backend/rag_engine.py`, `backend/routers/missions.py`.

- [ ] **Step 1: Thread `recap_schedule_id` through doc processing.** In `rag_engine.ingest_text_content` add param `recap_schedule_id: int = None` (next to `is_mission_recap_source`) and pass `recap_schedule_id=recap_schedule_id,` into the `Document(...)` constructor. In `process_document_for_user` add the same param and forward it in its `ingest_text_content(...)` call.

- [ ] **Step 2: Add per-recap doc endpoints** in `routers/missions.py` (after the schedule CRUD, ~line 534). They look up the schedule (scoped to the mission) then mirror the mission-doc pattern, sync + atomic:
```python
@router.post("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}/documents")
async def upload_recap_schedule_document(
    mission_id: int,
    schedule_id: int,
    file: UploadFile = File(...),
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Upload a document used ONLY as a source for this scheduled recap."""
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    schedule = (
        db.query(MissionRecapSchedule)
        .filter(MissionRecapSchedule.id == schedule_id, MissionRecapSchedule.mission_id == mission.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if not any(file.filename.lower().endswith(ext) for ext in ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="Type de fichier non supporté")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux")

    from rag_engine import process_document_for_user

    doc_id = process_document_for_user(
        file.filename, content, user_id, db, agent_id=None, company_id=mission.company_id,
        mission_id=mission.id, is_mission_recap_source=True, recap_schedule_id=schedule.id,
    )
    return {"filename": file.filename, "document_id": doc_id, "status": "uploaded"}


@router.get("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}/documents")
async def list_recap_schedule_documents(
    mission_id: int, schedule_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    docs = (
        db.query(Document)
        .filter(Document.mission_id == mission.id, Document.recap_schedule_id == schedule_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in docs
        ]
    }


@router.delete("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}/documents/{document_id}")
async def delete_recap_schedule_document(
    mission_id: int,
    schedule_id: int,
    document_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.mission_id == mission.id,
            Document.recap_schedule_id == schedule_id,
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"success": True}
```

- [ ] **Step 3: Remove the now-dead mission-level recap-document endpoints** (`upload_mission_recap_document`, `list_mission_recap_documents`, `delete_mission_recap_document` at missions.py:639-715). Nothing calls them after the frontend change. (Keep `list_mission_documents` with its `is_mission_recap_source.is_(False)` exclusion — recap docs still carry that flag so they stay out of the Documents tab.)

- [ ] **Step 4: Test** (PG-backed, skip-aware): create a mission + a schedule; seed a `Document` with `recap_schedule_id=sid, is_mission_recap_source=True`; assert it appears in the schedule's docs list, NOT in the mission Documents list; delete via the scoped endpoint; assert deleting the schedule cascade-deletes its docs. Run `cd backend && python -m pytest tests/test_missions.py -q`. Commit `feat(missions): per-recap document upload/list/delete endpoints`.

---

## Task 4: Generation uses the recap's prompt + its docs

**Files:** `backend/rag_engine.py`, `backend/mission_recap.py`, `backend/routers/missions.py`.

- [ ] **Step 1: RAG scoping by schedule.** In `rag_engine.search_similar_texts_for_user`, REPLACE the `recap_source_only: bool = False` param with `recap_schedule_id: int = None`. In the `if mission_id:` branch, replace the old `if recap_source_only: ...is_mission_recap_source...` lines with:
```python
        if mission_id:
            query = query.filter(Document.mission_id == mission_id)
            if recap_schedule_id is not None:
                query = query.filter(Document.recap_schedule_id == recap_schedule_id)
```
(Tenant `company_id` filters above are unchanged.)

- [ ] **Step 2:** In `mission_recap.enrich_events_with_docs`, add a `schedule_id: int | None = None` param and change the `search_similar_texts_for_user(...)` call to pass `recap_schedule_id=schedule_id` instead of `recap_source_only=True`.

- [ ] **Step 3:** In `process_mission_recap` (mission_recap.py:139), load the schedule and use its prompt + scope docs. Replace the enrich call (:185) and prompt build (:186-188):
```python
        schedule = None
        if schedule_id is not None:
            from database import MissionRecapSchedule

            schedule = db.query(MissionRecapSchedule).filter(MissionRecapSchedule.id == schedule_id).first()
        recall = fetch_events(mission.id, rc_start, rc_end, db)
        enriched = enrich_events_with_docs(mission, upcoming, db, schedule_id=schedule_id)
        prompt = build_mission_recap_prompt(
            mission, agent, recall, enriched,
            custom_prompt=(schedule.recap_prompt if schedule else None),
        )
```
(Keep the comment about running RAG before the first commit. `build_mission_recap_prompt`'s `custom_prompt` param already exists.)

- [ ] **Step 4: Per-recap manual generate endpoint.** In `routers/missions.py`, REPLACE the mission-level `generate_recap_now` (:752-768) with a per-recap version:
```python
@router.post("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}/generate")
async def generate_recap_schedule_now(
    mission_id: int, schedule_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    """Generate this scheduled recap on demand (synchronous, no email, no scheduler impact)."""
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    if not mission.agent_id:
        raise HTTPException(status_code=400, detail="Connectez un companion à la mission d'abord")
    schedule = (
        db.query(MissionRecapSchedule)
        .filter(MissionRecapSchedule.id == schedule_id, MissionRecapSchedule.mission_id == mission.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    from mission_recap import process_mission_recap

    result = process_mission_recap(mission, db, trigger="manual", schedule_id=schedule.id)
    if result["status"] == "no_data":
        raise HTTPException(status_code=400, detail="Aucun évènement à venir cette semaine")
    if result["status"] == "error":
        raise HTTPException(status_code=502, detail="La génération du récap a échoué")
    return {"recap_id": result["recap_id"], "content": result["content"]}
```

- [ ] **Step 5: Tests:** `build_mission_recap_prompt` custom-prompt tests already exist (keep them). Add: with a `types.SimpleNamespace` schedule passing through `process_mission_recap` is hard without a DB — instead unit-test the RAG param rename indirectly by asserting `search_similar_texts_for_user` accepts `recap_schedule_id` (e.g. `inspect.signature`):
```python
def test_search_similar_texts_accepts_recap_schedule_id():
    import inspect
    from rag_engine import search_similar_texts_for_user

    params = inspect.signature(search_similar_texts_for_user).parameters
    assert "recap_schedule_id" in params
    assert "recap_source_only" not in params
```
Run `cd backend && python -m pytest tests/test_missions.py -q`. Commit `feat(missions): recap generation uses the scheduled recap's prompt + its docs`.

---

## Task 5: Frontend — per-recap prompt + docs + generate

**Files:** `frontend/components/automations/missions/RecapSchedules.js`, `RecapsTab.js`, `frontend/public/locales/{fr,en}/automations.json`.

- [ ] **Step 1: `RecapSchedules.js` — expand each `ScheduleRow` into a card.** Keep the existing timing controls (checkbox, kind, weekday/date, hour, delete). The `commit()` already PUTs the whole schedule; extend its payload to include `recap_prompt`. Add below the timing row:
  - a **prompt** `<textarea>` bound to local `recapPrompt` state (init `schedule.recap_prompt || ''`, resync in the existing `useEffect([schedule])`), with a small **Save** button calling `onSave(schedule.id, {<timing...>, recap_prompt: recapPrompt})` — i.e. extend `commit()` to read `recapPrompt` and always include `recap_prompt` in its payload, and give the textarea an `onBlur={() => commit()}`.
  - a **documents** sub-section: `useState([])` + `loadDocs` (GET `/recap-schedules/${schedule.id}/documents`), an upload button (hidden file input; POST multipart, sync — NO `/upload-status` polling), a list with delete (DELETE `/recap-schedules/${schedule.id}/documents/${id}`). Mirror `DocumentsTab.js` structure but sync. Only fetch docs once the schedule has a real id (it always does after creation).
  - a **"Générer maintenant"** button: POST `/recap-schedules/${schedule.id}/generate`; on success toast + (optionally) call an `onGenerated` prop so `RecapsTab` reloads its recaps list; disable while generating and when the mission has no companion (pass a `hasCompanion` prop down from `RecapsTab` → `RecapSchedules` → `ScheduleRow`).

  Because the row grows, change the outer `ScheduleRow` container from a single flex line to a `div` card (e.g. `className="px-3 py-3 bg-white border border-gray-200 rounded-card space-y-3"`) with the timing controls in an inner `flex flex-wrap items-center gap-2` row.

- [ ] **Step 2: `RecapsTab.js` — remove mission-level sections.** Delete section (1) recap prompt, section (2) recap documents, and the mission-level "Générer maintenant" button + its `generate`/`recaps` wiring is partly reused: keep the **generated recaps list** and its `loadRecaps`. Keep the **lifecycle** section (companion/archive/delete) and the shared `form`/`save`/`remove`. Render `<RecapSchedules missionId={missionId} hasCompanion={hasCompanion} onGenerated={loadRecaps} />`. Remove now-unused imports/state (`fileRef`, recap-doc state, `Upload/FileText/Trash2` if no longer used in this file — they move to RecapSchedules). Remove the recap-prompt textarea + its `recap_prompt` form field (prompt now lives per schedule).

- [ ] **Step 3: i18n** — add to both `automations.json` under `missions.settings.recapSchedules` (where schedule labels already live):
  FR:
```json
"prompt": "Prompt de ce récap",
"promptPlaceholder": "Instructions pour générer ce récap…",
"docsTitle": "Documents de ce récap",
"docsHint": "Sources utilisées uniquement pour ce récap.",
"docsUpload": "Ajouter un document",
"docsUploading": "Import…",
"docsEmpty": "Aucun document.",
"docsDeleteConfirm": "Supprimer ce document ?",
"docsUploaded": "Document ajouté",
"generate": "Générer maintenant",
"generating": "Génération…",
"generated": "Récap généré",
"noCompanion": "Connectez un companion à la mission pour générer."
```
  EN:
```json
"prompt": "This recap's prompt",
"promptPlaceholder": "Instructions to generate this recap…",
"docsTitle": "This recap's documents",
"docsHint": "Sources used only for this recap.",
"docsUpload": "Add a document",
"docsUploading": "Uploading…",
"docsEmpty": "No document.",
"docsDeleteConfirm": "Delete this document?",
"docsUploaded": "Document added",
"generate": "Generate now",
"generating": "Generating…",
"generated": "Recap generated",
"noCompanion": "Connect a companion to the mission to generate."
```
  The old `missions.recaps.{promptTitle,...,docsUploaded}` keys added earlier today become unused — leave them (harmless) or remove. Keep `missions.recaps.{generate,generating,empty,period,noData,error,generated,noCompanion}` used by the generated-recaps list in RecapsTab.

- [ ] **Step 4:** From `frontend/`: `npm run lint` (no new errors) and `npm run build` (succeeds); confirm both JSON files parse. Commit `feat(missions): per-recap prompt, documents and generate in each schedule card`.

---

## Definition of Done
- Each scheduled recap card shows: timing + its own prompt + its own documents + "Générer maintenant".
- No mission-level recap prompt / recap docs / global generate button remain in the UI.
- Generating (manual or scheduled) a recap uses THAT recap's prompt and only THAT recap's documents; mission events are shared.
- Deleting a recap deletes its documents (cascade). Recap docs never appear in the mission Documents tab.
- Backend suite green in CI; frontend builds; `ruff format --check .` passes (run `python -m ruff format backend/` before committing backend changes).

## Self-review
- Spec coverage: model+migration (T1), schedule prompt CRUD (T2), per-recap docs + threading + remove mission-level docs endpoints (T3), generation scoping + per-recap generate + remove mission generate (T4), frontend cards + trim RecapsTab + i18n (T5).
- Placeholders: none — endpoints have full code; the RAG change shows exact before/after; T5 describes concrete component edits grounded in the existing `commit()`/DocumentsTab patterns.
- Type consistency: `recap_prompt`, `recap_schedule_id`, `recap_schedule_id` param (replaces `recap_source_only`), `schedule_id` arg — consistent across tasks.
- NOTE for implementers: run `python -m ruff format backend/` before each backend commit (CI enforces `ruff format --check`).
