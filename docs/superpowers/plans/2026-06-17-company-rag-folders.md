# RAG Entreprise — Dossiers + sélection par agent (+ fix UX) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Organiser les documents du RAG Entreprise en dossiers (liste plate), permettre à chaque agent de choisir quels dossiers inclure (tous par défaut, dynamique), et corriger le bug d'affichage post-upload.

**Architecture:** Nouvelle table `CompanyFolder` (scopée `company_id`), colonne `Document.folder_id`, colonne JSON `Agent.company_rag_folder_ids` (vide = tous, dynamique). Endpoints CRUD dossiers + `folder_id` obligatoire à l'upload + déplacement de doc dans `routers/company_rag.py`. Filtrage par dossier ajouté à la récupération RAG, en plus du filtre tenant existant. Fix UX = polling `/upload-status` après upload.

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL (backend), Next.js 14 / React (frontend), pytest + ruff + ESLint.

**Conventions du repo :**
- Migrations de colonnes via la liste `ensure_columns()` dans `backend/database.py` (pas d'Alembic).
- Tables créées par `Base.metadata.create_all` au démarrage (`main.py:354`).
- Tests backend DB-backed dans `backend/tests/test_company_rag.py` : **SKIP en local** (pas de Postgres), **exécutés en CI**. Vérification locale = `ruff check .` + import OK.
- Frontend : vérification = `npm run lint` + `npm run build`.
- Toujours valider tout `folder_id` fourni par le client comme appartenant à `company_id` du caller.

---

## File Structure

**Backend (modifiés) :**
- `backend/database.py` — modèle `CompanyFolder`, `Document.folder_id`, `Agent.company_rag_folder_ids`, entrées `ensure_columns`, fonction `ensure_company_rag_default_folders()`.
- `backend/main.py` — appel de `ensure_company_rag_default_folders()` au démarrage + import.
- `backend/rag_engine.py` — param `folder_id` dans `process_document_for_user`/`ingest_text_content` ; param `company_rag_folder_ids` + filtrage dans `search_similar_texts_for_user`, `get_answer`, `get_answer_stream`.
- `backend/routers/documents.py` — param `folder_id` dans `_process_document_background`.
- `backend/routers/company_rag.py` — endpoints dossiers (GET/POST/PUT/DELETE), `folder_id` à l'upload, `folder_id` dans GET docs + filtre, endpoint déplacement.
- `backend/routers/agents.py` — form param `company_rag_folder_ids` (create + update), sérialisation dans les GET.

**Backend (tests) :**
- `backend/tests/test_company_rag_folders.py` — nouveau fichier de tests DB-backed.

**Frontend (modifiés) :**
- `frontend/pages/organization.js` — état dossiers, CRUD dossiers, sélection dossier, upload dans dossier, déplacement doc, fix polling.
- `frontend/pages/agents.js` — multi-select dossiers à la création d'agent.
- `frontend/pages/index.js` — multi-select dossiers à l'édition d'agent + chargement.
- `frontend/public/locales/fr/organization.json`, `frontend/public/locales/en/organization.json` — clés dossiers.
- `frontend/public/locales/fr/agents.json`, `frontend/public/locales/en/agents.json` — clé sélection dossiers.

---

## Task 1: Modèle de données (table + colonnes + migrations)

**Files:**
- Modify: `backend/database.py` (modèle `Document` ~535-566, modèle `Agent` ~330, liste `migrations` ~1043-1046)

- [ ] **Step 1: Ajouter le modèle `CompanyFolder`**

Dans `backend/database.py`, juste **avant** `class Document(Base):` (ligne ~535), insérer :

```python
class CompanyFolder(Base):
    __tablename__ = "company_folders"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_company_folder_name"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

(`UniqueConstraint`, `Column`, `Integer`, `String`, `DateTime`, `ForeignKey`, `datetime` sont déjà importés en tête de fichier — vérifier la présence de `UniqueConstraint` dans les imports SQLAlchemy ; il est déjà utilisé ligne 212.)

- [ ] **Step 2: Ajouter `folder_id` au modèle `Document`**

Dans `class Document`, juste après la colonne `is_company_rag` (ligne ~558), ajouter :

```python
    folder_id = Column(
        Integer, ForeignKey("company_folders.id"), nullable=True, index=True
    )  # Company RAG folder (set only when is_company_rag=True; required at the app level for those)
```

- [ ] **Step 3: Ajouter `company_rag_folder_ids` au modèle `Agent`**

Dans `class Agent`, juste après la colonne `include_company_rag` (ligne ~330), ajouter :

```python
    company_rag_folder_ids = Column(Text, nullable=True)  # JSON list of CompanyFolder ids; NULL/[] = all folders (dynamic)
```

(`Text` est déjà importé.)

- [ ] **Step 4: Ajouter les entrées `ensure_columns`**

Dans `backend/database.py`, dans la liste `migrations` (~1043-1046), remplacer le bloc `# Company RAG` par :

```python
        # Company RAG
        ("documents", "is_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("agents", "include_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
        # Company RAG folders
        ("documents", "folder_id", "INTEGER REFERENCES company_folders(id)"),
        ("agents", "company_rag_folder_ids", "TEXT"),
```

- [ ] **Step 5: Vérifier que le module s'importe**

Run: `cd backend && python -c "import database; print('CompanyFolder' in dir(database))"`
Expected: `True` (et aucune erreur d'import)

- [ ] **Step 6: Lint**

Run: `cd backend && ruff check database.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add backend/database.py
git commit -m "feat(company-rag): CompanyFolder model + Document.folder_id + Agent.company_rag_folder_ids"
```

---

## Task 2: Migration de démarrage — dossier « Général » pour les docs existants

La table `company_folders` est créée par `Base.metadata.create_all` au démarrage. On ajoute une fonction idempotente qui rattache les docs entreprise orphelins (`folder_id IS NULL`) à un dossier « Général » par organisation.

**Files:**
- Modify: `backend/database.py` (ajouter la fonction, après `ensure_columns()` ~1096)
- Modify: `backend/main.py` (appel au démarrage ~360, import)

- [ ] **Step 1: Écrire `ensure_company_rag_default_folders()`**

Dans `backend/database.py`, après la fonction `ensure_columns()` (avant `ensure_rls_policies`), ajouter :

```python
def ensure_company_rag_default_folders():
    """Idempotent: attach orphan company-RAG docs (folder_id IS NULL) to a per-company
    'Général' folder, creating it if needed. Runs at startup, safe to re-run."""
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(Document.company_id)
                .filter(
                    Document.is_company_rag.is_(True),
                    Document.folder_id.is_(None),
                    Document.company_id.isnot(None),
                )
                .distinct()
                .all()
            )
            company_ids = [r[0] for r in rows]
            for cid in company_ids:
                folder = (
                    db.query(CompanyFolder)
                    .filter(CompanyFolder.company_id == cid, CompanyFolder.name == "Général")
                    .first()
                )
                if folder is None:
                    folder = CompanyFolder(company_id=cid, name="Général")
                    db.add(folder)
                    db.flush()
                db.query(Document).filter(
                    Document.is_company_rag.is_(True),
                    Document.folder_id.is_(None),
                    Document.company_id == cid,
                ).update({Document.folder_id: folder.id}, synchronize_session=False)
            db.commit()
            if company_ids:
                logger.info(
                    f"ensure_company_rag_default_folders: migrated docs for {len(company_ids)} companies"
                )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"ensure_company_rag_default_folders skipped: {e}")
```

(`SessionLocal`, `Document`, `CompanyFolder`, `logger` sont définis dans le module.)

- [ ] **Step 2: Appeler la migration au démarrage**

Dans `backend/main.py`, repérer l'appel `ensure_columns()` (~360). Juste **après**, ajouter :

```python
        from database import ensure_company_rag_default_folders
        ensure_company_rag_default_folders()
        logger.info("ensure_company_rag_default_folders done (%s)", _elapsed())
```

(Suivre le style des lignes voisines ; `_elapsed()` est la closure de timing déjà utilisée à côté de `create_all`/`ensure_columns`.)

- [ ] **Step 3: Vérifier l'import**

Run: `cd backend && python -c "import database; print(callable(database.ensure_company_rag_default_folders))"`
Expected: `True`

- [ ] **Step 4: Lint**

Run: `cd backend && ruff check database.py main.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat(company-rag): startup migration of existing docs into a Général folder"
```

---

## Task 3: Propager `folder_id` dans le pipeline d'ingestion

**Files:**
- Modify: `backend/rag_engine.py` (`process_document_for_user` ~1127, `ingest_text_content` ~1025)
- Modify: `backend/routers/documents.py` (`_process_document_background` ~565)

- [ ] **Step 1: Ajouter `folder_id` à `ingest_text_content`**

Dans `backend/rag_engine.py`, fonction `ingest_text_content` : ajouter le paramètre `folder_id: int = None` à la fin de la signature (après `is_company_rag: bool = False,`), puis dans la construction `document = Document(...)` ajouter la ligne `folder_id=folder_id,` à côté de `is_company_rag=is_company_rag,`.

```python
def ingest_text_content(
    # ... params existants ...
    is_company_rag: bool = False,
    folder_id: int = None,
):
    # ...
        document = Document(
            # ... champs existants ...
            is_company_rag=is_company_rag,
            folder_id=folder_id,
        )
```

- [ ] **Step 2: Ajouter `folder_id` à `process_document_for_user`**

Même fichier, fonction `process_document_for_user` (~1127) : ajouter `folder_id: int = None` à la fin de la signature (après `is_company_rag: bool = False,`), et passer `folder_id=folder_id,` dans l'appel `return ingest_text_content(...)` (~1190).

```python
def process_document_for_user(
    # ... params existants ...
    is_company_rag: bool = False,
    folder_id: int = None,
) -> int:
    # ...
        return ingest_text_content(
            # ... args existants ...
            is_company_rag=is_company_rag,
            folder_id=folder_id,
        )
```

- [ ] **Step 3: Ajouter `folder_id` à `_process_document_background`**

Dans `backend/routers/documents.py`, fonction `_process_document_background` (~565) : ajouter `folder_id: int = None` à la fin de la signature (après `is_company_rag: bool = False,`). Puis, dans le corps, repérer l'appel à `process_document_for_user(...)` et y ajouter `folder_id=folder_id,`.

```python
def _process_document_background(
    task_id: str,
    filename: str,
    content: bytes,
    user_id: int,
    agent_id: int,
    company_id: int = None,
    mission_id: int = None,
    is_company_rag: bool = False,
    folder_id: int = None,
):
    # ... dans le corps, à l'appel process_document_for_user(...):
    #     ..., is_company_rag=is_company_rag, folder_id=folder_id,
```

Vérifier le corps : si l'appel `process_document_for_user` y passe les arguments positionnellement, ajouter `folder_id=folder_id` en mot-clé à la fin. Lire la fonction avant d'éditer pour repérer la forme exacte de l'appel.

- [ ] **Step 4: Lint**

Run: `cd backend && ruff check rag_engine.py routers/documents.py`
Expected: `All checks passed!`

- [ ] **Step 5: Vérifier l'import**

Run: `cd backend && python -c "import rag_engine, inspect; print('folder_id' in inspect.signature(rag_engine.process_document_for_user).parameters)"`
Expected: `True`

- [ ] **Step 6: Commit**

```bash
git add backend/rag_engine.py backend/routers/documents.py
git commit -m "feat(company-rag): thread folder_id through the ingestion pipeline"
```

---

## Task 4: Endpoints CRUD dossiers

**Files:**
- Modify: `backend/routers/company_rag.py` (imports + nouveaux endpoints)

- [ ] **Step 1: Mettre à jour les imports**

En tête de `backend/routers/company_rag.py`, ajouter `CompanyFolder` à l'import depuis `database`, et `Body` depuis fastapi :

```python
from fastapi import APIRouter, Body, BackgroundTasks, Depends, File, HTTPException, UploadFile
from database import get_db, Document, CompanyFolder
from sqlalchemy import func
```

(`func` sert au comptage de docs ; `Body` aux endpoints JSON.)

- [ ] **Step 2: Ajouter un helper de comptage et les endpoints dossiers**

À la fin de `backend/routers/company_rag.py`, ajouter :

```python
def _folder_or_404(folder_id: int, company_id: int, db: Session) -> CompanyFolder:
    folder = (
        db.query(CompanyFolder)
        .filter(CompanyFolder.id == folder_id, CompanyFolder.company_id == company_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.get("/api/company-rag/folders")
async def list_company_folders(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's company-RAG folders with document counts (any member)."""
    company_id = _require_company_id(user_id, db)
    counts = dict(
        db.query(Document.folder_id, func.count(Document.id))
        .filter(Document.company_id == company_id, Document.is_company_rag.is_(True))
        .group_by(Document.folder_id)
        .all()
    )
    folders = (
        db.query(CompanyFolder)
        .filter(CompanyFolder.company_id == company_id)
        .order_by(CompanyFolder.name.asc())
        .all()
    )
    return {
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "document_count": int(counts.get(f.id, 0)),
            }
            for f in folders
        ]
    }


@router.post("/api/company-rag/folders")
async def create_company_folder(
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a company-RAG folder (owner/admin only)."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    exists = (
        db.query(CompanyFolder)
        .filter(CompanyFolder.company_id == company_id, CompanyFolder.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="A folder with this name already exists")
    folder = CompanyFolder(company_id=company_id, name=name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "document_count": 0}


@router.put("/api/company-rag/folders/{folder_id}")
async def rename_company_folder(
    folder_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Rename a company-RAG folder (owner/admin only)."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    folder = _folder_or_404(folder_id, company_id, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    collision = (
        db.query(CompanyFolder)
        .filter(
            CompanyFolder.company_id == company_id,
            CompanyFolder.name == name,
            CompanyFolder.id != folder_id,
        )
        .first()
    )
    if collision:
        raise HTTPException(status_code=409, detail="A folder with this name already exists")
    folder.name = name
    db.commit()
    return {"id": folder.id, "name": folder.name}


@router.delete("/api/company-rag/folders/{folder_id}")
async def delete_company_folder(
    folder_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a company-RAG folder (owner/admin only). Blocked if the folder is not empty."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    folder = _folder_or_404(folder_id, company_id, db)
    doc_count = (
        db.query(func.count(Document.id))
        .filter(Document.folder_id == folder_id, Document.company_id == company_id)
        .scalar()
    )
    if doc_count:
        raise HTTPException(status_code=400, detail="Folder is not empty")
    db.delete(folder)
    db.commit()
    return {"status": "deleted", "id": folder_id}
```

- [ ] **Step 3: Lint**

Run: `cd backend && ruff check routers/company_rag.py`
Expected: `All checks passed!`

- [ ] **Step 4: Vérifier le chargement de l'app (routes enregistrées)**

Run: `cd backend && python -c "import main; paths=[r.path for r in main.app.routes]; print('/api/company-rag/folders' in paths)"`
Expected: `True` (ou, si l'import nécessite la DB, au minimum aucune `SyntaxError`/`ImportError` provenant de `company_rag.py`)

- [ ] **Step 5: Commit**

```bash
git add backend/routers/company_rag.py
git commit -m "feat(company-rag): folder CRUD endpoints (create/list/rename/delete, blocked if non-empty)"
```

---

## Task 5: Endpoints documents — `folder_id` obligatoire, GET enrichi, déplacement

**Files:**
- Modify: `backend/routers/company_rag.py` (`upload_company_document`, `list_company_documents`, nouvel endpoint move)

- [ ] **Step 1: Rendre `folder_id` obligatoire à l'upload**

Dans `upload_company_document`, ajouter le param form `folder_id` et le valider. Modifier la signature :

```python
from fastapi import Form  # ajouter Form à l'import fastapi en tête si absent

@router.post("/api/company-rag/documents")
async def upload_company_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_id: int = Form(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
```

Au tout début du `try`, après `company_id = _require_company_id(user_id, db)`, valider le dossier :

```python
        _folder_or_404(folder_id, company_id, db)
```

Puis propager `folder_id` aux deux chemins (async et sync). Pour le chemin async, l'appel `background_tasks.add_task(_process_document_background, ...)` passe actuellement les args **positionnellement** :

```python
            background_tasks.add_task(
                _process_document_background,
                task_id, file.filename, content, int(user_id), None, company_id, None, True, folder_id,
            )
```

(Ordre = `task_id, filename, content, user_id, agent_id, company_id, mission_id, is_company_rag, folder_id` — `folder_id` est le 10e argument, conforme à la signature de Task 3.)

Pour le chemin sync :

```python
        doc_id = process_document_for_user(
            file.filename, content, int(user_id), db,
            agent_id=None, company_id=company_id, is_company_rag=True, folder_id=folder_id,
        )
```

- [ ] **Step 2: Enrichir `list_company_documents` (folder_id + filtre optionnel)**

Remplacer le corps de `list_company_documents` pour accepter un filtre `folder_id` et renvoyer `folder_id` :

```python
@router.get("/api/company-rag/documents")
async def list_company_documents(
    folder_id: int = None,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's shared RAG documents (any member), optionally by folder."""
    company_id = _require_company_id(user_id, db)
    q = db.query(Document).filter(
        Document.company_id == company_id, Document.is_company_rag.is_(True)
    )
    if folder_id is not None:
        q = q.filter(Document.folder_id == folder_id)
    docs = q.order_by(Document.created_at.desc()).all()
    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "source_url": d.source_url,
                "document_type": d.document_type,
                "folder_id": d.folder_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }
```

- [ ] **Step 3: Ajouter l'endpoint de déplacement d'un doc**

À la fin du fichier, ajouter :

```python
@router.put("/api/company-rag/documents/{document_id}/folder")
async def move_company_document(
    document_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Move a company-RAG document to another folder (owner/admin only)."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    target_folder_id = payload.get("folder_id")
    if target_folder_id is None:
        raise HTTPException(status_code=400, detail="folder_id is required")
    _folder_or_404(int(target_folder_id), company_id, db)
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.company_id == company_id,
            Document.is_company_rag.is_(True),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Company document not found")
    doc.folder_id = int(target_folder_id)
    db.commit()
    return {"status": "moved", "id": document_id, "folder_id": doc.folder_id}
```

- [ ] **Step 4: Lint**

Run: `cd backend && ruff check routers/company_rag.py`
Expected: `All checks passed!`

- [ ] **Step 5: Vérifier l'absence d'erreur de signature (import)**

Run: `cd backend && python -c "import routers.company_rag as c; import inspect; print('folder_id' in inspect.signature(c.upload_company_document).parameters)"`
Expected: `True`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/company_rag.py
git commit -m "feat(company-rag): require folder_id on upload, expose folder_id, add doc move endpoint"
```

---

## Task 6: Agent — accepter/sérialiser `company_rag_folder_ids`

**Files:**
- Modify: `backend/routers/agents.py` (create ~171/250, update ~710/761, GET ~106/137/332)

- [ ] **Step 1: Ajouter un helper de parsing JSON en tête de `agents.py`**

Après les imports de `backend/routers/agents.py`, ajouter :

```python
import json as _json


def _parse_folder_ids(raw: str):
    """Parse the company_rag_folder_ids form field into a JSON string or None.
    Empty/[]/invalid -> None (means 'all folders')."""
    if not raw:
        return None
    try:
        ids = _json.loads(raw)
    except Exception:
        return None
    if not isinstance(ids, list):
        return None
    clean = [int(x) for x in ids if str(x).strip().lstrip("-").isdigit()]
    return _json.dumps(clean) if clean else None
```

- [ ] **Step 2: Accepter le champ à la création**

Dans l'endpoint de création, après le param form `include_company_rag: str = Form("false"),` (~171), ajouter :

```python
    company_rag_folder_ids: str = Form(None),
```

Puis, dans la construction `db_agent = Agent(... )` (~250), après `include_company_rag=include_company_rag.lower() in ("true", "1", "yes"),`, ajouter :

```python
            company_rag_folder_ids=_parse_folder_ids(company_rag_folder_ids),
```

- [ ] **Step 3: Accepter le champ à la mise à jour**

Dans l'endpoint de mise à jour, après le param form `include_company_rag: str = Form("false"),` (~710), ajouter :

```python
    company_rag_folder_ids: str = Form(None),
```

Puis, après `agent.include_company_rag = include_company_rag.lower() in ("true", "1", "yes")` (~761), ajouter :

```python
        agent.company_rag_folder_ids = _parse_folder_ids(company_rag_folder_ids)
```

- [ ] **Step 4: Sérialiser dans les réponses GET**

Aux 3 emplacements où `"include_company_rag": getattr(a/agent, "include_company_rag", False),` apparaît (~106, ~137, ~332), ajouter juste en dessous une ligne renvoyant la liste parsée. Définir d'abord un petit helper en tête (après `_parse_folder_ids`) :

```python
def _folder_ids_out(raw):
    """Serialize stored JSON company_rag_folder_ids back to a list ([] = all)."""
    if not raw:
        return []
    try:
        v = _json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []
```

Puis, à chacun des 3 emplacements, ajouter sous la ligne `include_company_rag` (en adaptant `a` vs `agent` selon le contexte local) :

```python
                "company_rag_folder_ids": _folder_ids_out(getattr(a, "company_rag_folder_ids", None)),
```

(Emplacement ~332 utilise la variable `agent` et non `a` — utiliser `getattr(agent, ...)` là-bas.)

- [ ] **Step 5: Lint**

Run: `cd backend && ruff check routers/agents.py`
Expected: `All checks passed!`

- [ ] **Step 6: Test unitaire pur du parsing (pas de DB)**

Ajouter dans `backend/tests/test_company_rag_folders.py` (créé en Task 8, mais ce test ne touche pas la DB) :

```python
from routers.agents import _parse_folder_ids, _folder_ids_out


def test_parse_folder_ids_empty_means_all():
    assert _parse_folder_ids("") is None
    assert _parse_folder_ids("[]") is None
    assert _parse_folder_ids(None) is None


def test_parse_folder_ids_valid_list():
    assert _parse_folder_ids("[1, 2, 3]") == "[1, 2, 3]"


def test_parse_folder_ids_garbage_means_all():
    assert _parse_folder_ids("not json") is None
    assert _parse_folder_ids('{"a":1}') is None


def test_folder_ids_out_roundtrip():
    assert _folder_ids_out(None) == []
    assert _folder_ids_out("[1, 2]") == [1, 2]
    assert _folder_ids_out("garbage") == []
```

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -k "parse_folder_ids or folder_ids_out" -v`
Expected: 4 tests PASS (ne nécessitent pas de DB)

- [ ] **Step 7: Commit**

```bash
git add backend/routers/agents.py backend/tests/test_company_rag_folders.py
git commit -m "feat(company-rag): agent create/update accept and serialize company_rag_folder_ids"
```

---

## Task 7: Filtrage par dossier dans la récupération RAG

**Files:**
- Modify: `backend/rag_engine.py` (`search_similar_texts_for_user` ~803/877, et les 3 lectures de `include_company_rag` ~247/440, ~547/708)

- [ ] **Step 1: Ajouter le param à `search_similar_texts_for_user`**

Dans `backend/rag_engine.py`, signature de `search_similar_texts_for_user` (~803) : ajouter `company_rag_folder_ids: list = None` après `include_company_rag: bool = False,`.

Puis, dans la branche `agent_id` du filtre (lignes ~875-880), modifier l'union pour restreindre les docs entreprise aux dossiers sélectionnés quand la liste est non vide :

```python
        elif agent_id:
            # Agent-scoped docs; optionally union the company-shared docs
            agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
            if include_company_rag:
                company_scope = Document.is_company_rag.is_(True)
                if company_rag_folder_ids:
                    company_scope = and_(company_scope, Document.folder_id.in_(company_rag_folder_ids))
                query = query.filter(or_(agent_scope, company_scope))
            else:
                query = query.filter(agent_scope, Document.is_company_rag.is_(False))
```

(`and_`, `or_` sont déjà importés et utilisés dans le fichier.)

- [ ] **Step 2: Lire `company_rag_folder_ids` depuis l'agent dans `get_answer`**

Dans `get_answer`, à l'endroit où `include_company_rag` est calculé (~247) :

```python
        include_company_rag = bool(getattr(agent, "include_company_rag", False)) if agent else False
        company_rag_folder_ids = _agent_folder_ids(agent) if include_company_rag else None
```

Et là où `search_similar_texts_for_user(...)` est appelé (~440), ajouter l'argument :

```python
                include_company_rag=include_company_rag,
                company_rag_folder_ids=company_rag_folder_ids,
```

Aussi, dans le bloc de sélection directe des docs en contexte agent (le `db.query(Document).filter(or_(Document.agent_id == agent_id, and_(Document.is_company_rag.is_(True), Document.company_id == company_scope_id) if include_company_rag else False), ...))` ~273-290) : remplacer la sous-clause company par une version filtrée par dossier :

```python
                            and_(
                                Document.is_company_rag.is_(True),
                                Document.company_id == company_scope_id,
                                Document.folder_id.in_(company_rag_folder_ids) if company_rag_folder_ids else true(),
                            )
                            if include_company_rag
                            else False,
```

Ajouter `true` à l'import SQLAlchemy en tête de `rag_engine.py` (`from sqlalchemy import ..., true`). Si l'ajout de `true()` complique, utiliser l'équivalent sans import : remplacer `Document.folder_id.in_(company_rag_folder_ids) if company_rag_folder_ids else true()` par une construction conditionnelle du `and_` en Python (n'inclure le terme `folder_id.in_(...)` que si `company_rag_folder_ids`). Choisir l'option la plus lisible au moment de l'édition.

- [ ] **Step 3: Idem dans `get_answer_stream`**

Reproduire exactement les modifications du Step 2 dans `get_answer_stream` : lecture `company_rag_folder_ids` (~547), bloc de sélection directe (~569-583), et l'appel `search_similar_texts_for_user(...)` (~708, ajouter `company_rag_folder_ids=company_rag_folder_ids,`).

- [ ] **Step 4: Ajouter le helper `_agent_folder_ids`**

En tête de `rag_engine.py` (après les imports), ajouter :

```python
import json as _json


def _agent_folder_ids(agent):
    """Return the agent's selected company-RAG folder ids as a list, or None for 'all'."""
    raw = getattr(agent, "company_rag_folder_ids", None)
    if not raw:
        return None
    try:
        ids = _json.loads(raw)
    except Exception:
        return None
    if not isinstance(ids, list) or not ids:
        return None
    return [int(x) for x in ids if str(x).strip().lstrip("-").isdigit()] or None
```

(Si `json` est déjà importé dans le fichier, réutiliser l'import existant au lieu d'`_json`.)

- [ ] **Step 5: Lint**

Run: `cd backend && ruff check rag_engine.py`
Expected: `All checks passed!`

- [ ] **Step 6: Vérifier l'import du module**

Run: `cd backend && python -c "import rag_engine, inspect; print('company_rag_folder_ids' in inspect.signature(rag_engine.search_similar_texts_for_user).parameters)"`
Expected: `True`

- [ ] **Step 7: Commit**

```bash
git add backend/rag_engine.py
git commit -m "feat(company-rag): filter company docs by selected folders during retrieval"
```

---

## Task 8: Tests backend DB-backed

Ces tests **skippent en local** (pas de Postgres) et **tournent en CI**, comme `test_company_rag.py`. Reproduire le mécanisme de skip/fixtures de ce fichier existant.

**Files:**
- Create: `backend/tests/test_company_rag_folders.py` (compléter le fichier amorcé en Task 6)

- [ ] **Step 1: Lire le fichier de tests existant pour réutiliser fixtures et skip-guard**

Run: `cat backend/tests/test_company_rag.py`
But : copier le mécanisme d'accès DB (fixtures `db`/`client`, marqueur de skip si pas de Postgres, helpers de création company/user/role).

- [ ] **Step 2: Écrire les tests dossiers (en réutilisant les fixtures repérées)**

Ajouter à `backend/tests/test_company_rag_folders.py`, en haut, le même skip-guard et les mêmes fixtures que `test_company_rag.py` (adapter les imports). Puis les cas suivants (pseudo-structure à adapter aux fixtures réelles du repo) :

```python
def test_create_and_list_folder(client, admin_headers):
    r = client.post("/api/company-rag/folders", json={"name": "Marketing"}, headers=admin_headers)
    assert r.status_code == 200
    fid = r.json()["id"]
    r2 = client.get("/api/company-rag/folders", headers=admin_headers)
    names = [f["name"] for f in r2.json()["folders"]]
    assert "Marketing" in names
    assert any(f["id"] == fid and f["document_count"] == 0 for f in r2.json()["folders"])


def test_duplicate_folder_name_conflicts(client, admin_headers):
    client.post("/api/company-rag/folders", json={"name": "Dup"}, headers=admin_headers)
    r = client.post("/api/company-rag/folders", json={"name": "Dup"}, headers=admin_headers)
    assert r.status_code == 409


def test_rename_folder(client, admin_headers):
    fid = client.post("/api/company-rag/folders", json={"name": "Old"}, headers=admin_headers).json()["id"]
    r = client.put(f"/api/company-rag/folders/{fid}", json={"name": "New"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["name"] == "New"


def test_delete_empty_folder_ok(client, admin_headers):
    fid = client.post("/api/company-rag/folders", json={"name": "Empty"}, headers=admin_headers).json()["id"]
    r = client.delete(f"/api/company-rag/folders/{fid}", headers=admin_headers)
    assert r.status_code == 200


def test_member_cannot_create_folder(client, member_headers):
    r = client.post("/api/company-rag/folders", json={"name": "X"}, headers=member_headers)
    assert r.status_code in (401, 403)


def test_upload_requires_folder_id(client, admin_headers):
    # multipart without folder_id -> 422 (FastAPI required Form field)
    r = client.post(
        "/api/company-rag/documents",
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_tenant_isolation_on_folders(client, admin_headers, other_company_admin_headers):
    fid = client.post("/api/company-rag/folders", json={"name": "Secret"}, headers=admin_headers).json()["id"]
    # other company's admin cannot rename/delete it
    assert client.put(f"/api/company-rag/folders/{fid}", json={"name": "Hack"}, headers=other_company_admin_headers).status_code == 404
    assert client.delete(f"/api/company-rag/folders/{fid}", headers=other_company_admin_headers).status_code == 404
```

> Note : si `test_company_rag.py` ne fournit pas de fixtures `member_headers` / `other_company_admin_headers`, ne garder que les cas réalisables avec les fixtures existantes et adapter les noms. Les cas de suppression-bloquée-si-non-vide et de filtrage-récupération nécessitent de créer un doc avec chunks ; si le harnais de test existant le permet (helper d'insertion `Document`), les ajouter :

```python
def test_delete_non_empty_folder_blocked(client, admin_headers, db, company_id):
    from database import CompanyFolder, Document
    f = CompanyFolder(company_id=company_id, name="Full")
    db.add(f); db.commit(); db.refresh(f)
    db.add(Document(filename="d.txt", user_id=1, company_id=company_id, is_company_rag=True, folder_id=f.id))
    db.commit()
    r = client.delete(f"/api/company-rag/folders/{f.id}", headers=admin_headers)
    assert r.status_code == 400
```

- [ ] **Step 3: Lancer les tests localement (attendu : skip DB, pass parsing)**

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -v`
Expected: les tests DB **SKIP** (pas de Postgres local) ; les 4 tests de parsing (Task 6) **PASS**. Aucune erreur de collecte/import.

- [ ] **Step 4: Lint des tests**

Run: `cd backend && ruff check tests/test_company_rag_folders.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_company_rag_folders.py
git commit -m "test(company-rag): folder CRUD, tenant isolation, upload requires folder_id"
```

---

## Task 9: Frontend — `organization.js` (dossiers + déplacement + fix UX)

**Files:**
- Modify: `frontend/pages/organization.js` (état ~95-97, loaders ~105/125/172, handlers ~184-212, rendu ~670-728)

- [ ] **Step 1: Ajouter l'état dossiers**

Près de `const [companyDocs, setCompanyDocs] = useState([]);` (~96), ajouter :

```javascript
  const [folders, setFolders] = useState([]);
  const [selectedFolderId, setSelectedFolderId] = useState(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
```

- [ ] **Step 2: Charger les dossiers + sélectionner le premier**

Ajouter une fonction `loadFolders` près de `loadCompanyDocs` (~172) :

```javascript
  const loadFolders = async () => {
    try {
      const res = await api.get('/api/company-rag/folders');
      const list = res.data.folders || [];
      setFolders(list);
      setSelectedFolderId(prev => (prev && list.some(f => f.id === prev) ? prev : (list[0]?.id ?? null)));
    } catch {
      toast.error(t('organization:companyRag.loadError'));
    }
  };
```

Dans le flux d'initialisation où `loadCompanyDocs()` est appelé (~125), appeler aussi `loadFolders()`.

- [ ] **Step 3: Recharger les docs du dossier sélectionné**

Modifier `loadCompanyDocs` pour filtrer par dossier sélectionné :

```javascript
  const loadCompanyDocs = async (folderId = selectedFolderId) => {
    try {
      setCompanyDocsLoading(true);
      const url = folderId ? `/api/company-rag/documents?folder_id=${folderId}` : '/api/company-rag/documents';
      const res = await api.get(url);
      setCompanyDocs(res.data.documents || []);
    } catch {
      toast.error(t('organization:companyRag.loadError'));
    } finally {
      setCompanyDocsLoading(false);
    }
  };
```

Ajouter un `useEffect` qui recharge les docs quand `selectedFolderId` change :

```javascript
  useEffect(() => {
    if (selectedFolderId) loadCompanyDocs(selectedFolderId);
    else setCompanyDocs([]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFolderId]);
```

- [ ] **Step 4: Handlers création/renommage/suppression de dossier**

Ajouter près des handlers existants (~212) :

```javascript
  const handleCreateFolder = async () => {
    const name = (window.prompt(t('organization:companyRag.folderNamePrompt')) || '').trim();
    if (!name) return;
    try {
      setCreatingFolder(true);
      const res = await api.post('/api/company-rag/folders', { name });
      await loadFolders();
      setSelectedFolderId(res.data.id);
    } catch (e) {
      toast.error(e.response?.data?.detail || t('organization:companyRag.folderCreateError'));
    } finally {
      setCreatingFolder(false);
    }
  };

  const handleRenameFolder = async (folder) => {
    const name = (window.prompt(t('organization:companyRag.folderNamePrompt'), folder.name) || '').trim();
    if (!name || name === folder.name) return;
    try {
      await api.put(`/api/company-rag/folders/${folder.id}`, { name });
      await loadFolders();
    } catch (e) {
      toast.error(e.response?.data?.detail || t('organization:companyRag.folderRenameError'));
    }
  };

  const handleDeleteFolder = async (folder) => {
    if (!confirm(t('organization:companyRag.folderDeleteConfirm'))) return;
    try {
      await api.delete(`/api/company-rag/folders/${folder.id}`);
      const remaining = folders.filter(f => f.id !== folder.id);
      setFolders(remaining);
      if (selectedFolderId === folder.id) setSelectedFolderId(remaining[0]?.id ?? null);
    } catch (e) {
      toast.error(e.response?.data?.detail || t('organization:companyRag.folderDeleteError'));
    }
  };
```

- [ ] **Step 5: Upload dans le dossier sélectionné + fix du bug d'affichage (polling)**

Remplacer `handleCompanyDocUpload` par une version qui envoie `folder_id` et qui poll le statut :

```javascript
  const pollCompanyUpload = async (taskId) => {
    for (let i = 0; i < 150; i++) {
      await new Promise(r => setTimeout(r, 1500));
      try {
        const res = await api.get(`/upload-status/${taskId}`);
        const { status, error } = res.data;
        if (status === 'completed') { await loadCompanyDocs(); await loadFolders(); return; }
        if (status === 'failed') { toast.error(error || t('organization:companyRag.uploadError')); return; }
      } catch { /* keep polling */ }
    }
    toast.error(t('organization:companyRag.uploadError'));
  };

  const handleCompanyDocUpload = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (!selectedFolderId) { toast.error(t('organization:companyRag.pickFolderFirst')); e.target.value = ''; return; }
    const fd = new FormData();
    fd.append('file', file);
    fd.append('folder_id', selectedFolderId);
    try {
      setCompanyDocUploading(true);
      const res = await api.post('/api/company-rag/documents', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      toast.success(t('organization:companyRag.uploadSuccess'));
      if (res.data.task_id) {
        await pollCompanyUpload(res.data.task_id);
      } else {
        await loadCompanyDocs();
        await loadFolders();
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:companyRag.uploadError'));
    } finally {
      setCompanyDocUploading(false);
      e.target.value = '';
    }
  };
```

- [ ] **Step 6: Handler déplacement de doc**

Ajouter :

```javascript
  const handleMoveDoc = async (docId, targetFolderId) => {
    if (!targetFolderId || targetFolderId === selectedFolderId) return;
    try {
      await api.put(`/api/company-rag/documents/${docId}/folder`, { folder_id: targetFolderId });
      await loadCompanyDocs();
      await loadFolders();
    } catch (e) {
      toast.error(e.response?.data?.detail || t('organization:companyRag.moveError'));
    }
  };
```

- [ ] **Step 7: Rendu — barre de dossiers + sélecteur de déplacement**

Dans le bloc « RAG Entreprise » (~671-728), juste après le `<p>` de description (~692) et **avant** la liste des docs, insérer la barre de dossiers :

```jsx
                    <div className="flex flex-wrap items-center gap-2 mb-4">
                      {folders.map(f => (
                        <div key={f.id}
                          className={`group flex items-center rounded-button border px-3 py-1.5 text-sm cursor-pointer transition-colors ${selectedFolderId === f.id ? 'bg-teal-50 border-teal-300 text-teal-800' : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'}`}
                          onClick={() => setSelectedFolderId(f.id)}>
                          <span className="font-medium">{f.name}</span>
                          <span className="ml-2 text-xs text-gray-400">{f.document_count}</span>
                          {canManage && (
                            <span className="ml-2 hidden group-hover:inline-flex items-center gap-1">
                              <button onClick={(ev) => { ev.stopPropagation(); handleRenameFolder(f); }}
                                className="text-gray-400 hover:text-gray-700" title={t('organization:companyRag.folderRename')}>✎</button>
                              <button onClick={(ev) => { ev.stopPropagation(); handleDeleteFolder(f); }}
                                className="text-red-400 hover:text-red-600" title={t('organization:companyRag.folderDelete')}>🗑</button>
                            </span>
                          )}
                        </div>
                      ))}
                      {canManage && (
                        <button onClick={handleCreateFolder} disabled={creatingFolder}
                          className="rounded-button border border-dashed border-gray-300 px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-50">
                          + {t('organization:companyRag.newFolder')}
                        </button>
                      )}
                    </div>
```

Dans chaque `<li>` de document (~709-721), ajouter — avant le bouton download, visible si `canManage` et au moins 2 dossiers — un sélecteur de déplacement :

```jsx
                              {canManage && folders.length > 1 && (
                                <select
                                  value={doc.folder_id || ''}
                                  onChange={(e) => handleMoveDoc(doc.id, Number(e.target.value))}
                                  onClick={(e) => e.stopPropagation()}
                                  className="text-xs border border-gray-200 rounded-button px-2 py-1 bg-white text-gray-600"
                                  title={t('organization:companyRag.moveTo')}>
                                  {folders.map(f => (
                                    <option key={f.id} value={f.id}>{f.name}</option>
                                  ))}
                                </select>
                              )}
```

Adapter le message « empty » : afficher `companyRag.emptyFolder` quand un dossier est sélectionné mais vide, et `companyRag.noFolders` quand `folders.length === 0`.

- [ ] **Step 8: Lint + build**

Run: `cd frontend && npm run lint`
Expected: pas d'erreur ESLint sur `organization.js`.

Run: `cd frontend && npm run build`
Expected: build Next.js réussi.

- [ ] **Step 9: Commit**

```bash
git add frontend/pages/organization.js
git commit -m "feat(company-rag): folders UI in organization page + move docs + fix upload display bug"
```

---

## Task 10: Frontend — multi-select dossiers à la création d'agent (`agents.js`)

**Files:**
- Modify: `frontend/pages/agents.js` (form state ~31, toggle ~585-591, submit ~665, useEffect de chargement)

- [ ] **Step 1: Ajouter `company_rag_folder_ids` à l'état du form**

Dans `useState({ ... })` (~31), ajouter `company_rag_folder_ids: []` à l'objet initial (à côté de `include_company_rag: false`).

Ajouter aussi un état pour la liste des dossiers disponibles, près des autres `useState` du composant :

```javascript
  const [companyFolders, setCompanyFolders] = useState([]);
```

- [ ] **Step 2: Charger les dossiers disponibles**

Dans le `useEffect` d'initialisation du composant (là où les données initiales sont chargées), ajouter un chargement best-effort :

```javascript
    api.get('/api/company-rag/folders')
      .then(res => setCompanyFolders(res.data.folders || []))
      .catch(() => setCompanyFolders([]));
```

- [ ] **Step 3: Afficher le multi-select quand le toggle est actif**

Juste après le bloc du toggle `include_company_rag` (~591), ajouter un sélecteur de dossiers (tout coché = liste vide = tous) :

```jsx
                  {form.include_company_rag && companyFolders.length > 0 && (
                    <div className="mt-3 ml-1 space-y-2">
                      <p className="text-xs text-gray-500">{t('agents:companyRagFolders.label')}</p>
                      <div className="flex flex-wrap gap-2">
                        {companyFolders.map(f => {
                          const all = !form.company_rag_folder_ids || form.company_rag_folder_ids.length === 0;
                          const checked = all || form.company_rag_folder_ids.includes(f.id);
                          return (
                            <label key={f.id}
                              className={`flex items-center gap-2 px-3 py-1.5 rounded-button border text-sm cursor-pointer ${checked ? 'bg-emerald-50 border-emerald-300 text-emerald-800' : 'bg-white border-gray-200 text-gray-600'}`}>
                              <input type="checkbox" checked={checked}
                                onChange={() => setForm(prev => {
                                  const base = (!prev.company_rag_folder_ids || prev.company_rag_folder_ids.length === 0)
                                    ? companyFolders.map(x => x.id)
                                    : [...prev.company_rag_folder_ids];
                                  const next = base.includes(f.id) ? base.filter(id => id !== f.id) : [...base, f.id];
                                  // all selected -> store [] (means "all", dynamic)
                                  return { ...prev, company_rag_folder_ids: next.length === companyFolders.length ? [] : next };
                                })} />
                              {f.name}
                            </label>
                          );
                        })}
                      </div>
                      <p className="text-xs text-gray-400">{t('agents:companyRagFolders.allHint')}</p>
                    </div>
                  )}
```

- [ ] **Step 4: Envoyer le champ dans le FormData**

À la soumission (~665), juste après `formData.append("include_company_rag", ...)`, ajouter :

```javascript
                    formData.append("company_rag_folder_ids", JSON.stringify(form.company_rag_folder_ids || []));
```

- [ ] **Step 5: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: succès.

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/agents.js
git commit -m "feat(company-rag): folder multi-select on agent creation"
```

---

## Task 11: Frontend — multi-select dossiers à l'édition d'agent (`index.js`)

**Files:**
- Modify: `frontend/pages/index.js` (form state ~65, hydratation ~186, toggle ~1238-1241, submit ~505, chargement dossiers)

- [ ] **Step 1: État form + liste dossiers**

Dans l'objet `useState` du form (~65), ajouter `company_rag_folder_ids: [],` à côté de `include_company_rag: false`.

Ajouter un état dossiers près des autres `useState` :

```javascript
  const [companyFolders, setCompanyFolders] = useState([]);
```

Charger les dossiers (best-effort) dans le `useEffect` d'initialisation :

```javascript
    api.get('/api/company-rag/folders')
      .then(res => setCompanyFolders(res.data.folders || []))
      .catch(() => setCompanyFolders([]));
```

- [ ] **Step 2: Hydrater depuis l'agent à l'édition**

Là où le form est rempli depuis `agent` (~186, à côté de `include_company_rag: agent.include_company_rag || false,`), ajouter :

```javascript
        company_rag_folder_ids: agent.company_rag_folder_ids || [],
```

- [ ] **Step 3: Afficher le multi-select sous le toggle**

Juste après le bloc du toggle `include_company_rag` (~1241), insérer le **même** multi-select qu'en Task 10 Step 3 (copier le JSX à l'identique — il référence `form.company_rag_folder_ids`, `companyFolders`, `setForm`, `t`, déjà présents dans `index.js`).

- [ ] **Step 4: Envoyer le champ**

À la soumission (~505), juste après `formData.append("include_company_rag", ...)`, ajouter :

```javascript
      formData.append("company_rag_folder_ids", JSON.stringify(f.company_rag_folder_ids || []));
```

- [ ] **Step 5: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: succès.

- [ ] **Step 6: Commit**

```bash
git add frontend/pages/index.js
git commit -m "feat(company-rag): folder multi-select on agent edit"
```

---

## Task 12: i18n — clés de traduction

**Files:**
- Modify: `frontend/public/locales/fr/organization.json`, `frontend/public/locales/en/organization.json`
- Modify: `frontend/public/locales/fr/agents.json`, `frontend/public/locales/en/agents.json`

- [ ] **Step 1: Repérer le bloc `companyRag` existant**

Run: `grep -n "companyRag" frontend/public/locales/fr/organization.json`
Objectif : ajouter les nouvelles clés dans l'objet `companyRag` existant.

- [ ] **Step 2: Ajouter les clés FR (`organization.json`)**

Dans l'objet `companyRag` de `frontend/public/locales/fr/organization.json`, ajouter :

```json
    "newFolder": "Nouveau dossier",
    "folderNamePrompt": "Nom du dossier",
    "folderRename": "Renommer",
    "folderDelete": "Supprimer",
    "folderDeleteConfirm": "Supprimer ce dossier ? (il doit être vide)",
    "folderCreateError": "Impossible de créer le dossier",
    "folderRenameError": "Impossible de renommer le dossier",
    "folderDeleteError": "Impossible de supprimer le dossier (non vide ?)",
    "pickFolderFirst": "Sélectionnez d'abord un dossier",
    "moveTo": "Déplacer vers",
    "moveError": "Impossible de déplacer le document",
    "emptyFolder": "Aucun document dans ce dossier",
    "noFolders": "Créez un dossier pour commencer"
```

- [ ] **Step 3: Ajouter les clés EN (`organization.json`)**

Dans `frontend/public/locales/en/organization.json`, objet `companyRag` :

```json
    "newFolder": "New folder",
    "folderNamePrompt": "Folder name",
    "folderRename": "Rename",
    "folderDelete": "Delete",
    "folderDeleteConfirm": "Delete this folder? (it must be empty)",
    "folderCreateError": "Could not create folder",
    "folderRenameError": "Could not rename folder",
    "folderDeleteError": "Could not delete folder (not empty?)",
    "pickFolderFirst": "Select a folder first",
    "moveTo": "Move to",
    "moveError": "Could not move document",
    "emptyFolder": "No documents in this folder",
    "noFolders": "Create a folder to get started"
```

- [ ] **Step 4: Ajouter la clé `companyRagFolders` (agents.json FR + EN)**

Dans `frontend/public/locales/fr/agents.json`, ajouter au niveau racine :

```json
  "companyRagFolders": {
    "label": "Dossiers du RAG Entreprise inclus",
    "allHint": "Tout coché = tous les dossiers (y compris les futurs)"
  }
```

Dans `frontend/public/locales/en/agents.json` :

```json
  "companyRagFolders": {
    "label": "Included Company RAG folders",
    "allHint": "All checked = all folders (including future ones)"
  }
```

(Attention à la virgule JSON entre la nouvelle clé et les clés voisines.)

- [ ] **Step 5: Valider le JSON**

Run: `cd frontend && node -e "['fr','en'].forEach(l=>{require('./public/locales/'+l+'/organization.json');require('./public/locales/'+l+'/agents.json')});console.log('JSON OK')"`
Expected: `JSON OK`

- [ ] **Step 6: Build**

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 7: Commit**

```bash
git add frontend/public/locales
git commit -m "i18n(company-rag): folder management + agent folder selection keys (fr+en)"
```

---

## Task 13: Vérification d'ensemble + push

- [ ] **Step 1: Lint backend complet**

Run: `cd backend && ruff check .`
Expected: `All checks passed!`

- [ ] **Step 2: Tests backend (skip DB local attendu)**

Run: `cd backend && python -m pytest -q`
Expected: aucun échec ; tests DB skippés, tests purs (parsing) passés.

- [ ] **Step 3: Lint + build frontend**

Run: `cd frontend && npm run lint && npm run build`
Expected: succès.

- [ ] **Step 4: Revue manuelle du diff**

Run: `git log --oneline dev..HEAD`
Vérifier : 12 commits cohérents, périmètre = dossiers RAG entreprise uniquement, rien hors sujet.

- [ ] **Step 5: Push de la branche**

```bash
git push -u origin feature/company-rag-folders
```

(Ne pas merger ni ouvrir de PR sans le feu vert de l'utilisateur — cf. politique du repo. CI s'exécute sur le push et fera tourner les tests DB-backed.)

---

## Notes de cohérence (self-review)

- **Couverture spec :** dossiers plats (Task 1) ✓ ; dossier obligatoire à l'upload (Task 5) ✓ ; défaut « tous » dynamique = `[]`/NULL (Tasks 6, 7, 10, 11) ✓ ; gestion créer/renommer/supprimer/déplacer (Tasks 4, 5, 9) ✓ ; suppression bloquée si non vide (Task 4) ✓ ; migration « Général » (Task 2) ✓ ; filtrage récupération (Task 7) ✓ ; fix UX polling (Task 9) ✓ ; i18n (Task 12) ✓ ; sécurité tenant + admin (Tasks 4, 5) ✓.
- **Noms cohérents :** champ form/colonne/JSON = `company_rag_folder_ids` partout (backend + frontend) ; `folder_id` partout pour le rattachement doc ; sémantique « `[]`/NULL = tous » identique côté agent (Task 6/7) et UI (Task 10/11).
- **Threading `folder_id` :** `_process_document_background` (10e arg positionnel) → `process_document_for_user(folder_id=...)` → `ingest_text_content(folder_id=...)` → `Document(folder_id=...)`. Ordre des args positionnels vérifié contre la signature de Task 3.
