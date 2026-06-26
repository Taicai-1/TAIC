# Dossiers dans le RAG des companions — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre aux companions (agents) d'organiser leurs documents RAG en dossiers, avec un interrupteur actif/inactif par dossier qui contrôle si le dossier est utilisé pour répondre.

**Architecture:** On transpose le pattern existant du RAG entreprise (`CompanyFolder` + `routers/company_rag.py`) au scope par agent : nouvelle table `AgentFolder`, nouvelle colonne `documents.agent_folder_id`, nouveau routeur `routers/agent_folders.py`, propagation d'un `agent_folder_id` dans le pipeline d'upload, filtrage des dossiers inactifs dans la récupération RAG, et UI de dossiers dans la page sources du companion.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL (pgvector), Next.js (Pages Router), React, Tailwind. Tests : pytest + httpx (DB-backed tests skippés en local, exécutés en CI).

---

## Notes transverses (à lire avant de commencer)

- **Migrations** : les nouvelles **tables** sont créées par `Base.metadata.create_all` au démarrage (`backend/main.py:427`). Les nouvelles **colonnes** sur tables existantes doivent passer par `ensure_columns()` (`backend/database.py:1072`, `ADD COLUMN IF NOT EXISTS`).
- **RLS** : toute table tenant-scoped doit figurer dans `TENANT_TABLES` (`backend/database.py:1271`) et porter une colonne `company_id`.
- **Permissions agent** : `_user_can_edit_agent(user_id, agent_id, db)` (mutations) et `_user_can_access_agent(user_id, agent_id, db)` (lecture) — dans `backend/helpers/agent_helpers.py`. Les deux renvoient 404 si l'agent n'existe pas, 403 si pas le droit.
- **Tests DB** : ils skippent automatiquement en local (pas de Postgres) via la fixture `db_session` et tournent en CI. Fixtures disponibles : `client`, `db_session`, `test_user`, `auth_cookies`, `test_agent` (agent possédé par `test_user`), `mock_redis_none`, `mock_event_tracker`, factories dans `backend/tests/factories.py`.
- **Lint backend** : `ruff` (config `backend/pyproject.toml`). Lancer `ruff check backend/` avant chaque commit backend.

## Structure des fichiers

| Fichier | Responsabilité | Création/Modif |
|---------|----------------|----------------|
| `backend/database.py` | Modèle `AgentFolder`, colonne `Document.agent_folder_id`, `ensure_columns`, `TENANT_TABLES` | Modif |
| `backend/routers/agent_folders.py` | Endpoints CRUD dossiers d'agent + déplacement de document | Création |
| `backend/main.py` | Enregistrement du routeur | Modif |
| `backend/routers/documents.py` | `/upload-agent` accepte `folder_id` ; propagation au background worker | Modif |
| `backend/rag_engine.py` | Paramètre `agent_folder_id` dans l'ingestion ; helper + filtre dossiers inactifs en récupération | Modif |
| `backend/routers/sources.py` | `folders` + `agent_folder_id` dans la réponse sources | Modif |
| `backend/tests/factories.py` | `AgentFolderFactory` | Modif |
| `backend/tests/test_agent_folders.py` | Tests CRUD + déplacement + permissions + filtrage récupération | Création |
| `frontend/pages/sources/[agentId].js` | UI dossiers (onglets, CRUD, toggle actif, upload ciblé, déplacement) | Modif |

---

## Task 1 : Modèle de données `AgentFolder` + colonne `documents.agent_folder_id`

**Files:**
- Modify: `backend/database.py` (modèle après `CompanyFolder` ~ligne 584 ; `Document` ~ligne 610 ; `ensure_columns` ~ligne 1074 ; `TENANT_TABLES` ~ligne 1271)

- [ ] **Step 1 : Ajouter le modèle `AgentFolder`**

Dans `backend/database.py`, juste après la classe `CompanyFolder` (après la ligne 584), ajouter :

