# Mission Recaps Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use `- [ ]` checkboxes.

**Goal:** Give mission recaps a custom prompt + dedicated source documents (like companion recaps), merge the Récaps and Réglages tabs, and rename Chat → Aide (last tab).

**Architecture:** Add `Mission.recap_prompt` and a `Document.is_mission_recap_source` flag. New recap-document endpoints mirror the mission-document ones. Recap generation passes the mission's prompt as the system prompt override and scopes its RAG to recap-source docs only. Frontend consolidates the recap UI into one tab and relabels/reorders the chat tab.

**Tech Stack:** FastAPI, SQLAlchemy/Postgres, Next.js.

**Key existing code (reuse):**
- Mission document endpoints: `routers/missions.py:539-623` (upload/list/delete).
- Doc processing: `rag_engine.process_document_for_user` (creates Document at rag_engine.py:1103-1116, accepts `mission_id`, `is_company_rag`, `folder_id`).
- Recap generation: `mission_recap.build_mission_recap_prompt` (mission_recap.py:75, hardcoded system prompt at :80-94), `enrich_events_with_docs` (:42, RAG via `search_similar_texts_for_user(..., mission_id=...)`), `process_mission_recap` (:133).
- Companion parity: `weekly_recap.build_recap_prompt(custom_prompt=...)`; `Recap.prompt`; `RecapDocument`.
- Tabs: `frontend/components/automations/missions/MissionDetail.js:12` (`SUB_TABS`), rendering :52-71.

---

## Task 1: Data model + migration

**Files:** `backend/database.py`; Test `backend/tests/test_missions.py`.

- [ ] **Step 1:** Add to the `Mission` model (after `recap_hour`, ~database.py:819):
```python
    recap_prompt = Column(Text, nullable=True)  # custom prompt for this mission's recaps
```

- [ ] **Step 2:** Add to the `Document` model (near the other flags, after `is_company_rag`):
```python
    is_mission_recap_source = Column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )  # document used ONLY as a source for this mission's recaps (not the mission's general docs)
```

- [ ] **Step 3:** Add both to `ensure_columns()` migrations list (database.py, the `migrations = [...]` array):
```python
        ("missions", "recap_prompt", "TEXT"),
        ("documents", "is_mission_recap_source", "BOOLEAN NOT NULL DEFAULT FALSE"),
```

- [ ] **Step 4: Test** (`tests/test_missions.py`, pure):
```python
def test_mission_recap_prompt_and_recap_source_columns_exist():
    from database import Mission, Document

    assert hasattr(Mission, "recap_prompt")
    assert hasattr(Document, "is_mission_recap_source")
```
Run: `cd backend && python -m pytest tests/test_missions.py -k recap_prompt_and_recap_source -q`. Confirm `import database` ok (dummy env).

- [ ] **Step 5: Commit** `feat(missions): recap_prompt + is_mission_recap_source columns`.

---

## Task 2: `recap_prompt` in the mission update + detail

**Files:** `backend/schemas/missions.py`, `backend/routers/missions.py`.

- [ ] **Step 1:** In `schemas/missions.py`, add to `MissionUpdate` (and `MissionCreate` if recaps are configurable at create — optional; at minimum `MissionUpdate`):
```python
    recap_prompt: Optional[str] = Field(None, max_length=10000)
```
(Ensure `Optional` is imported.)

- [ ] **Step 2:** In `routers/missions.py`, the mission UPDATE endpoint: after the other recap fields are applied to the mission, add:
```python
        mission.recap_prompt = payload.recap_prompt
```
(Find the update handler that sets `mission.recap_enabled = payload.recap_enabled` etc. and add the line alongside.)

- [ ] **Step 3:** In the mission DETAIL response builder (the dict returned by the GET mission endpoint), add:
```python
        "recap_prompt": mission.recap_prompt,
```

- [ ] **Step 4:** Run mission tests; commit `feat(missions): persist + expose recap_prompt on mission update/detail`.

---

## Task 3: Recap-document endpoints

**Files:** `backend/routers/missions.py`.

Mirror the mission-document endpoints (`:539-623`) but for recap-source docs. Use the SYNC processing path and set the flag after creation (avoids threading the flag through the async background task).

