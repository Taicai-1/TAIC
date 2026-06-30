# RAG Import de dossier (Phase 2) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre l'import d'un **dossier entier** (avec sous-dossiers) dans les deux systèmes RAG (companion `AgentFolder` et entreprise `CompanyFolder`) : l'arborescence du répertoire choisi est recréée sous la destination, les fichiers non supportés sont ignorés/comptés, aucun dossier vide n'est créé.

**Architecture:** Un module partagé `backend/folder_import.py` contient la logique pure et testable (découpage de chemin, résolution/fusion paresseuse de la chaîne de dossiers, moteur de boucle d'import) + les helpers de statut Redis. Les deux routeurs exposent `POST …/folders/import` (multipart `files[]` + `paths[]` + `parent_id`) et `GET …/folders/import-status/{task_id}`, et câblent le moteur partagé avec leurs spécificités (find/create folder par tenant, ingestion companion vs entreprise). Le job tourne via `BackgroundTasks` quand Redis est disponible, sinon en synchrone (réponse immédiate avec récapitulatif). Le frontend ajoute un `<input webkitdirectory>` qui envoie `files[]`/`paths[]` puis sonde le statut et affiche une barre de progression + récap.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Redis, Next.js (Pages Router), React, Tailwind, pytest. Les tests DB-backed skippent en local et tournent en CI ; les tests purs du module d'import tournent partout.

---

## Notes transverses

- **Dépend de la Phase 1** (sous-dossiers `parent_id`, déjà mergée sur la branche `feature/rag-subfolders-import`). Ce plan continue sur la **même branche**.
- **Déviation assumée vs la spec** : la spec listait `frontend/pages/sources/[agentId].js` parmi les pages d'import companion. **Cette page est URL-only (aucun upload de fichier).** L'import companion est donc placé sur `frontend/pages/index.js` (qui possède déjà `uploadDocument` + `pollUploadStatus` via `/upload-agent`). La page `sources/[agentId].js` est hors périmètre de ce plan.
- **Pipeline réutilisé** : `process_document_for_user(filename, content, user_id, db, agent_id=, company_id=, is_company_rag=, folder_id=, agent_folder_id=)` (dans `backend/rag_engine.py`) ingère **un** fichier. L'import boucle dessus, un fichier à la fois.
- **Validation par fichier** : `validate_file_extension(filename)` + `validate_file_content(content, filename)` (dans `backend/validation.py`). `MAX_FILE_SIZE = 50 MB`. Extensions UI : `.pdf,.txt,.docx,.doc,.json`.
- **Statut async** : nouveau namespace Redis `import_task:{uuid}` (distinct de `doc_task:`), TTL 3600s, via `get_redis()` (`backend/redis_client.py`, renvoie `None` si indisponible).
- **Caps anti-abus** (nouvelles constantes dans `folder_import.py`) : `MAX_IMPORT_FILES = 200`, `MAX_IMPORT_TOTAL_SIZE = 200 * 1024 * 1024` (200 MB). Dépassement → 413 au POST.
- **Permissions** : companion `_user_can_edit_agent(int(user_id), agent_id, db)` (déjà importé dans `agent_folders.py`) ; entreprise `require_role(int(user_id), db, "admin")` + `_require_company_id` (déjà utilisés dans `company_rag.py`).
- **Lecture des fichiers AVANT le background task** : `UploadFile` se ferme après la réponse HTTP. Le handler lit tout en mémoire (`await f.read()`) et passe une `list[(filename, rel_path, bytes)]` au job. Le cap total borne la mémoire.
- **Lint** : `ruff check .` ET `ruff format --check .`. Lancer `ruff format <fichiers>` avant de committer du backend. Frontend : `npm run lint` + `npm run build`.

## Structure des fichiers

| Fichier | Responsabilité | Création/Modif |
|---------|----------------|----------------|
| `backend/folder_import.py` | **Nouveau** : `split_relative_path`, `resolve_folder_for_path`, `run_folder_import`, `set_import_status`/`get_import_status`, caps | Création |
| `backend/routers/agent_folders.py` | Endpoints import + import-status companion ; background job companion | Modif |
| `backend/routers/company_rag.py` | Endpoints import + import-status entreprise ; background job entreprise | Modif |
| `backend/tests/test_folder_import.py` | **Nouveau** : tests purs du module (sans DB) | Création |
| `backend/tests/test_agent_folders.py` | Tests DB import companion | Modif |
| `backend/tests/test_company_rag_folders.py` | Tests DB import entreprise | Modif |
| `frontend/pages/index.js` | Bouton « Importer un dossier » companion + progression | Modif |
| `frontend/pages/organization.js` | Bouton « Importer un dossier » entreprise + progression | Modif |
| `frontend/public/locales/{fr,en}/agents.json` | Clés i18n import companion | Modif |
| `frontend/public/locales/{fr,en}/organization.json` | Clés i18n import entreprise | Modif |

---

## Task 1 : Module partagé `folder_import.py` (logique pure, TDD)

**Files:**
- Create: `backend/folder_import.py`
- Test: `backend/tests/test_folder_import.py`

- [ ] **Step 1 : Écrire les tests purs (qui échouent)**

Créer `backend/tests/test_folder_import.py` :

```python
from folder_import import split_relative_path, resolve_folder_for_path, run_folder_import


def test_split_relative_path_basic():
    assert split_relative_path("Contrats/2024/bail.pdf") == (["Contrats", "2024"], "bail.pdf")
    assert split_relative_path("bail.pdf") == ([], "bail.pdf")
    assert split_relative_path("a\\b\\c.txt") == (["a", "b"], "c.txt")
    assert split_relative_path("./x/../y/z.txt") == (["y"], "z.txt")
    assert split_relative_path("") == ([], "")


class _FakeTree:
    """In-memory folder store for testing find/create callbacks."""

    def __init__(self):
        self.rows = {}  # id -> (parent_id, name)
        self._next = 1

    def find_child(self, parent_id, name):
        for fid, (pid, nm) in self.rows.items():
            if pid == parent_id and nm == name:
                return fid
        return None

    def create_child(self, parent_id, name):
        fid = self._next
        self._next += 1
        self.rows[fid] = (parent_id, name)
        return fid


def test_resolve_folder_for_path_creates_chain():
    tree = _FakeTree()
    cache = {}
    leaf = resolve_folder_for_path(["A", "B"], None, tree.find_child, tree.create_child, cache)
    assert tree.rows[leaf] == (tree.find_child(None, "A"), "B")
    # empty segments -> destination itself
    assert resolve_folder_for_path([], 7, tree.find_child, tree.create_child, cache) == 7


def test_resolve_folder_for_path_merges_existing():
    tree = _FakeTree()
    a = tree.create_child(None, "A")
    cache = {}
    leaf = resolve_folder_for_path(["A", "B"], None, tree.find_child, tree.create_child, cache)
    # "A" reused (merge), "B" created under it
    assert tree.rows[leaf][0] == a
    assert len([r for r in tree.rows.values() if r == (None, "A")]) == 1


def test_resolve_folder_for_path_caches():
    tree = _FakeTree()
    calls = {"create": 0}
    orig_create = tree.create_child

    def counting_create(p, n):
        calls["create"] += 1
        return orig_create(p, n)

    cache = {}
    resolve_folder_for_path(["A", "B"], None, tree.find_child, counting_create, cache)
    resolve_folder_for_path(["A", "B", "C"], None, tree.find_child, counting_create, cache)
    # A and B created once (cache hit on 2nd call), C created once -> 3 creates total
    assert calls["create"] == 3


def test_run_folder_import_skips_unsupported_no_empty_folders():
    tree = _FakeTree()
    ingested = []

    def is_supported(filename, content):
        return filename.endswith(".pdf")

    def ingest_file(filename, content, folder_id):
        ingested.append((filename, folder_id))

    statuses = []

    def set_status(total, done, skipped, failed, root_folder_id, status):
        statuses.append((done, skipped, failed, status))

    items = [
        ("a.pdf", "Root/Sub/a.pdf", b"x"),
        ("b.exe", "Root/Empty/b.exe", b"x"),  # unsupported -> skipped, "Empty" never created
        ("c.pdf", "Root/Sub/c.pdf", b"x"),
    ]
    summary = run_folder_import(
        items, None, tree.find_child, tree.create_child, ingest_file, is_supported, set_status
    )
    assert summary == {"total": 3, "done": 2, "skipped": 1, "failed": 0, "root_folder_id": summary["root_folder_id"]}
    assert summary["done"] == 2 and summary["skipped"] == 1
    # no "Empty" folder created (lazy creation only on supported files)
    assert not any(nm == "Empty" for (_, nm) in tree.rows.values())
    # root_folder_id is the "Root" folder
    assert tree.rows[summary["root_folder_id"]] == (None, "Root")
    assert statuses[-1][3] == "completed"


def test_run_folder_import_counts_failures():
    tree = _FakeTree()

    def is_supported(filename, content):
        return True

    def ingest_file(filename, content, folder_id):
        raise RuntimeError("boom")

    summary = run_folder_import(
        [("a.pdf", "R/a.pdf", b"x")], None, tree.find_child, tree.create_child, ingest_file, lambda *a: True, lambda *a: None
    )
    assert summary["failed"] == 1 and summary["done"] == 0
```

- [ ] **Step 2 : Lancer les tests (échec attendu)**

Run: `cd backend && python -m pytest tests/test_folder_import.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'folder_import'`.

- [ ] **Step 3 : Implémenter `folder_import.py`**

Créer `backend/folder_import.py` :

```python
"""Shared, mostly-pure logic for importing a whole directory tree into a RAG folder system.

The two routers (companion `agent_folders` and company `company_rag`) inject their own
find/create-folder and ingestion callbacks, so the tree-resolution and import loop here
stay tenant-agnostic and unit-testable without a database.
"""

import json
import logging

from redis_client import get_redis

logger = logging.getLogger(__name__)

# Abuse guards (aligned with the single-upload limits).
MAX_IMPORT_FILES = 200
MAX_IMPORT_TOTAL_SIZE = 200 * 1024 * 1024  # 200 MB
IMPORT_TASK_TTL = 3600  # 1 hour, like doc_task:*


def split_relative_path(rel_path):
    """Split a browser webkitRelativePath into (dir_segments, filename).

    'Contrats/2024/bail.pdf' -> (['Contrats', '2024'], 'bail.pdf').
    Backslashes are normalised to '/', and '.'/'..'/empty segments are dropped.
    """
    norm = (rel_path or "").replace("\\", "/")
    parts = [p for p in norm.split("/") if p and p not in (".", "..")]
    if not parts:
        return [], ""
    return parts[:-1], parts[-1]


def resolve_folder_for_path(dir_segments, destination_parent_id, find_child, create_child, cache):
    """Ensure the folder chain for dir_segments exists under destination_parent_id.

    Merges into existing same-named children (find_child) and lazily creates the rest
    (create_child). Returns the leaf folder id, or destination_parent_id if dir_segments
    is empty. Results are memoised per (destination_parent_id, path-so-far) in `cache`.

    find_child(parent_id, name) -> folder_id | None
    create_child(parent_id, name) -> folder_id
    """
    parent = destination_parent_id
    path_key = ()
    for seg in dir_segments:
        path_key = path_key + (seg,)
        cache_key = (destination_parent_id, path_key)
        if cache_key in cache:
            parent = cache[cache_key]
            continue
        existing = find_child(parent, seg)
        fid = existing if existing is not None else create_child(parent, seg)
        cache[cache_key] = fid
        parent = fid
    return parent


def run_folder_import(items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status):
    """Import each (filename, rel_path, content) item under destination_parent_id.

    Skips unsupported files (is_supported), creates folders lazily (no empty folders),
    ingests supported files into their resolved folder, and reports progress via
    set_status(total, done, skipped, failed, root_folder_id, status). Per-file ingestion
    errors are counted as `failed` without aborting the batch. Returns a summary dict.
    """
    cache = {}
    total = len(items)
    done = skipped = failed = 0
    root_folder_id = None
    for filename, rel_path, content in items:
        if not is_supported(filename, content):
            skipped += 1
            set_status(total, done, skipped, failed, root_folder_id, "processing")
            continue
        dir_segments, _ = split_relative_path(rel_path)
        try:
            folder_id = resolve_folder_for_path(
                dir_segments, destination_parent_id, find_child, create_child, cache
            )
            if root_folder_id is None and dir_segments:
                root_folder_id = cache[(destination_parent_id, (dir_segments[0],))]
            ingest_file(filename, content, folder_id)
            done += 1
        except Exception as e:  # pragma: no cover - exercised via failure test
            logger.warning(f"folder import: failed on {rel_path}: {e}")
            failed += 1
        set_status(total, done, skipped, failed, root_folder_id, "processing")
    set_status(total, done, skipped, failed, root_folder_id, "completed")
    return {"total": total, "done": done, "skipped": skipped, "failed": failed, "root_folder_id": root_folder_id}


def set_import_status(task_id, total, done, skipped, failed, root_folder_id, status, error=None):
    """Write an import task status to Redis (no-op if Redis is unavailable)."""
    r = get_redis()
    if r is None:
        return
    r.setex(
        f"import_task:{task_id}",
        IMPORT_TASK_TTL,
        json.dumps(
            {
                "task_id": task_id,
                "status": status,
                "total": total,
                "done": done,
                "skipped": skipped,
                "failed": failed,
                "root_folder_id": root_folder_id,
                "error": error,
            }
        ),
    )


def get_import_status(task_id):
    """Read an import task status from Redis. Returns dict or None."""
    r = get_redis()
    if r is None:
        return None
    data = r.get(f"import_task:{task_id}")
    return json.loads(data) if data else None
```

- [ ] **Step 4 : Lancer les tests (succès) + lint**

Run: `cd backend && python -m pytest tests/test_folder_import.py -v`
Expected: 6 tests PASS.

Run: `cd backend && ruff check folder_import.py tests/test_folder_import.py && ruff format --check folder_import.py tests/test_folder_import.py`
Expected: clean (sinon `ruff format folder_import.py tests/test_folder_import.py`).

- [ ] **Step 5 : Commit**

```bash
git add backend/folder_import.py backend/tests/test_folder_import.py
git commit -m "feat(rag): shared folder-import engine (path split, lazy merge, import loop)"
```

---

## Task 2 : Endpoints d'import companion (`agent_folders.py`)

**Files:**
- Modify: `backend/routers/agent_folders.py` (imports en tête ; nouveaux endpoints + background job en fin de fichier)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire les tests DB (skip local / run CI)**

Dans `backend/tests/test_agent_folders.py`, ajouter à la fin :

```python
# -- folder import (companion) -----------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_tree_and_docs(client, auth_cookies, db_session, test_agent, monkeypatch):
    """Import recreates the directory tree and attaches docs to the right subfolder."""
    import folder_import
    from database import AgentFolder, Document

    # Run synchronously (no Redis) so the POST does the work inline.
    monkeypatch.setattr(folder_import, "get_redis", lambda: None)

    files = [
        ("files", ("a.txt", b"hello world", "text/plain")),
        ("files", ("b.txt", b"second file", "text/plain")),
        ("files", ("skip.exe", b"MZ", "application/octet-stream")),
    ]
    data = [
        ("paths", "Root/Sub/a.txt"),
        ("paths", "Root/b.txt"),
        ("paths", "Root/Sub/skip.exe"),
    ]
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders/import", files=files, data=data, cookies=auth_cookies
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] == 2 and body["skipped"] == 1

    root = db_session.query(AgentFolder).filter(
        AgentFolder.agent_id == test_agent.id, AgentFolder.name == "Root", AgentFolder.parent_id.is_(None)
    ).first()
    assert root is not None
    sub = db_session.query(AgentFolder).filter(
        AgentFolder.agent_id == test_agent.id, AgentFolder.name == "Sub", AgentFolder.parent_id == root.id
    ).first()
    assert sub is not None
    # "a.txt" lives in Sub, "b.txt" in Root
    a_doc = db_session.query(Document).filter(Document.agent_id == test_agent.id, Document.filename == "a.txt").first()
    assert a_doc.agent_folder_id == sub.id


@pytest.mark.asyncio
async def test_import_merges_into_existing_folder(client, auth_cookies, db_session, test_agent, monkeypatch):
    import folder_import
    from database import AgentFolder

    monkeypatch.setattr(folder_import, "get_redis", lambda: None)
    existing = _make_folder(db_session, test_agent, "Root")

    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders/import",
        files=[("files", ("a.txt", b"hi", "text/plain"))],
        data=[("paths", "Root/a.txt")],
        cookies=auth_cookies,
    )
    assert resp.status_code == 200
    roots = db_session.query(AgentFolder).filter(
        AgentFolder.agent_id == test_agent.id, AgentFolder.name == "Root", AgentFolder.parent_id.is_(None)
    ).all()
    assert len(roots) == 1 and roots[0].id == existing.id  # merged, not duplicated


@pytest.mark.asyncio
async def test_import_rejects_too_many_files(client, auth_cookies, test_agent, monkeypatch):
    import folder_import

    monkeypatch.setattr(folder_import, "MAX_IMPORT_FILES", 1)
    files = [
        ("files", ("a.txt", b"x", "text/plain")),
        ("files", ("b.txt", b"y", "text/plain")),
    ]
    data = [("paths", "R/a.txt"), ("paths", "R/b.txt")]
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders/import", files=files, data=data, cookies=auth_cookies
    )
    assert resp.status_code == 413
```

- [ ] **Step 2 : Lancer (skip local)**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -k "import" -v`
Expected (local) : SKIPPED (DB). Passer à l'implémentation.

- [ ] **Step 3 : Compléter les imports en tête de `agent_folders.py`**

Vérifier/ajouter en haut de `backend/routers/agent_folders.py` :

```python
from uuid import uuid4

from fastapi import BackgroundTasks, File, Form, UploadFile

from database import SessionLocal
from rag_engine import process_document_for_user
from validation import validate_file_content, validate_file_extension
import folder_import
from folder_import import (
    MAX_IMPORT_FILES,
    MAX_IMPORT_TOTAL_SIZE,
    get_import_status,
    run_folder_import,
    set_import_status,
)
```

(Certains — `HTTPException`, `Depends`, `verify_token`, `get_db`, `AgentFolder`, `_user_can_edit_agent` — sont déjà importés ; ne pas dupliquer. `import folder_import` est nécessaire en plus de l'import des noms pour que `monkeypatch.setattr(folder_import, ...)` des tests porte.)

- [ ] **Step 4 : Ajouter le background job + les endpoints en fin de `agent_folders.py`**

À la fin de `backend/routers/agent_folders.py`, ajouter :

```python
def _run_agent_folder_import(task_id, agent_id, company_id, user_id, destination_parent_id, items):
    """Background job: import a directory tree of files into this agent's folders."""
    db = SessionLocal()
    try:
        def find_child(parent_id, name):
            q = db.query(AgentFolder.id).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name)
            q = q.filter(AgentFolder.parent_id.is_(None)) if parent_id is None else q.filter(
                AgentFolder.parent_id == parent_id
            )
            row = q.first()
            return row[0] if row else None

        def create_child(parent_id, name):
            folder = AgentFolder(
                agent_id=agent_id, company_id=company_id, name=name, is_active=True, parent_id=parent_id
            )
            db.add(folder)
            db.commit()
            db.refresh(folder)
            return folder.id

        def is_supported(filename, content):
            return validate_file_extension(filename) and validate_file_content(content, filename)

        def ingest_file(filename, content, folder_id):
            process_document_for_user(
                filename, content, user_id, db, agent_id=agent_id, company_id=company_id, agent_folder_id=folder_id
            )

        def set_status(total, done, skipped, failed, root_folder_id, status):
            set_import_status(task_id, total, done, skipped, failed, root_folder_id, status)

        return run_folder_import(
            items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status
        )
    except Exception as e:
        set_import_status(task_id, 0, 0, 0, 0, None, "failed", error=str(e))
        raise
    finally:
        db.close()