```python
class AgentFolder(Base):
    __tablename__ = "agent_folders"
    __table_args__ = (UniqueConstraint("agent_id", "name", name="uq_agent_folder_name"),)

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2 : Ajouter la colonne `agent_folder_id` au modèle `Document`**

Dans `backend/database.py`, dans la classe `Document`, juste après la colonne `folder_id` (ligne 610-612), ajouter :

```python
    agent_folder_id = Column(
        Integer, ForeignKey("agent_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )  # Companion RAG folder (set only on agent docs; NULL = "no folder")
```

- [ ] **Step 3 : Enregistrer la colonne dans `ensure_columns()`**

Dans `backend/database.py`, dans la liste `migrations` de `ensure_columns()` (~ligne 1074), à la suite des autres entrées `("documents", ...)`, ajouter :

```python
        ("documents", "agent_folder_id", "INTEGER REFERENCES agent_folders(id) ON DELETE SET NULL"),
```

- [ ] **Step 4 : Ajouter `agent_folders` à `TENANT_TABLES`**

Dans `backend/database.py`, dans la liste `TENANT_TABLES` (~ligne 1271), après `"company_folders",` ajouter :

```python
    "agent_folders",
```

- [ ] **Step 5 : Vérifier l'import (sanity) et le lint**

Run: `cd backend && python -c "from database import AgentFolder, Document; print(AgentFolder.__tablename__, hasattr(Document, 'agent_folder_id'))"`
Expected: `agent_folders True`

Run: `ruff check backend/database.py`
Expected: aucun nouveau warning.

- [ ] **Step 6 : Commit**

```bash
git add backend/database.py
git commit -m "feat(rag): AgentFolder model + documents.agent_folder_id column"
```

---

## Task 2 : Factory de test `AgentFolderFactory`

**Files:**
- Modify: `backend/tests/factories.py`

- [ ] **Step 1 : Importer le modèle**

Dans `backend/tests/factories.py`, ajouter `AgentFolder` à l'import depuis `database` (bloc lignes 4-27) :

```python
    AgentFolder,
```

- [ ] **Step 2 : Ajouter la factory**

Dans `backend/tests/factories.py`, après `AgentFactory` (après la ligne 60), ajouter :

```python
class AgentFolderFactory(factory.Factory):
    class Meta:
        model = AgentFolder

    name = factory.Sequence(lambda n: f"folder-{n}")
    is_active = True
```

- [ ] **Step 3 : Commit**

```bash
git add backend/tests/factories.py
git commit -m "test(rag): AgentFolderFactory"
```

---

## Task 3 : Routeur `agent_folders` — CRUD dossiers + déplacement de document

Endpoints (tous scoping par `agent_id`) :
- `GET /api/agents/{agent_id}/folders`
- `POST /api/agents/{agent_id}/folders`
- `PUT /api/agents/{agent_id}/folders/{folder_id}` (rename et/ou is_active)
- `DELETE /api/agents/{agent_id}/folders/{folder_id}` (si vide)
- `PUT /api/agents/{agent_id}/documents/{document_id}/folder` (déplacer, `folder_id` null autorisé)

**Files:**
- Create: `backend/routers/agent_folders.py`
- Modify: `backend/main.py` (~lignes 615 et 644)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire les tests CRUD + déplacement (qui échouent)**

Créer `backend/tests/test_agent_folders.py` :

```python
"""DB-backed tests for the companion-RAG folder feature (skipped locally, run in CI)."""

import pytest


def _make_folder(db_session, agent, name, is_active=True):
    from tests.factories import AgentFolderFactory

    folder = AgentFolderFactory.build(agent_id=agent.id, company_id=agent.company_id, name=name, is_active=is_active)
    db_session.add(folder)
    db_session.flush()
    return folder


def _make_agent_doc(db_session, user_id, agent, agent_folder_id=None):
    from tests.factories import DocumentFactory

    doc = DocumentFactory.build(
        user_id=user_id, agent_id=agent.id, company_id=agent.company_id, agent_folder_id=agent_folder_id
    )
    db_session.add(doc)
    db_session.flush()
    return doc


# -- create + list -----------------------------------------------------------


@pytest.mark.asyncio
async def test_create_folder_happy_path(client, auth_cookies, test_agent):
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Contrats"}, cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Contrats"
    assert body["is_active"] is True
    assert body["document_count"] == 0
    assert isinstance(body["id"], int)


@pytest.mark.asyncio
async def test_list_folders_with_counts(client, auth_cookies, db_session, test_user, test_agent):
    folder = _make_folder(db_session, test_agent, "RH")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=None)  # sans dossier

    resp = await client.get(f"/api/agents/{test_agent.id}/folders", cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    match = next((f for f in body["folders"] if f["id"] == folder.id), None)
    assert match is not None
    assert match["name"] == "RH"
    assert match["document_count"] == 1
    assert body["uncategorized_count"] == 1


@pytest.mark.asyncio
async def test_create_folder_duplicate_409(client, auth_cookies, db_session, test_agent):
    _make_folder(db_session, test_agent, "Finance")
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Finance"}, cookies=auth_cookies)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_folder_empty_name_400(client, auth_cookies, test_agent):
    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "   "}, cookies=auth_cookies)
    assert resp.status_code == 400


# -- rename + toggle ---------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_folder(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Old")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{folder.id}", json={"name": "New"}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New"


@pytest.mark.asyncio
async def test_toggle_folder_active(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Archive", is_active=True)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{folder.id}", json={"is_active": False}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_rename_collision_409(client, auth_cookies, db_session, test_agent):
    _make_folder(db_session, test_agent, "Existing")
    target = _make_folder(db_session, test_agent, "ToRename")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/folders/{target.id}", json={"name": "Existing"}, cookies=auth_cookies
    )
    assert resp.status_code == 409


# -- delete ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_empty_folder(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "Empty")
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder.id}", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_delete_non_empty_folder_409(client, auth_cookies, db_session, test_user, test_agent):
    folder = _make_folder(db_session, test_agent, "Full")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{folder.id}", cookies=auth_cookies)
    assert resp.status_code == 409


# -- move document -----------------------------------------------------------


@pytest.mark.asyncio
async def test_move_document_to_folder(client, auth_cookies, db_session, test_user, test_agent):
    src = _make_folder(db_session, test_agent, "Src")
    dst = _make_folder(db_session, test_agent, "Dst")
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=src.id)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/{doc.id}/folder", json={"folder_id": dst.id}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["folder_id"] == dst.id