- [ ] **Step 1:** Add after the existing mission-document endpoints:
```python
@router.post("/api/automations/missions/{mission_id}/recap-documents")
async def upload_mission_recap_document(
    mission_id: int,
    file: UploadFile = File(...),
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Upload a document used ONLY as a source for this mission's recaps."""
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)

    if not any(file.filename.lower().endswith(ext) for ext in ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="Type de fichier non supporté")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux")

    from rag_engine import process_document_for_user

    doc_id = process_document_for_user(
        file.filename, content, user_id, db, agent_id=None, company_id=mission.company_id, mission_id=mission.id
    )
    db.query(Document).filter(Document.id == doc_id).update({Document.is_mission_recap_source: True})
    db.commit()
    return {"filename": file.filename, "document_id": doc_id, "status": "uploaded"}


@router.get("/api/automations/missions/{mission_id}/recap-documents")
async def list_mission_recap_documents(
    mission_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    docs = (
        db.query(Document)
        .filter(Document.mission_id == mission.id, Document.is_mission_recap_source.is_(True))
        .order_by(Document.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in docs
        ]
    }


@router.delete("/api/automations/missions/{mission_id}/recap-documents/{document_id}")
async def delete_mission_recap_document(
    mission_id: int, document_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.mission_id == mission.id,
            Document.is_mission_recap_source.is_(True),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(doc)
    db.commit()
    return {"success": True}
```
(Note: `process_document_for_user`'s positional signature is `(filename, content, user_id, db, agent_id=None, company_id=None, mission_id=None, ...)` — verify the call matches; it mirrors the existing mission upload at :591-593.)

- [ ] **Step 2:** Exclude recap-source docs from the EXISTING mission documents list (`list_mission_documents`, :602):
```python
    docs = (
        db.query(Document)
        .filter(Document.mission_id == mission.id, Document.is_mission_recap_source.is_(False))
        .order_by(Document.created_at.desc())
        .all()
    )
```

- [ ] **Step 3:** Tests (PG-backed) in `tests/test_missions.py`: upload a recap doc → it appears in recap-documents list and NOT in the mission documents list; delete works. Run + commit `feat(missions): recap-document upload/list/delete endpoints`.

---

## Task 4: Recap generation uses the prompt + recap-source docs

**Files:** `backend/mission_recap.py`, `backend/rag_engine.py`.

- [ ] **Step 1: Scope RAG to recap-source docs.** In `rag_engine.search_similar_texts_for_user`, add a param `recap_source_only: bool = False`; where it already filters by `mission_id` (the mission-scope clause, see rag_engine.py around the `Document.mission_id`/mission scope filters), add, guarded by the flag:
```python
        if recap_source_only:
            query = query.filter(Document.is_mission_recap_source.is_(True))
```
(Locate the query that joins/filters Document for the mission path and append this filter. If the search builds chunk filters without joining Document, add a join on `DocumentChunk.document_id == Document.id` for this branch.)

- [ ] **Step 2:** In `mission_recap.enrich_events_with_docs` (:59), pass `recap_source_only=True` to `search_similar_texts_for_user(...)` so recap RAG only pulls recap-source docs.

- [ ] **Step 3: Custom prompt.** Change `build_mission_recap_prompt` signature to accept `custom_prompt: str | None = None`; when provided, use it as the system prompt instead of the hardcoded one:
```python
def build_mission_recap_prompt(mission, agent, recall_events: list, enriched_upcoming: list, custom_prompt: str | None = None) -> list:
    ...
    if custom_prompt and custom_prompt.strip():
        system_prompt = custom_prompt.strip()
    else:
        system_prompt = f"""Tu es {agent_name}, ...particular default..."""  # keep the existing default
```
(Keep the existing default block verbatim in the `else`.)

- [ ] **Step 4:** In `process_mission_recap`, pass the mission prompt:
```python
    messages = build_mission_recap_prompt(mission, agent, recall_events, enriched, custom_prompt=getattr(mission, "recap_prompt", None))
```
(Find the existing `build_mission_recap_prompt(...)` call and add the `custom_prompt=` arg.)

- [ ] **Step 5:** Tests: `build_mission_recap_prompt(..., custom_prompt="XYZ")` → messages[0]["content"] == "XYZ"; without → contains the default. Run + commit `feat(missions): recap uses custom prompt + recap-source docs only`.

---

## Task 5: Frontend — tabs restructure

**Files:** `frontend/components/automations/missions/MissionDetail.js`, `frontend/public/locales/{fr,en}/automations.json`.

- [ ] **Step 1:** Change `SUB_TABS` (MissionDetail.js:12) to:
```js
const SUB_TABS = ['planning', 'documents', 'recaps', 'aide'];
```
- [ ] **Step 2:** In the tab→component mapping (:67-71), render `ChatTab` for `aide` and the merged tab for `recaps`; remove the `settings`/`chat` cases:
```jsx
{active === 'planning' && <PlanningTab ... />}
{active === 'documents' && <DocumentsTab ... />}
{active === 'recaps' && <RecapsTab ... />}
{active === 'aide' && <ChatTab ... />}
```
(Keep the same props each tab received before; `RecapsTab` now also needs the props `SettingsTab` used — see Task 6.)

- [ ] **Step 3:** i18n: in both `automations.json`, under `missions.detail.tabs`, add `"aide": "Aide"` (fr) / `"aide": "Help"` (en); the `chat`/`settings` keys can be left (unused) or removed.

- [ ] **Step 4:** `npm run lint`; commit `feat(missions): tabs planning/documents/récaps/aide (chat→aide last, settings merged)`.

---

## Task 6: Frontend — merged Récaps tab

**Files:** `frontend/components/automations/missions/RecapsTab.js` (absorbs `SettingsTab.js`), delete `SettingsTab.js`.

- [ ] **Step 1:** Extend `RecapsTab.js` to stack, in order:
  1. **Recap prompt** — a `<textarea>` bound to the mission's `recap_prompt` + a Save button calling the mission update (PUT) with the existing mission fields + `recap_prompt`.
  2. **Recap documents** — upload/list/delete using the new endpoints (`/recap-documents`), mirroring `DocumentsTab.js`'s upload/list/delete logic but against the recap-documents URLs.
  3. **Schedules** — render the existing `<RecapSchedules ... />` (moved from SettingsTab).
  4. **Generated recaps** — the existing list + "Générer maintenant" button (already in RecapsTab).
  5. **Lifecycle** — companion dropdown + Archive + Delete (moved from SettingsTab).
  Reuse the data-loading/handlers from `SettingsTab.js` verbatim where possible; pass through the same props (mission, companions list, onChange/refresh, etc.) that `MissionDetail` passed to both tabs.

- [ ] **Step 2:** Delete `SettingsTab.js` and remove its import from `MissionDetail.js`.

- [ ] **Step 3:** `npm run lint` + `npm run build` (or rely on CI build); commit `feat(missions): merge Réglages into the Récaps tab (prompt + recap docs + schedules + recaps + lifecycle)`.

---

## Definition of Done
- Mission detail shows 4 tabs: Planning, Documents, Récaps, Aide (last). Aide = the old chat.
- The Récaps tab holds: recap prompt, recap documents, schedules, generated recaps, companion + archive/delete.
- A recap-source doc is separate from mission documents (not shown in Documents tab) and is the ONLY doc source used when generating a recap; the recap uses the mission's `recap_prompt` as its system prompt.
- Full suite green in CI; frontend builds.

## Self-review
- Spec coverage: model+migration (T1), recap_prompt update/detail (T2), recap-doc endpoints + exclude from mission docs (T3), generation prompt+source scoping (T4), tabs (T5), merged tab (T6). All spec sections mapped.
- Placeholders: T4 step 1 and T2/T6 say "find the existing call/handler and add X" — these adapt to existing code shape; the exact line to change is identified (the mission-scope RAG filter; the `build_mission_recap_prompt(...)` call; the mission update handler). New endpoints (T3) have complete code.
- Type consistency: `recap_prompt`, `is_mission_recap_source`, `recap_source_only`, `custom_prompt` used consistently.