@router.post("/api/agents/{agent_id}/folders/import")
async def import_agent_folder(
    agent_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    parent_id: str | None = Form(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Import a whole directory tree of documents into a companion's folders."""
    agent = _user_can_edit_agent(int(user_id), agent_id, db)
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files and paths length mismatch")
    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (max {MAX_IMPORT_FILES})")
    dest_parent_id = None
    if parent_id not in (None, ""):
        try:
            dest_parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
        _folder_or_404(dest_parent_id, agent_id, db)

    items = []
    total_size = 0
    for f, rel in zip(files, paths):
        content = await f.read()
        total_size += len(content)
        if total_size > MAX_IMPORT_TOTAL_SIZE:
            raise HTTPException(status_code=413, detail="Import too large")
        items.append((f.filename, rel, content))

    task_id = str(uuid4())
    if folder_import.get_redis() is not None:
        set_import_status(task_id, len(items), 0, 0, 0, None, "processing")
        background_tasks.add_task(
            _run_agent_folder_import, task_id, agent_id, agent.company_id, int(user_id), dest_parent_id, items
        )
        return {"import_task_id": task_id, "status": "processing"}
    # Synchronous fallback: do the work now and return the summary.
    summary = _run_agent_folder_import(task_id, agent_id, agent.company_id, int(user_id), dest_parent_id, items)
    return {**summary, "status": "completed"}


@router.get("/api/agents/{agent_id}/folders/import-status/{task_id}")
async def agent_folder_import_status(
    agent_id: int, task_id: str, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Poll the status of a folder-import task."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    status = get_import_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    return status
```

- [ ] **Step 5 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -k "import" -v`
Expected (local) : SKIPPED (DB). CI : PASS.

Run: `cd backend && ruff check routers/agent_folders.py && ruff format --check routers/agent_folders.py`
Expected: clean (sinon `ruff format routers/agent_folders.py`).

- [ ] **Step 6 : Commit**

```bash
git add backend/routers/agent_folders.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): companion folder import endpoints (multipart tree + status)"
```

---

## Task 3 : Endpoints d'import entreprise (`company_rag.py`)

**Files:**
- Modify: `backend/routers/company_rag.py` (imports ; nouveaux endpoints + background job)
- Test: `backend/tests/test_company_rag_folders.py`

- [ ] **Step 1 : Écrire les tests DB (skip local / run CI)**

Dans `backend/tests/test_company_rag_folders.py`, ajouter à la fin (la signature du helper est `_make_folder(db_session, company_id, name)` — vérifier en haut du fichier) :

```python
# -- folder import (company) -------------------------------------------------


@pytest.mark.asyncio
async def test_company_import_creates_tree_and_docs(client, admin_cookies, db_session, test_company, monkeypatch):
    import folder_import
    from database import CompanyFolder, Document

    monkeypatch.setattr(folder_import, "get_redis", lambda: None)
    resp = await client.post(
        "/api/company-rag/folders/import",
        files=[
            ("files", ("a.txt", b"hello", "text/plain")),
            ("files", ("skip.exe", b"MZ", "application/octet-stream")),
        ],
        data=[("paths", "Legal/Contracts/a.txt"), ("paths", "Legal/skip.exe")],
        cookies=admin_cookies,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["done"] == 1 and body["skipped"] == 1

    legal = db_session.query(CompanyFolder).filter(
        CompanyFolder.company_id == test_company.id, CompanyFolder.name == "Legal", CompanyFolder.parent_id.is_(None)
    ).first()
    contracts = db_session.query(CompanyFolder).filter(
        CompanyFolder.company_id == test_company.id, CompanyFolder.name == "Contracts", CompanyFolder.parent_id == legal.id
    ).first()
    assert contracts is not None
    a_doc = db_session.query(Document).filter(
        Document.company_id == test_company.id, Document.filename == "a.txt"
    ).first()
    assert a_doc.folder_id == contracts.id and a_doc.is_company_rag is True


@pytest.mark.asyncio
async def test_company_import_requires_admin(client, member_cookies, monkeypatch):
    import folder_import

    monkeypatch.setattr(folder_import, "get_redis", lambda: None)
    resp = await client.post(
        "/api/company-rag/folders/import",
        files=[("files", ("a.txt", b"hi", "text/plain"))],
        data=[("paths", "R/a.txt")],
        cookies=member_cookies,
    )
    assert resp.status_code == 403
```

- [ ] **Step 2 : Lancer (skip local)**

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -k "import" -v`
Expected (local) : SKIPPED (DB). Passer à l'implémentation.

- [ ] **Step 3 : Compléter les imports en tête de `company_rag.py`**

Vérifier/ajouter en haut de `backend/routers/company_rag.py` :

```python
from uuid import uuid4

from fastapi import BackgroundTasks, File, Form, UploadFile

from database import SessionLocal
from rag_engine import process_document_for_user
from validation import validate_file_content, validate_file_extension
import folder_import
from folder_import import (
    MAX_IMPORT_FILES,
    MAX_IMPORT_TOTAL_SIZE,
    get_import_status,
    run_folder_import,
    set_import_status,
)
```

(`require_role`, `_require_company_id`, `_folder_or_404`, `CompanyFolder`, `verify_token`, `get_db`, `HTTPException`, `Depends` sont déjà importés — ne pas dupliquer.)

- [ ] **Step 4 : Ajouter le background job + les endpoints**

À la fin de `backend/routers/company_rag.py`, ajouter :

```python
def _run_company_folder_import(task_id, company_id, user_id, destination_parent_id, items):
    """Background job: import a directory tree of files into the company RAG folders."""
    db = SessionLocal()
    try:
        def find_child(parent_id, name):
            q = db.query(CompanyFolder.id).filter(
                CompanyFolder.company_id == company_id, CompanyFolder.name == name
            )
            q = q.filter(CompanyFolder.parent_id.is_(None)) if parent_id is None else q.filter(
                CompanyFolder.parent_id == parent_id
            )
            row = q.first()
            return row[0] if row else None

        def create_child(parent_id, name):
            folder = CompanyFolder(company_id=company_id, name=name, parent_id=parent_id)
            db.add(folder)
            db.commit()
            db.refresh(folder)
            return folder.id

        def is_supported(filename, content):
            return validate_file_extension(filename) and validate_file_content(content, filename)

        def ingest_file(filename, content, folder_id):
            process_document_for_user(
                filename, content, user_id, db, company_id=company_id, is_company_rag=True, folder_id=folder_id
            )

        def set_status(total, done, skipped, failed, root_folder_id, status):
            set_import_status(task_id, total, done, skipped, failed, root_folder_id, status)

        return run_folder_import(
            items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status
        )
    except Exception as e:
        set_import_status(task_id, 0, 0, 0, 0, None, "failed", error=str(e))
        raise
    finally:
        db.close()


@router.post("/api/company-rag/folders/import")
async def import_company_folder(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    parent_id: str | None = Form(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Import a whole directory tree of documents into the company RAG folders (admin)."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files and paths length mismatch")
    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (max {MAX_IMPORT_FILES})")
    dest_parent_id = None
    if parent_id not in (None, ""):
        try:
            dest_parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
        _folder_or_404(dest_parent_id, company_id, db)

    items = []
    total_size = 0
    for f, rel in zip(files, paths):
        content = await f.read()
        total_size += len(content)
        if total_size > MAX_IMPORT_TOTAL_SIZE:
            raise HTTPException(status_code=413, detail="Import too large")
        items.append((f.filename, rel, content))

    task_id = str(uuid4())
    if folder_import.get_redis() is not None:
        set_import_status(task_id, len(items), 0, 0, 0, None, "processing")
        background_tasks.add_task(
            _run_company_folder_import, task_id, company_id, int(user_id), dest_parent_id, items
        )
        return {"import_task_id": task_id, "status": "processing"}
    summary = _run_company_folder_import(task_id, company_id, int(user_id), dest_parent_id, items)
    return {**summary, "status": "completed"}


@router.get("/api/company-rag/folders/import-status/{task_id}")
async def company_folder_import_status(
    task_id: str, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Poll the status of a company folder-import task."""
    require_role(int(user_id), db, "member")
    status = get_import_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    return status
```

Note : vérifier le nom exact du helper company id (`_require_company_id`) en haut de `company_rag.py` et l'aligner si différent.

- [ ] **Step 5 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -k "import" -v`
Expected (local) : SKIPPED (DB). CI : PASS.

Run: `cd backend && ruff check routers/company_rag.py && ruff format --check routers/company_rag.py`
Expected: clean (sinon `ruff format routers/company_rag.py`).

- [ ] **Step 6 : Commit**

```bash
git add backend/routers/company_rag.py backend/tests/test_company_rag_folders.py
git commit -m "feat(rag): company folder import endpoints (multipart tree + status)"
```

---

## Task 4 : Frontend import companion (`index.js`)

**Files:**
- Modify: `frontend/pages/index.js`
- Modify: `frontend/public/locales/fr/agents.json`, `frontend/public/locales/en/agents.json`

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `frontend/public/locales/fr/agents.json`, sous l'objet `"buttons"` (ou à côté de `clickToChoose`), ajouter :

```json
    "importFolder": "Importer un dossier",
    "importingFolder": "Import en cours…",
    "importDone": "{{done}} importés, {{skipped}} ignorés",
    "importNoSupported": "Aucun fichier supporté dans ce dossier."
```

Dans `frontend/public/locales/en/agents.json`, mêmes clés :

```json
    "importFolder": "Import a folder",
    "importingFolder": "Importing…",
    "importDone": "{{done}} imported, {{skipped}} skipped",
    "importNoSupported": "No supported files in this folder."
```

(Repérer le bon objet parent au Step suivant en lisant le fichier ; placer les clés là où `t('agents:buttons.clickToChoose')` est défini.)

- [ ] **Step 2 : Lire `index.js` et repérer les ancrages**

Lire la zone d'upload de `frontend/pages/index.js` autour des lignes 591-652 (`pollUploadStatus`, `uploadDocument`) et le JSX du drop zone (~1305-1377). Confirmer : `uploadFolderId` (state), `currentAgent`, `setAgentDocuments`, `loadAgentFolders`, `useRef` est-il importé de React. Noter l'import React en tête.

- [ ] **Step 3 : Ajouter l'état + le ref + le handler d'import**

S'assurer que `useRef` est importé : `import { useState, useEffect, useRef } from 'react';` (compléter si besoin).

Près de `const [uploadFolderId, setUploadFolderId] = useState(null);`, ajouter :

```javascript
  const folderImportRef = useRef(null);
  const [importingFolder, setImportingFolder] = useState(false);
  const [importProgress, setImportProgress] = useState(null); // { total, done, skipped, failed }

  useEffect(() => {
    if (folderImportRef.current) {
      folderImportRef.current.setAttribute('webkitdirectory', '');
      folderImportRef.current.setAttribute('directory', '');
    }
  }, []);
```

Puis, à côté de `uploadDocument`, ajouter le handler :

```javascript
  const ALLOWED_IMPORT_EXT = ['pdf', 'txt', 'docx', 'doc', 'json'];

  const pollImportStatus = async (taskId, agentId) => {
    for (let i = 0; i < 200; i++) {
      await new Promise(r => setTimeout(r, 1500));
      try {
        const res = await api.get(`/api/agents/${agentId}/folders/import-status/${taskId}`);
        const s = res.data;
        setImportProgress({ total: s.total, done: s.done, skipped: s.skipped, failed: s.failed });
        if (s.status === 'completed') {
          toast.success(t('agents:buttons.importDone', { done: s.done, skipped: s.skipped }));
          const docs = await api.get(`/user/documents?agent_id=${agentId}`);
          setAgentDocuments(docs.data.documents || []);
          loadAgentFolders(agentId);
          setTimeout(() => setImportProgress(null), 2000);
          return;
        }
        if (s.status === 'failed') {
          toast.error(s.error || t('agents:toast.documentAddError'));
          setImportProgress(null);
          return;
        }
      } catch { /* keep polling */ }
    }
    setImportProgress(null);
    toast.error(t('agents:toast.documentAddError'));
  };

  const handleFolderImport = async (e) => {
    const all = Array.from(e.target.files || []);
    e.target.value = '';
    if (!all.length || !currentAgent) return;
    const fd = new FormData();
    let count = 0;
    for (const file of all) {
      const rel = file.webkitRelativePath || file.name;
      const ext = rel.split('.').pop().toLowerCase();
      if (!ALLOWED_IMPORT_EXT.includes(ext)) continue;
      fd.append('files', file);
      fd.append('paths', rel);
      count++;
    }
    if (!count) { toast.error(t('agents:buttons.importNoSupported')); return; }
    if (uploadFolderId) fd.append('parent_id', String(uploadFolderId));
    try {
      setImportingFolder(true);
      setImportProgress({ total: count, done: 0, skipped: 0, failed: 0 });
      const res = await api.post(`/api/agents/${currentAgent.id}/folders/import`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.import_task_id) {
        await pollImportStatus(res.data.import_task_id, currentAgent.id);
      } else {
        toast.success(t('agents:buttons.importDone', { done: res.data.done, skipped: res.data.skipped }));
        const docs = await api.get(`/user/documents?agent_id=${currentAgent.id}`);
        setAgentDocuments(docs.data.documents || []);
        loadAgentFolders(currentAgent.id);
        setImportProgress(null);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('agents:toast.documentAddError'));
      setImportProgress(null);
    } finally {
      setImportingFolder(false);
    }
  };
```

- [ ] **Step 4 : Ajouter le bouton + la barre de progression dans le JSX du drop zone**

À côté du `<label>` d'upload de fichier (~1355-1359), ajouter un second `<label>` pour l'import de dossier :

```jsx
              <label className="cursor-pointer inline-flex items-center space-x-2 px-4 py-2 bg-white border border-purple-300 text-purple-700 rounded-sm hover:bg-purple-50 transition-all font-medium text-sm ml-2">
                <input ref={folderImportRef} type="file" multiple className="hidden" disabled={importingFolder}
                  onChange={handleFolderImport} />
                <Upload className="w-4 h-4" />
                <span>{importingFolder ? t('agents:buttons.importingFolder') : t('agents:buttons.importFolder')}</span>
              </label>
```

Et, sous la zone d'upload, afficher la progression d'import si active :

```jsx
              {importProgress && (
                <div className="mt-3 text-xs text-gray-600">
                  <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div className="h-full bg-purple-600 transition-all"
                      style={{ width: `${importProgress.total ? Math.round(((importProgress.done + importProgress.skipped + importProgress.failed) / importProgress.total) * 100) : 0}%` }} />
                  </div>
                  <span>{importProgress.done + importProgress.skipped + importProgress.failed}/{importProgress.total} · {t('agents:buttons.importDone', { done: importProgress.done, skipped: importProgress.skipped })}</span>
                </div>
              )}
```

(`Upload` est déjà importé de lucide-react dans `index.js`. Vérifier et compléter si absent.)

- [ ] **Step 5 : Lint + build**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 6 : Commit**

```bash
git add frontend/pages/index.js frontend/public/locales/fr/agents.json frontend/public/locales/en/agents.json
git commit -m "feat(rag): import a folder into a companion (webkitdirectory + progress)"
```

---

## Task 5 : Frontend import entreprise (`organization.js`)

**Files:**
- Modify: `frontend/pages/organization.js`
- Modify: `frontend/public/locales/fr/organization.json`, `frontend/public/locales/en/organization.json`

- [ ] **Step 1 : Ajouter les clés i18n**

Dans `frontend/public/locales/fr/organization.json`, sous `"companyRag"`, ajouter :

```json
    "importFolder": "Importer un dossier",
    "importingFolder": "Import en cours…",
    "importDone": "{{done}} importés, {{skipped}} ignorés",
    "importNoSupported": "Aucun fichier supporté dans ce dossier."
```

Dans `frontend/public/locales/en/organization.json`, sous `"companyRag"` :

```json
    "importFolder": "Import a folder",
    "importingFolder": "Importing…",
    "importDone": "{{done}} imported, {{skipped}} skipped",
    "importNoSupported": "No supported files in this folder."
```

- [ ] **Step 2 : Ajouter l'état + le ref + le handler d'import**

S'assurer que `useRef` est importé en tête (`import { useState, useEffect, useRef } from 'react';`).

Près de `const [companyDocUploading, setCompanyDocUploading] = useState(false);`, ajouter :

```javascript
  const folderImportRef = useRef(null);
  const [importingFolder, setImportingFolder] = useState(false);
  const [importProgress, setImportProgress] = useState(null);

  useEffect(() => {
    if (folderImportRef.current) {
      folderImportRef.current.setAttribute('webkitdirectory', '');
      folderImportRef.current.setAttribute('directory', '');
    }
  }, []);
```

Près de `handleCompanyDocUpload`, ajouter :

```javascript
  const ALLOWED_IMPORT_EXT = ['pdf', 'txt', 'docx', 'doc', 'json'];

  const pollCompanyImport = async (taskId) => {
    for (let i = 0; i < 200; i++) {
      await new Promise(r => setTimeout(r, 1500));
      try {
        const res = await api.get(`/api/company-rag/folders/import-status/${taskId}`);
        const s = res.data;
        setImportProgress({ total: s.total, done: s.done, skipped: s.skipped, failed: s.failed });
        if (s.status === 'completed') {
          toast.success(t('organization:companyRag.importDone', { done: s.done, skipped: s.skipped }));
          await loadCompanyDocs();
          await loadFolders();
          setTimeout(() => setImportProgress(null), 2000);
          return;
        }
        if (s.status === 'failed') {
          toast.error(s.error || t('organization:companyRag.uploadError'));
          setImportProgress(null);
          return;
        }
      } catch { /* keep polling */ }
    }
    setImportProgress(null);
    toast.error(t('organization:companyRag.uploadError'));
  };

  const handleCompanyFolderImport = async (e) => {
    const all = Array.from(e.target.files || []);
    e.target.value = '';
    if (!all.length) return;
    const fd = new FormData();
    let count = 0;
    for (const file of all) {
      const rel = file.webkitRelativePath || file.name;
      const ext = rel.split('.').pop().toLowerCase();
      if (!ALLOWED_IMPORT_EXT.includes(ext)) continue;
      fd.append('files', file);
      fd.append('paths', rel);
      count++;
    }
    if (!count) { toast.error(t('organization:companyRag.importNoSupported')); return; }
    if (selectedFolderId) fd.append('parent_id', String(selectedFolderId));
    try {
      setImportingFolder(true);
      setImportProgress({ total: count, done: 0, skipped: 0, failed: 0 });
      const res = await api.post('/api/company-rag/folders/import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.import_task_id) {
        await pollCompanyImport(res.data.import_task_id);
      } else {
        toast.success(t('organization:companyRag.importDone', { done: res.data.done, skipped: res.data.skipped }));
        await loadCompanyDocs();
        await loadFolders();
        setImportProgress(null);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || t('organization:companyRag.uploadError'));
      setImportProgress(null);
    } finally {
      setImportingFolder(false);
    }
  };
```

- [ ] **Step 3 : Ajouter le bouton + la barre dans le JSX**

À côté du `<label>` d'upload de fichier (~856-862, le bouton « Ajouter un document »), ajouter un second `<label>` :

```jsx
                        <label className={`flex items-center space-x-2 px-4 py-2 bg-white border border-teal-300 text-teal-700 text-sm font-semibold rounded-button hover:bg-teal-50 transition-all cursor-pointer ${importingFolder ? 'opacity-60 pointer-events-none' : ''}`}>
                          {importingFolder ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                          <span>{importingFolder ? t('organization:companyRag.importingFolder') : t('organization:companyRag.importFolder')}</span>
                          <input ref={folderImportRef} type="file" multiple className="hidden" onChange={handleCompanyFolderImport} />
                        </label>
```

Et, sous la barre de dossiers (après le `</div>` du `space-y-2 mb-4`), afficher la progression si active :

```jsx
                    {importProgress && (
                      <div className="mb-4 text-xs text-gray-600">
                        <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                          <div className="h-full bg-teal-600 transition-all"
                            style={{ width: `${importProgress.total ? Math.round(((importProgress.done + importProgress.skipped + importProgress.failed) / importProgress.total) * 100) : 0}%` }} />
                        </div>
                        <span>{importProgress.done + importProgress.skipped + importProgress.failed}/{importProgress.total} · {t('organization:companyRag.importDone', { done: importProgress.done, skipped: importProgress.skipped })}</span>
                      </div>
                    )}
```

(`Upload` et `Loader2` sont déjà importés de lucide-react dans `organization.js`.)

- [ ] **Step 4 : Lint + build**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 5 : Commit**

```bash
git add frontend/pages/organization.js frontend/public/locales/fr/organization.json frontend/public/locales/en/organization.json
git commit -m "feat(rag): import a folder into company RAG (webkitdirectory + progress)"
```

---

## Self-Review (effectué par l'auteur du plan)

**Couverture de la spec (Phase 2) :**
- §2.1 Frontend `<input webkitdirectory>` + `files[]`/`paths[]` + `parent_id` + poll + progression/récap → Tasks 4 (companion) & 5 (entreprise) ✓ (déviation documentée : companion sur `index.js`, pas `sources/[agentId].js` qui est URL-only).
- §2.2 Endpoints `POST …/folders/import` + `GET …/import-status/{id}` (companion perm edit / entreprise admin) → Tasks 2 & 3 ✓.
- §2.3 Job d'arrière-plan, logique partagée `folder_import.py`, `resolve_folder_for_path` (fusion + création paresseuse + cache par chemin), `root_folder_id`, repli synchrone si Redis absent → Tasks 1, 2, 3 ✓.
- §2.4 Réutilisation des validateurs par fichier, caps nombre/taille (413), permissions → Tasks 1 (constantes), 2 & 3 (checks) ✓.
- §2.5 Tests : purs sans DB (Task 1), DB/CI import companion+entreprise (Tasks 2 & 3) ; récursivité de récupération déjà couverte en Phase 1 → ✓.

**Placeholders :** aucun TODO/TBD ; code fourni à chaque étape. Les Tasks 4-5 demandent une lecture préalable des pages pour placer les clés i18n et le JSX au bon endroit — ancrages (numéros de ligne, noms d'état/handler) fournis ; intentionnel, pas un placeholder de logique.

**Cohérence des types/noms :** `split_relative_path(rel_path) -> (list, str)`, `resolve_folder_for_path(dir_segments, destination_parent_id, find_child, create_child, cache) -> int`, `run_folder_import(items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status) -> dict`, `set_import_status(task_id, total, done, skipped, failed, root_folder_id, status, error=None)`, `get_import_status(task_id) -> dict|None`. Namespace Redis `import_task:{id}`. Réponse POST async `{import_task_id, status}` ; sync `{total, done, skipped, failed, root_folder_id, status}`. Côté frontend, `import_task_id` lu pour décider poll vs récap immédiat — cohérent avec le backend.

**Points d'attention :**
- `import folder_import` (le module) EN PLUS de l'import des noms, sinon `monkeypatch.setattr(folder_import, "get_redis", ...)` / `MAX_IMPORT_FILES` des tests ne portent pas sur les références utilisées par le routeur → le routeur doit appeler `folder_import.get_redis()` (qualifié) pour que le monkeypatch synchrone fonctionne dans les tests DB.
- `_require_company_id` : vérifier le nom exact en tête de `company_rag.py` (l'exploration l'a relevé ainsi) et aligner.
- `webkitdirectory` posé via `ref` + `setAttribute` (et non en prop JSX) pour éviter les warnings React.
- Mémoire : l'import lit tous les fichiers en RAM avant le job (cap 200 MB) ; acceptable sur Cloud Run 4Gi.
- Tests DB skippent en local ; validation réelle (création d'arbre, fusion, compteurs) en CI.
```