@pytest.mark.asyncio
async def test_move_document_to_uncategorized(client, auth_cookies, db_session, test_user, test_agent):
    src = _make_folder(db_session, test_agent, "Src2")
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=src.id)
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/{doc.id}/folder", json={"folder_id": None}, cookies=auth_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["folder_id"] is None


@pytest.mark.asyncio
async def test_move_document_wrong_doc_404(client, auth_cookies, db_session, test_agent):
    folder = _make_folder(db_session, test_agent, "F")
    resp = await client.put(
        f"/api/agents/{test_agent.id}/documents/999999/folder", json={"folder_id": folder.id}, cookies=auth_cookies
    )
    assert resp.status_code == 404


# -- permissions -------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_cannot_create_folder(client, db_session, test_agent):
    """A different user with no share on the agent gets 403."""
    from tests.factories import UserFactory
    from auth import create_access_token

    other = UserFactory.build()
    db_session.add(other)
    db_session.flush()
    other_cookies = {"token": create_access_token(data={"sub": str(other.id)})}

    resp = await client.post(f"/api/agents/{test_agent.id}/folders", json={"name": "Nope"}, cookies=other_cookies)
    assert resp.status_code == 403
```

- [ ] **Step 2 : Lancer les tests pour vérifier l'échec**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected: en CI, FAIL/erreur 404 (routes inexistantes). En local : `SKIPPED (PostgreSQL not available)` — c'est normal, passer à l'implémentation.

- [ ] **Step 3 : Créer le routeur**

Créer `backend/routers/agent_folders.py` :

```python
"""Companion RAG folders: per-agent document folders with an active/inactive switch.

Agent documents are normal Document rows with agent_id set and agent_folder_id
pointing to an AgentFolder (NULL = "no folder"). An inactive folder's documents
are excluded from the agent's RAG retrieval (see rag_engine.search_similar_texts_for_user).
Edit permission on the agent is required for every mutation.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, AgentFolder, Document
from helpers.agent_helpers import _user_can_access_agent, _user_can_edit_agent

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FOLDER_NAME_LENGTH = 100


def _folder_or_404(folder_id: int, agent_id: int, db: Session) -> AgentFolder:
    folder = (
        db.query(AgentFolder).filter(AgentFolder.id == folder_id, AgentFolder.agent_id == agent_id).first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.get("/api/agents/{agent_id}/folders")
async def list_agent_folders(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List a companion's folders with document counts (read access required)."""
    _user_can_access_agent(int(user_id), agent_id, db)
    counts = dict(
        db.query(Document.agent_folder_id, func.count(Document.id))
        .filter(Document.agent_id == agent_id, Document.document_type == "rag", Document.mission_id.is_(None))
        .group_by(Document.agent_folder_id)
        .all()
    )
    folders = (
        db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id).order_by(AgentFolder.name.asc()).all()
    )
    return {
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "is_active": f.is_active,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "document_count": int(counts.get(f.id, 0)),
            }
            for f in folders
        ],
        "uncategorized_count": int(counts.get(None, 0)),
    }


@router.post("/api/agents/{agent_id}/folders")
async def create_agent_folder(
    agent_id: int, payload: dict = Body(...), user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Create a folder for a companion (edit permission required)."""
    agent = _user_can_edit_agent(int(user_id), agent_id, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if len(name) > MAX_FOLDER_NAME_LENGTH:
        raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
    # Pre-check for a friendlier 409; the DB UniqueConstraint is the real guard against races.
    exists = (
        db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name).first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="A folder with this name already exists")
    folder = AgentFolder(agent_id=agent_id, company_id=agent.company_id, name=name, is_active=True)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active, "document_count": 0}


@router.put("/api/agents/{agent_id}/folders/{folder_id}")
async def update_agent_folder(
    agent_id: int,
    folder_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Rename and/or toggle the active state of a folder (edit permission required)."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    folder = _folder_or_404(folder_id, agent_id, db)

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
        collision = (
            db.query(AgentFolder)
            .filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name, AgentFolder.id != folder_id)
            .first()
        )
        if collision:
            raise HTTPException(status_code=409, detail="A folder with this name already exists")
        folder.name = name

    if "is_active" in payload:
        folder.is_active = bool(payload.get("is_active"))

    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active}


@router.delete("/api/agents/{agent_id}/folders/{folder_id}")
async def delete_agent_folder(
    agent_id: int, folder_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Delete a folder (edit permission required). Blocked if the folder is not empty."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    folder = _folder_or_404(folder_id, agent_id, db)
    doc_count = (
        db.query(func.count(Document.id))
        .filter(Document.agent_folder_id == folder_id, Document.agent_id == agent_id)
        .scalar()
    )
    if doc_count:
        raise HTTPException(status_code=409, detail="Folder is not empty")
    db.delete(folder)
    db.commit()
    return {"status": "deleted", "id": folder_id}


@router.put("/api/agents/{agent_id}/documents/{document_id}/folder")
async def move_agent_document(
    agent_id: int,
    document_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Move a companion document to another folder, or to "no folder" (folder_id=None)."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    if "folder_id" not in payload:
        raise HTTPException(status_code=400, detail="folder_id is required (use null for no folder)")
    target_folder_id = payload.get("folder_id")
    if target_folder_id is not None:
        try:
            target_folder_id = int(target_folder_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="folder_id must be an integer or null")
        _folder_or_404(target_folder_id, agent_id, db)
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.agent_id == agent_id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.agent_folder_id = target_folder_id
    db.commit()
    return {"status": "moved", "id": document_id, "folder_id": doc.agent_folder_id}
```

- [ ] **Step 4 : Enregistrer le routeur dans `main.py`**

Dans `backend/main.py`, après la ligne 615 (`from routers.company_rag import router as company_rag_router  # noqa: E402`), ajouter :

```python
from routers.agent_folders import router as agent_folders_router  # noqa: E402
```

Puis après la ligne 644 (`app.include_router(company_rag_router)`), ajouter :

```python
app.include_router(agent_folders_router)
```

- [ ] **Step 5 : Lancer les tests pour vérifier le succès**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected (CI) : tous PASS. En local : SKIPPED (pas de Postgres) — acceptable.

Run: `ruff check backend/routers/agent_folders.py backend/main.py`
Expected: aucun warning.

- [ ] **Step 6 : Commit**

```bash
git add backend/routers/agent_folders.py backend/main.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): companion folder CRUD + move endpoints"
```

---

## Task 4 : Upload d'un document directement dans un dossier

On propage un `agent_folder_id` optionnel depuis `/upload-agent` jusqu'à la création de la ligne `Document`.

**Files:**
- Modify: `backend/rag_engine.py` (`ingest_text_content` ~ligne 1072 ; `process_document_for_user` ~ligne 1180)
- Modify: `backend/routers/documents.py` (`_process_document_background` ~ligne 565 ; `/upload-agent` ~ligne 675)

- [ ] **Step 1 : Ajouter `agent_folder_id` à `ingest_text_content`**

Dans `backend/rag_engine.py`, dans la signature de `ingest_text_content` (lignes 1072-1089), ajouter le paramètre après `folder_id: int = None,` :

```python
    agent_folder_id: int = None,
```

Puis dans la construction de l'objet `Document` (lignes 1115-1130), après `folder_id=folder_id,`, ajouter :

```python
            agent_folder_id=agent_folder_id,
```

- [ ] **Step 2 : Ajouter `agent_folder_id` à `process_document_for_user`**

Dans `backend/rag_engine.py`, dans la signature de `process_document_for_user` (lignes 1180-1192), ajouter après `folder_id: int = None,` :

```python
    agent_folder_id: int = None,
```

Puis dans l'appel à `ingest_text_content` (lignes 1246-1260), après `folder_id=folder_id,`, ajouter :

```python
            agent_folder_id=agent_folder_id,
```

- [ ] **Step 3 : Propager dans le background worker**

Dans `backend/routers/documents.py`, dans la signature de `_process_document_background` (lignes 565-575), ajouter après `folder_id: int = None,` :

```python
    agent_folder_id: int = None,
```

Puis dans l'appel à `process_document_for_user` à l'intérieur (lignes 620-631), après `folder_id=folder_id,`, ajouter :

```python
            agent_folder_id=agent_folder_id,
```

- [ ] **Step 4 : Accepter `folder_id` dans `/upload-agent` et le valider**

Dans `backend/routers/documents.py`, dans `upload_file_for_agent` (~ligne 675), après la résolution et conversion de `agent_id` (après `agent_id = int(agent_id)`, ligne 702) et la vérification des droits (`agent = _user_can_edit_agent(...)`, ligne 714), ajouter l'extraction + validation du dossier :

```python
        # Optional target folder (companion RAG folders). None => "no folder".
        raw_folder_id = form.get("folder_id")
        agent_folder_id = None
        if raw_folder_id not in (None, "", "null"):
            try:
                agent_folder_id = int(raw_folder_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="folder_id must be an integer")
            from database import AgentFolder

            folder = (
                db.query(AgentFolder)
                .filter(AgentFolder.id == agent_folder_id, AgentFolder.agent_id == agent_id)
                .first()
            )
            if not folder:
                raise HTTPException(status_code=404, detail="Folder not found")
```

Note : placer ce bloc **après** `agent = _user_can_edit_agent(int(user_id), agent_id, db)` (ligne 714) et **avant** `content = await file.read()` (ligne 716).

- [ ] **Step 5 : Passer `agent_folder_id` aux deux chemins (async + sync)**

Dans `backend/routers/documents.py`, dans le chemin async (`background_tasks.add_task(...)`, lignes 736-738), ajouter `agent_folder_id` comme dernier argument positionnel. Le worker attend l'ordre `(task_id, filename, content, user_id, agent_id, company_id, mission_id, is_company_rag, folder_id, agent_folder_id)`, donc passer les valeurs intermédiaires explicitement :

```python
            background_tasks.add_task(
                _process_document_background,
                task_id,
                file.filename,
                content,
                int(user_id),
                agent_id,
                caller_cid,
                None,   # mission_id
                False,  # is_company_rag
                None,   # folder_id (company RAG)
                agent_folder_id,
            )
```

Puis dans le chemin synchrone de secours (`process_document_for_user(...)`, lignes 743-745), ajouter le mot-clé :

```python
        doc_id = process_document_for_user(
            file.filename,
            content,
            int(user_id),
            db,
            agent_id,
            company_id=_get_caller_company_id(user_id, db),
            agent_folder_id=agent_folder_id,
        )
```

- [ ] **Step 6 : Écrire le test d'upload ciblé (sync path)**

Dans `backend/tests/test_agent_folders.py`, ajouter à la fin :

```python
# -- upload into a folder ----------------------------------------------------


@pytest.mark.asyncio
async def test_upload_into_folder_sync(
    client, auth_cookies, db_session, test_agent, mock_redis_none, mock_gcs, mock_event_tracker, monkeypatch
):
    """With Redis off, /upload-agent stores the doc in the given folder (sync path)."""
    folder = _make_folder(db_session, test_agent, "Cible")

    # Avoid real embeddings: stub ingest to create a Document directly.
    import rag_engine
    from database import Document

    def _fake_ingest(text_content, filename, user_id, agent_id, db, **kwargs):
        doc = Document(
            filename=filename,
            content=text_content,
            user_id=user_id,
            agent_id=agent_id,
            company_id=kwargs.get("company_id"),
            agent_folder_id=kwargs.get("agent_folder_id"),
            document_type="rag",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc.id

    monkeypatch.setattr(rag_engine, "ingest_text_content", _fake_ingest)

    files = {"file": ("note.txt", b"contenu de test", "text/plain")}
    data = {"agent_id": str(test_agent.id), "folder_id": str(folder.id)}
    resp = await client.post("/upload-agent", files=files, data=data, cookies=auth_cookies)
    assert resp.status_code == 200

    doc = db_session.query(Document).filter(Document.agent_id == test_agent.id).order_by(Document.id.desc()).first()
    assert doc is not None
    assert doc.agent_folder_id == folder.id
```

- [ ] **Step 7 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected (CI) : PASS. Local : SKIPPED.

Run: `ruff check backend/rag_engine.py backend/routers/documents.py`
Expected: aucun warning.

- [ ] **Step 8 : Commit**

```bash
git add backend/rag_engine.py backend/routers/documents.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): upload companion document into a folder"
```

---

## Task 5 : Filtrage des dossiers inactifs dans la récupération RAG

Les documents d'un dossier **inactif** sont exclus ; les documents sans dossier ou dans un dossier actif restent inclus.

**Files:**
- Modify: `backend/rag_engine.py` (helper module-level + branche `elif agent_id:` ~ligne 918)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire le test du helper (qui échoue)**

Dans `backend/tests/test_agent_folders.py`, ajouter :

```python
# -- retrieval filtering -----------------------------------------------------


@pytest.mark.asyncio
async def test_inactive_folder_ids_helper(db_session, test_agent):
    """The helper returns only the agent's inactive folder ids."""
    from rag_engine import _inactive_agent_folder_ids

    active = _make_folder(db_session, test_agent, "Actif", is_active=True)
    inactive = _make_folder(db_session, test_agent, "Inactif", is_active=False)

    ids = _inactive_agent_folder_ids(test_agent.id, db_session)
    assert inactive.id in ids
    assert active.id not in ids
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

Run: `cd backend && python -m pytest tests/test_agent_folders.py::test_inactive_folder_ids_helper -v`
Expected (CI) : FAIL `ImportError: cannot import name '_inactive_agent_folder_ids'`. Local : SKIPPED.

- [ ] **Step 3 : Ajouter le helper module-level**

Dans `backend/rag_engine.py`, juste avant la fonction `search_similar_texts_for_user` (avant la ligne 836), ajouter :

```python
def _inactive_agent_folder_ids(agent_id: int, db: Session) -> list:
    """Return the ids of this agent's folders whose is_active is False.

    Documents in these folders are excluded from RAG retrieval; documents with
    agent_folder_id IS NULL (no folder) are always included.
    """
    from database import AgentFolder

    rows = (
        db.query(AgentFolder.id)
        .filter(AgentFolder.agent_id == agent_id, AgentFolder.is_active.is_(False))
        .all()
    )
    return [r[0] for r in rows]
```

- [ ] **Step 4 : Brancher le filtre dans la récupération**

Dans `backend/rag_engine.py`, dans la branche `elif agent_id:` (lignes 918-927), remplacer la définition de `agent_scope` :

```python
        elif agent_id:
            # Agent-scoped docs; optionally union the company-shared docs
            agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
```

par :

```python
        elif agent_id:
            # Agent-scoped docs; exclude docs sitting in an inactive folder.
            inactive_folder_ids = _inactive_agent_folder_ids(agent_id, db)
            agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
            if inactive_folder_ids:
                agent_scope = and_(
                    agent_scope,
                    or_(
                        Document.agent_folder_id.is_(None),
                        Document.agent_folder_id.notin_(inactive_folder_ids),
                    ),
                )
```

(Le reste de la branche — `if include_company_rag:` etc. — reste inchangé. `and_` et `or_` sont déjà importés dans ce fichier puisqu'ils sont utilisés juste en dessous.)

- [ ] **Step 5 : Écrire le test d'intégration de récupération**

Dans `backend/tests/test_agent_folders.py`, ajouter :

```python
@pytest.mark.asyncio
async def test_retrieval_excludes_inactive_folder(db_session, test_user, test_agent):
    """search_similar_texts_for_user returns docs from active/no folder, not inactive."""
    from rag_engine import search_similar_texts_for_user
    from database import DocumentChunk

    active = _make_folder(db_session, test_agent, "RetrActive", is_active=True)
    inactive = _make_folder(db_session, test_agent, "RetrInactive", is_active=False)

    # One non-zero unit vector so cosine_distance is well-defined (dim 1024).
    vec = [1.0] + [0.0] * 1023

    def _doc_with_chunk(folder_id, fname):
        doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder_id)
        doc.filename = fname
        chunk = DocumentChunk(
            document_id=doc.id,
            company_id=test_agent.company_id,
            chunk_text=f"chunk {fname}",
            embedding_vec=vec,
            chunk_index=0,
        )
        db_session.add(chunk)
        db_session.flush()
        return doc

    _doc_with_chunk(None, "no_folder.txt")
    _doc_with_chunk(active.id, "active.txt")
    _doc_with_chunk(inactive.id, "inactive.txt")

    results = search_similar_texts_for_user(
        vec, test_user.id, db_session, top_k=10, agent_id=test_agent.id, company_id=test_agent.company_id
    )
    filenames = {r["filename"] for r in results}
    assert "no_folder.txt" in filenames
    assert "active.txt" in filenames
    assert "inactive.txt" not in filenames
```

- [ ] **Step 6 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected (CI) : PASS. Local : SKIPPED.

Run: `ruff check backend/rag_engine.py`
Expected: aucun warning.

- [ ] **Step 7 : Commit**

```bash
git add backend/rag_engine.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): exclude inactive companion folders from retrieval"
```

---

## Task 6 : Exposer les dossiers dans l'endpoint sources

**Files:**
- Modify: `backend/routers/sources.py` (`get_agent_sources` ~ligne 302)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire le test (qui échoue)**

Dans `backend/tests/test_agent_folders.py`, ajouter :

```python
# -- sources endpoint --------------------------------------------------------


@pytest.mark.asyncio
async def test_sources_includes_folders_and_doc_folder_id(
    client, auth_cookies, db_session, test_user, test_agent
):
    folder = _make_folder(db_session, test_agent, "SourcesFolder")
    _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=folder.id)

    resp = await client.get(f"/api/agents/{test_agent.id}/sources", cookies=auth_cookies)
    assert resp.status_code == 200
    body = resp.json()
    assert any(f["id"] == folder.id and f["is_active"] is True for f in body["folders"])
    assert all("agent_folder_id" in d for d in body["documents"])
    assert any(d["agent_folder_id"] == folder.id for d in body["documents"])
```

- [ ] **Step 2 : Lancer le test pour vérifier l'échec**

Run: `cd backend && python -m pytest tests/test_agent_folders.py::test_sources_includes_folders_and_doc_folder_id -v`
Expected (CI) : FAIL `KeyError: 'folders'`. Local : SKIPPED.

- [ ] **Step 3 : Importer le modèle dans sources.py**

Dans `backend/routers/sources.py`, ajouter `AgentFolder` à l'import depuis `database` (ligne 14) :

```python
from database import get_db, Agent, AgentShare, AgentFolder, Document, DocumentChunk, NotionLink, DriveLink
```

- [ ] **Step 4 : Charger les dossiers et les inclure dans la réponse**

Dans `backend/routers/sources.py`, dans `get_agent_sources` (~ligne 302), après la requête `drive_links` (ligne 337) et avant le `return`, ajouter :

```python
    # Companion RAG folders + per-folder document counts
    folders = (
        db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id).order_by(AgentFolder.name.asc()).all()
    )
    folder_counts = {}
    for d in docs:
        if d.agent_folder_id is not None:
            folder_counts[d.agent_folder_id] = folder_counts.get(d.agent_folder_id, 0) + 1
```

Puis, dans le `dict` retourné (lignes 339-374), ajouter `agent_folder_id` à chaque document et un nouveau tableau `folders`. Remplacer la clé `"documents": [...]` par :

```python
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "has_file": bool(d.gcs_url),
                "notion_link_id": d.notion_link_id,
                "drive_link_id": getattr(d, "drive_link_id", None),
                "source_url": _clean_source_url(getattr(d, "source_url", None)),
                "agent_folder_id": d.agent_folder_id,
            }
            for d in docs
        ],
```

Et juste après la clé `"can_edit": can_edit,` (dernière clé), ajouter :

```python
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "is_active": f.is_active,
                "document_count": folder_counts.get(f.id, 0),
            }
            for f in folders
        ],
```

- [ ] **Step 5 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected (CI) : PASS. Local : SKIPPED.

Run: `ruff check backend/routers/sources.py`
Expected: aucun warning.

- [ ] **Step 6 : Commit**

```bash
git add backend/routers/sources.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): expose companion folders in the sources endpoint"
```

---

## Task 7 : UI des dossiers dans la page sources du companion

On ajoute à `frontend/pages/sources/[agentId].js` : une barre de dossiers (incluant « Sans dossier »), la création/renommage/suppression, le toggle actif/inactif, la sélection du dossier à l'upload, et le déplacement d'un document. Modèle de référence : `frontend/pages/organization.js` (lignes 175-298 pour les handlers, 799-845 pour le rendu).

**Files:**
- Modify: `frontend/pages/sources/[agentId].js`
- Reference: `frontend/pages/organization.js`, `frontend/lib/api.js` (instance `api`)

- [ ] **Step 1 : Lire la page existante et le modèle**

Lire `frontend/pages/sources/[agentId].js` en entier pour repérer : l'état des documents (`useState`), `loadSources()`, le handler d'upload existant, et la liste des documents rendue. Lire `frontend/pages/organization.js` lignes 175-298 et 799-845 comme modèle de handlers/JSX. Confirmer que `api` est importé depuis `lib/api`.

- [ ] **Step 2 : Ajouter l'état des dossiers**

Dans le composant de `frontend/pages/sources/[agentId].js`, à côté des `useState` existants, ajouter :

```javascript
  const [folders, setFolders] = useState([]);
  const [selectedFolderId, setSelectedFolderId] = useState(null); // null = "Sans dossier" / tous
  const [newFolderName, setNewFolderName] = useState('');
  const [uploadFolderId, setUploadFolderId] = useState(null);     // dossier cible à l'upload
```

- [ ] **Step 3 : Récupérer les dossiers depuis la réponse sources**

Dans `loadSources()`, après avoir stocké les documents depuis la réponse de `GET /api/agents/{agentId}/sources`, stocker aussi les dossiers :

```javascript
      setFolders(res.data.folders || []);
```

(Les documents portent désormais `agent_folder_id` ; aucun autre appel n'est nécessaire — l'endpoint sources renvoie tout.)

- [ ] **Step 4 : Ajouter les handlers CRUD + toggle + move**

Dans le composant, ajouter (en s'inspirant de `organization.js`) :

```javascript
  const reloadFolders = async () => {
    const res = await api.get(`/api/agents/${agentId}/folders`);
    setFolders(res.data.folders || []);
  };

  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      await api.post(`/api/agents/${agentId}/folders`, { name });
      setNewFolderName('');
      await reloadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Erreur lors de la création du dossier');
    }
  };

  const handleRenameFolder = async (folder) => {
    const name = prompt('Nouveau nom du dossier', folder.name);
    if (!name || !name.trim()) return;
    try {
      await api.put(`/api/agents/${agentId}/folders/${folder.id}`, { name: name.trim() });
      await reloadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Erreur lors du renommage');
    }
  };

  const handleToggleFolder = async (folder) => {
    try {
      await api.put(`/api/agents/${agentId}/folders/${folder.id}`, { is_active: !folder.is_active });
      await reloadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Erreur lors du changement d\'état');
    }
  };

  const handleDeleteFolder = async (folder) => {
    if (!confirm(`Supprimer le dossier "${folder.name}" ?`)) return;
    try {
      await api.delete(`/api/agents/${agentId}/folders/${folder.id}`);
      if (selectedFolderId === folder.id) setSelectedFolderId(null);
      await reloadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Le dossier doit être vide pour être supprimé');
    }
  };

  const handleMoveDoc = async (docId, folderId) => {
    try {
      await api.put(`/api/agents/${agentId}/documents/${docId}/folder`, {
        folder_id: folderId === '' ? null : Number(folderId),
      });
      await loadSources();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Erreur lors du déplacement');
    }
  };
```

- [ ] **Step 5 : Passer le dossier cible à l'upload existant**

Localiser le handler d'upload existant (celui qui POST vers `/upload-agent` avec un `FormData`). Avant l'envoi, si `uploadFolderId` est défini, l'ajouter au FormData :

```javascript
      if (uploadFolderId) {
        formData.append('folder_id', String(uploadFolderId));
      }
```

Et ajouter, près du bouton d'upload, un sélecteur de dossier cible :

```jsx
            <select
              value={uploadFolderId ?? ''}
              onChange={(e) => setUploadFolderId(e.target.value === '' ? null : Number(e.target.value))}
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">Sans dossier</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
```

- [ ] **Step 6 : Ajouter la barre de dossiers + le filtre d'affichage**

Au-dessus de la liste des documents, ajouter la barre de dossiers (création + onglets avec compteur, toggle, renommer, supprimer) :

```jsx
        <div className="mb-4">
          <div className="flex gap-2 mb-3">
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="Nouveau dossier"
              className="border rounded px-2 py-1 text-sm"
            />
            <button onClick={handleCreateFolder} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
              + Dossier
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setSelectedFolderId(null)}
              className={`px-3 py-1 rounded text-sm ${selectedFolderId === null ? 'bg-blue-600 text-white' : 'bg-gray-100'}`}
            >
              Sans dossier
            </button>
            {folders.map((f) => (
              <div
                key={f.id}
                className={`flex items-center gap-1 px-2 py-1 rounded text-sm ${selectedFolderId === f.id ? 'bg-blue-600 text-white' : 'bg-gray-100'} ${!f.is_active ? 'opacity-50' : ''}`}
              >
                <button onClick={() => setSelectedFolderId(f.id)}>
                  {f.name} ({f.document_count}){!f.is_active ? ' — inactif' : ''}
                </button>
                <button title="Actif/inactif" onClick={() => handleToggleFolder(f)}>{f.is_active ? '🟢' : '⚪'}</button>
                <button title="Renommer" onClick={() => handleRenameFolder(f)}>✏️</button>
                <button title="Supprimer" onClick={() => handleDeleteFolder(f)}>🗑️</button>
              </div>
            ))}
          </div>
        </div>
```

Puis filtrer la liste rendue des documents selon `selectedFolderId` : quand `selectedFolderId === null` montrer les documents avec `agent_folder_id == null` ; sinon ceux du dossier sélectionné. Remplacer la source de la liste (`documents.map(...)`) par une variable filtrée :

```javascript
  const visibleDocuments = documents.filter((d) =>
    selectedFolderId === null ? !d.agent_folder_id : d.agent_folder_id === selectedFolderId
  );
```

et utiliser `visibleDocuments.map(...)` dans le JSX de la liste.

- [ ] **Step 7 : Ajouter le menu « déplacer vers… » sur chaque document**

Dans le rendu de chaque document, ajouter un sélecteur de déplacement :

```jsx
                <select
                  value={doc.agent_folder_id ?? ''}
                  onChange={(e) => handleMoveDoc(doc.id, e.target.value)}
                  className="border rounded px-1 py-0.5 text-xs"
                >
                  <option value="">Sans dossier</option>
                  {folders.map((f) => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
```

- [ ] **Step 8 : Vérifier le lint et le build frontend**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur ESLint.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 9 : Commit**

```bash
git add frontend/pages/sources/[agentId].js
git commit -m "feat(rag): companion folders UI on the sources page"
```

---

## Task 8 : Vérification manuelle de bout en bout

**Files:** aucun (validation)

- [ ] **Step 1 : Lancer la stack**

Run: `docker-compose up --build` (ou backend + frontend séparément). Vérifier qu'aucune erreur de démarrage n'apparaît (notamment `ensure_columns done` et `create_all done` dans les logs).

- [ ] **Step 2 : Parcours utilisateur**

Dans l'UI, ouvrir un companion → page Sources :
1. Créer deux dossiers (« A », « B »).
2. Uploader un document dans « A », un autre sans dossier.
3. Déplacer le document de « A » vers « B », puis vers « Sans dossier ».
4. Renommer « B ».
5. Rendre « A » inactif, poser au companion une question dont la réponse ne se trouve QUE dans un document de « A » → vérifier que le companion ne l'utilise pas. Réactiver « A », reposer la question → il l'utilise.
6. Tenter de supprimer un dossier non vide → message d'erreur ; vider puis supprimer → succès.

- [ ] **Step 3 : Mettre à jour la mémoire projet**

Ajouter une entrée dans `MEMORY.md` (mémoire auto) pointant vers une note décrivant la feature « dossiers RAG companions » (table `AgentFolder`, colonne `documents.agent_folder_id`, routeur `agent_folders.py`, toggle `is_active` filtrant la récupération). Décision utilisateur requise sur ce point uniquement si le worker n'a pas accès en écriture à la mémoire.

---

## Self-Review (effectué par l'auteur du plan)

**Couverture de la spec :**
- §1 Modèle de données → Task 1 ✓ (table `AgentFolder`, colonne `agent_folder_id`, `ensure_columns`, `TENANT_TABLES`)
- §2 Endpoints (5 routes) → Task 3 ✓
- §3 Upload dans un dossier → Task 4 ✓
- §4 Filtrage récupération inactifs → Task 5 ✓
- §5 Frontend (sources endpoint + UI) → Task 6 (endpoint) + Task 7 (UI) ✓
- §6 Tests → intégrés dans Tasks 3/4/5/6 ✓

**Placeholders :** aucun TODO/TBD ; tout le code est fourni explicitement.

**Cohérence des types/noms :** `agent_folder_id` (colonne + paramètres), `is_active`, `_inactive_agent_folder_ids`, `_folder_or_404` (local à `agent_folders.py`, distinct de celui de `company_rag.py`), réponses `{id, name, is_active, document_count}` cohérentes entre create/list/update et l'endpoint sources. L'ordre des arguments positionnels de `_process_document_background` (Task 4 Step 5) correspond à la signature étendue de Task 4 Step 3.

**Points d'attention pour le worker :**
- Les tests DB skippent en local — c'est attendu ; la validation réelle se fait en CI + Task 8.
- Ne pas confondre `folder_id` (RAG entreprise, FK `company_folders`) et `agent_folder_id` (RAG companion, FK `agent_folders`).
