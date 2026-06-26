# RAG Sous-dossiers (Phase 1) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une hiérarchie de dossiers (sous-dossiers) aux deux systèmes RAG (entreprise `CompanyFolder` et companion `AgentFolder`), avec une sémantique récursive : l'état actif/inactif (companion) et la sélection (entreprise) d'un dossier s'appliquent à tout son sous-arbre.

**Architecture:** Une colonne `parent_id` (self-FK) sur chaque table de dossiers ; l'unicité de nom passe au niveau des frères (`(tenant, parent_id, name)`) via une DDL idempotente au démarrage ; les endpoints CRUD acceptent/retournent `parent_id` ; la récupération RAG étend les ensembles de dossiers à leurs descendants via un helper d'arbre pur ; les UI affichent un arbre repliable.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Next.js (Pages Router), React, Tailwind, pytest. Les tests DB-backed skippent en local et tournent en CI (Postgres+pgvector).

---

## Notes transverses

- **Migrations** : nouvelles colonnes via `ensure_columns()` (`backend/database.py`, `ADD COLUMN IF NOT EXISTS`). Les **contraintes** ne sont pas gérées par `create_all`/`ensure_columns` → une nouvelle fonction idempotente `ensure_folder_hierarchy_constraints()` migre les contraintes d'unicité, appelée au démarrage dans `backend/main.py` sous `migration_lock()`.
- **Spec** : `docs/superpowers/specs/2026-06-26-rag-subfolders-and-folder-import-design.md` (Phase 1).
- **Lint** : `ruff check .` ET `ruff format --check .` (la CI lance les deux). Lancer `ruff format <fichiers>` avant de committer du backend.
- **Tests DB** : skippent en local (pas de Postgres), tournent en CI. Fixtures : `client`, `db_session`, `test_user`, `auth_cookies`, `test_agent`, `test_company`, `test_admin_user`, `admin_cookies`, `member_cookies`. Helper local `_give_company` dans `tests/test_agent_folders.py` pour donner une company à test_agent/test_user.
- **Pré-check applicatif = garde-fou principal** d'unicité (la contrainte DB est best-effort, surtout pour `parent_id IS NULL` que Postgres considère distinct).

## Structure des fichiers

| Fichier | Responsabilité | Création/Modif |
|---------|----------------|----------------|
| `backend/database.py` | `parent_id` sur les 2 modèles ; `ensure_columns` ; `ensure_folder_hierarchy_constraints()` | Modif |
| `backend/main.py` | Appel de `ensure_folder_hierarchy_constraints()` au démarrage | Modif |
| `backend/rag_engine.py` | `_descendant_folder_ids` (helper arbre pur) ; `_inactive_agent_folder_ids` récursif ; expansion `company_rag_folder_ids` | Modif |
| `backend/routers/agent_folders.py` | create/list/rename/delete avec `parent_id` (companion) | Modif |
| `backend/routers/company_rag.py` | create/list/rename/delete avec `parent_id` (entreprise) | Modif |
| `backend/tests/test_agent_folders.py` | Tests hiérarchie companion + helper arbre | Modif |
| `backend/tests/test_company_rag_folders.py` | Tests hiérarchie entreprise | Modif |
| `frontend/pages/sources/[agentId].js` | Arbre repliable + « + sous-dossier » (companion) | Modif |
| `frontend/pages/organization.js` | Arbre repliable + « + sous-dossier » (entreprise) | Modif |
| `frontend/pages/agents.js` | Arbre de cases à cocher (sélection entreprise) | Modif |

---

## Task 1 : Schéma — `parent_id` + migration des contraintes d'unicité

**Files:**
- Modify: `backend/database.py` (`CompanyFolder` ~576-583 ; `AgentFolder` ~586-595 ; `ensure_columns` ~1074 ; nouvelle fonction)
- Modify: `backend/main.py` (startup ~432-445)

- [ ] **Step 1 : `CompanyFolder` — colonne `parent_id` + unicité au niveau frères**

Dans `backend/database.py`, remplacer la classe `CompanyFolder` (lignes 576-583) par :

```python
class CompanyFolder(Base):
    __tablename__ = "company_folders"
    __table_args__ = (UniqueConstraint("company_id", "parent_id", "name", name="uq_company_folder_parent_name"),)

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    parent_id = Column(
        Integer, ForeignKey("company_folders.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL = top-level folder
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 2 : `AgentFolder` — colonne `parent_id` + unicité au niveau frères**

Dans `backend/database.py`, remplacer la classe `AgentFolder` (lignes 586-595) par :

```python
class AgentFolder(Base):
    __tablename__ = "agent_folders"
    __table_args__ = (UniqueConstraint("agent_id", "parent_id", "name", name="uq_agent_folder_parent_name"),)

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    parent_id = Column(
        Integer, ForeignKey("agent_folders.id", ondelete="CASCADE"), nullable=True, index=True
    )  # NULL = top-level folder
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 3 : `ensure_columns()` — ajouter les colonnes `parent_id`**

Dans `backend/database.py`, dans la liste `migrations` de `ensure_columns()` (~ligne 1074), à la suite des autres entrées, ajouter :

```python
        # RAG folder hierarchy (subfolders)
        ("company_folders", "parent_id", "INTEGER REFERENCES company_folders(id) ON DELETE CASCADE"),
        ("agent_folders", "parent_id", "INTEGER REFERENCES agent_folders(id) ON DELETE CASCADE"),
```

- [ ] **Step 4 : Fonction idempotente de migration des contraintes d'unicité**

Dans `backend/database.py`, juste après la fonction `ensure_columns()` (avant `TENANT_TABLES`), ajouter :

```python
def ensure_folder_hierarchy_constraints():
    """Idempotently migrate folder uniqueness from (tenant, name) to (tenant, parent_id, name).

    create_all / ensure_columns do not alter existing constraints, so on an existing DB the
    old company-wide / agent-wide unique constraints would block same-named subfolders under
    different parents. Drop the old constraints and add the parent-aware ones. Safe to run on
    every startup: the old DROP IF EXISTS no-ops once gone, and the ADD is skipped if present.
    """
    statements = [
        "ALTER TABLE company_folders DROP CONSTRAINT IF EXISTS uq_company_folder_name",
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_company_folder_parent_name') THEN
                ALTER TABLE company_folders
                    ADD CONSTRAINT uq_company_folder_parent_name UNIQUE (company_id, parent_id, name);
            END IF;
        END $$;
        """,
        "ALTER TABLE agent_folders DROP CONSTRAINT IF EXISTS uq_agent_folder_name",
        """
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_agent_folder_parent_name') THEN
                ALTER TABLE agent_folders
                    ADD CONSTRAINT uq_agent_folder_parent_name UNIQUE (agent_id, parent_id, name);
            END IF;
        END $$;
        """,
    ]
    with engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as e:  # pragma: no cover - logged, non-fatal per-statement
                logger.warning(f"ensure_folder_hierarchy_constraints: statement skipped: {e}")
```

Note : `engine`, `text`, et `logger` sont déjà importés/définis en haut de `database.py` (utilisés par `ensure_columns` / `ensure_rls_policies`). Vérifier la présence de `logger` ; s'il n'existe pas dans ce module, utiliser le logger du module (chercher comment `ensure_columns` logge) et s'aligner.

- [ ] **Step 5 : Appeler la fonction au démarrage**

Dans `backend/main.py`, dans `startup_event`, juste après l'appel `ensure_columns()` (~ligne 433-434), ajouter :

```python
            ensure_folder_hierarchy_constraints()
            logger.info("ensure_folder_hierarchy_constraints done (%s)", _elapsed())
```

Et ajouter `ensure_folder_hierarchy_constraints` à l'import depuis `database` en haut de `main.py` (là où `ensure_columns`, `ensure_company_rag_default_folders`, etc. sont importés ~ligne 34).

- [ ] **Step 6 : Vérifier l'import + lint**

Run: `cd backend && python -c "import os; os.environ.setdefault('DATABASE_URL','postgresql://t:t@localhost/t'); [os.environ.setdefault(k,'x') for k in ['JWT_SECRET_KEY','OPENAI_API_KEY','MISTRAL_API_KEY','GEMINI_API_KEY']]; from database import CompanyFolder, AgentFolder, ensure_folder_hierarchy_constraints; print(hasattr(CompanyFolder,'parent_id'), hasattr(AgentFolder,'parent_id'))"`
Expected: `True True`

Run: `cd backend && ruff check database.py main.py && ruff format --check database.py main.py`
Expected: aucun warning ; "already formatted" (sinon lancer `ruff format database.py main.py`).

- [ ] **Step 7 : Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat(rag): folder parent_id column + sibling-name uniqueness migration"
```

---

## Task 2 : Helper d'arbre + récupération récursive (companion + entreprise)

**Files:**
- Modify: `backend/rag_engine.py` (`_inactive_agent_folder_ids` ~839-848 ; branche `elif agent_id:` ~933-951 ; nouveau helper)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire les tests unitaires purs du helper d'arbre (qui échouent)**

Dans `backend/tests/test_agent_folders.py`, ajouter à la fin :

```python
# -- folder tree expansion (pure, runs locally) ------------------------------


def test_descendant_folder_ids_basic():
    from rag_engine import _descendant_folder_ids

    # tree: 1 -> 2 -> 4, 1 -> 3
    pairs = [(1, None), (2, 1), (3, 1), (4, 2), (5, None)]
    assert _descendant_folder_ids([1], pairs) == {1, 2, 3, 4}
    assert _descendant_folder_ids([2], pairs) == {2, 4}
    assert _descendant_folder_ids([5], pairs) == {5}
    assert _descendant_folder_ids([], pairs) == set()


def test_descendant_folder_ids_cycle_safe():
    from rag_engine import _descendant_folder_ids

    # defensive: a malformed cycle must not loop forever
    pairs = [(1, 2), (2, 1)]
    assert _descendant_folder_ids([1], pairs) == {1, 2}
```

- [ ] **Step 2 : Lancer les tests (échec attendu)**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -k descendant_folder_ids -v`
Expected: FAIL `ImportError: cannot import name '_descendant_folder_ids'` (ces tests RUN en local — pas de DB).

- [ ] **Step 3 : Ajouter le helper d'arbre pur**

Dans `backend/rag_engine.py`, juste avant la fonction `_inactive_agent_folder_ids` (ligne ~839), ajouter :

```python
def _descendant_folder_ids(start_ids, pairs) -> set:
    """Return start_ids plus all their descendants.

    pairs: iterable of (folder_id, parent_id). Cycle-safe (a malformed parent cycle
    cannot loop forever because already-visited ids are skipped).
    """
    children = {}
    for fid, pid in pairs:
        children.setdefault(pid, []).append(fid)
    result = set()
    stack = list(start_ids)
    while stack:
        cur = stack.pop()
        if cur in result:
            continue
        result.add(cur)
        stack.extend(children.get(cur, []))
    return result
```

- [ ] **Step 4 : Rendre `_inactive_agent_folder_ids` récursif**

Dans `backend/rag_engine.py`, remplacer la fonction `_inactive_agent_folder_ids` (lignes 839-848) par :

```python
def _inactive_agent_folder_ids(agent_id: int, db: Session) -> list:
    """Return the ids of this agent's inactive folders AND all their descendants.

    Documents in these folders (or any subfolder of an inactive folder) are excluded
    from RAG retrieval; documents with agent_folder_id IS NULL (no folder) are always
    included. Subtree semantics: deactivating a parent excludes its whole subtree.
    """
    from database import AgentFolder

    rows = db.query(AgentFolder.id, AgentFolder.parent_id, AgentFolder.is_active).filter(
        AgentFolder.agent_id == agent_id
    ).all()
    inactive_roots = [r[0] for r in rows if not r[2]]
    if not inactive_roots:
        return []
    pairs = [(r[0], r[1]) for r in rows]
    return list(_descendant_folder_ids(inactive_roots, pairs))
```

- [ ] **Step 5 : Étendre la sélection entreprise à son sous-arbre**

Dans `backend/rag_engine.py`, dans la branche `elif agent_id:` (lignes 945-948), remplacer :

```python
            if include_company_rag:
                company_scope = Document.is_company_rag.is_(True)
                if company_rag_folder_ids:
                    company_scope = and_(company_scope, Document.folder_id.in_(company_rag_folder_ids))
                query = query.filter(or_(agent_scope, company_scope))
```

par :

```python
            if include_company_rag:
                company_scope = Document.is_company_rag.is_(True)
                if company_rag_folder_ids:
                    from database import CompanyFolder

                    crows = db.query(CompanyFolder.id, CompanyFolder.parent_id).filter(
                        CompanyFolder.company_id == company_id
                    ).all()
                    expanded = _descendant_folder_ids(company_rag_folder_ids, [(r[0], r[1]) for r in crows])
                    company_scope = and_(company_scope, Document.folder_id.in_(expanded))
                query = query.filter(or_(agent_scope, company_scope))
```

(`company_id` est déjà résolu plus haut dans la fonction — c'est la borne tenant.)

- [ ] **Step 6 : Tests DB de récursivité (companion + entreprise)**

Dans `backend/tests/test_agent_folders.py`, ajouter à la fin :

```python
@pytest.mark.asyncio
async def test_retrieval_excludes_inactive_parent_subtree(db_session, test_user, test_agent):
    """An inactive PARENT folder excludes documents sitting in its child subfolder."""
    from rag_engine import search_similar_texts_for_user
    from database import DocumentChunk
    from tests.factories import AgentFolderFactory

    _give_company(db_session, test_user, test_agent)

    parent = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="Parent", is_active=False
    )
    db_session.add(parent)
    db_session.flush()
    child = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="Child", is_active=True, parent_id=parent.id
    )
    db_session.add(child)
    db_session.flush()

    vec = [1.0] + [0.0] * 1023
    doc = _make_agent_doc(db_session, test_user.id, test_agent, agent_folder_id=child.id)
    doc.filename = "in_child.txt"
    db_session.add(
        DocumentChunk(
            document_id=doc.id,
            company_id=test_agent.company_id,
            chunk_text="content",
            embedding_vec=vec,
            chunk_index=0,
        )
    )
    db_session.flush()

    results = search_similar_texts_for_user(
        vec, test_user.id, db_session, top_k=10, agent_id=test_agent.id, company_id=test_agent.company_id
    )
    assert all(r["document_name"] != "in_child.txt" for r in results)
```

- [ ] **Step 7 : Lancer + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -k "descendant_folder_ids or excludes_inactive_parent" -v`
Expected (local) : les 2 tests `descendant_folder_ids` PASS ; `test_retrieval_excludes_inactive_parent_subtree` SKIPPED (pas de Postgres). En CI : tous PASS.

Run: `cd backend && ruff check rag_engine.py tests/test_agent_folders.py && ruff format --check rag_engine.py tests/test_agent_folders.py`
Expected: clean (sinon `ruff format ...`).

- [ ] **Step 8 : Commit**

```bash
git add backend/rag_engine.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): recursive subtree semantics in retrieval (inactive + company selection)"
```

---

## Task 3 : CRUD companion avec `parent_id`

**Files:**
- Modify: `backend/routers/agent_folders.py` (create ~59-78 ; list ~33-56 ; rename ~93-106 ; delete ~116-137 ; helper)
- Test: `backend/tests/test_agent_folders.py`

- [ ] **Step 1 : Écrire les tests (qui échouent)**

Dans `backend/tests/test_agent_folders.py`, ajouter à la fin :

```python
# -- subfolders (companion) --------------------------------------------------


@pytest.mark.asyncio
async def test_create_subfolder(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "Parent")
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders",
        json={"name": "Child", "parent_id": parent.id},
        cookies=auth_cookies,
    )
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == parent.id


@pytest.mark.asyncio
async def test_create_subfolder_bad_parent_404(client, auth_cookies, test_agent):
    resp = await client.post(
        f"/api/agents/{test_agent.id}/folders",
        json={"name": "Child", "parent_id": 999999},
        cookies=auth_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_same_name_under_different_parents_ok(client, auth_cookies, db_session, test_agent):
    p1 = _make_folder(db_session, test_agent, "P1")
    p2 = _make_folder(db_session, test_agent, "P2")
    r1 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "2024", "parent_id": p1.id}, cookies=auth_cookies
    )
    r2 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "2024", "parent_id": p2.id}, cookies=auth_cookies
    )
    assert r1.status_code == 200 and r2.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_name_same_parent_409(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "Parent2")
    await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "Dup", "parent_id": parent.id}, cookies=auth_cookies
    )
    r2 = await client.post(
        f"/api/agents/{test_agent.id}/folders", json={"name": "Dup", "parent_id": parent.id}, cookies=auth_cookies
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_returns_parent_id(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "ListParent")
    resp = await client.get(f"/api/agents/{test_agent.id}/folders", cookies=auth_cookies)
    assert resp.status_code == 200
    match = next(f for f in resp.json()["folders"] if f["id"] == parent.id)
    assert "parent_id" in match and match["parent_id"] is None


@pytest.mark.asyncio
async def test_delete_folder_with_subfolder_409(client, auth_cookies, db_session, test_agent):
    parent = _make_folder(db_session, test_agent, "HasChild")
    from tests.factories import AgentFolderFactory

    child = AgentFolderFactory.build(
        agent_id=test_agent.id, company_id=test_agent.company_id, name="C", parent_id=parent.id
    )
    db_session.add(child)
    db_session.flush()
    resp = await client.delete(f"/api/agents/{test_agent.id}/folders/{parent.id}", cookies=auth_cookies)
    assert resp.status_code == 409
```

- [ ] **Step 2 : Lancer (skip local / fail CI)**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -k "subfolder or parent or different_parents or same_parent_409 or with_subfolder" -v`
Expected (local) : SKIPPED (DB). Passer à l'implémentation.

- [ ] **Step 3 : `create_agent_folder` — accepter `parent_id`, unicité par parent**

Dans `backend/routers/agent_folders.py`, remplacer le corps de `create_agent_folder` (lignes 63-78) par :

```python
    """Create a folder for a companion (edit permission required)."""
    agent = _user_can_edit_agent(int(user_id), agent_id, db)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if len(name) > MAX_FOLDER_NAME_LENGTH:
        raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
    parent_id = payload.get("parent_id")
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
        _folder_or_404(parent_id, agent_id, db)  # parent must belong to this agent
    # Pre-check for a friendlier 409 (sibling uniqueness); the DB constraint is the real race guard.
    exists = (
        db.query(AgentFolder)
        .filter(AgentFolder.agent_id == agent_id, AgentFolder.parent_id.is_(None) if parent_id is None
                else AgentFolder.parent_id == parent_id, AgentFolder.name == name)
        .first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="A folder with this name already exists here")
    folder = AgentFolder(agent_id=agent_id, company_id=agent.company_id, name=name, is_active=True, parent_id=parent_id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {
        "id": folder.id,
        "name": folder.name,
        "is_active": folder.is_active,
        "parent_id": folder.parent_id,
        "document_count": 0,
    }
```

Note : la condition `parent_id.is_(None) if parent_id is None else parent_id == ...` est inhabituelle en une ligne ; si c'est plus clair, l'écrire en deux temps :

```python
    sibling_q = db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name)
    sibling_q = sibling_q.filter(AgentFolder.parent_id.is_(None)) if parent_id is None else sibling_q.filter(
        AgentFolder.parent_id == parent_id
    )
    if sibling_q.first():
        raise HTTPException(status_code=409, detail="A folder with this name already exists here")
```

Utiliser la forme en deux temps (plus lisible).

- [ ] **Step 4 : `list_agent_folders` — renvoyer `parent_id`**

Dans `backend/routers/agent_folders.py`, dans le dict de chaque dossier de `list_agent_folders` (lignes 46-52), ajouter la clé `parent_id` :

```python
            {
                "id": f.id,
                "name": f.name,
                "is_active": f.is_active,
                "parent_id": f.parent_id,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "document_count": int(counts.get(f.id, 0)),
            }
```

- [ ] **Step 5 : `update_agent_folder` — collision parmi les frères**

Dans `backend/routers/agent_folders.py`, dans `update_agent_folder`, remplacer le bloc de collision (lignes 99-105) par une vérification au sein du même parent :

```python
        sibling_q = db.query(AgentFolder).filter(
            AgentFolder.agent_id == agent_id, AgentFolder.name == name, AgentFolder.id != folder_id
        )
        sibling_q = (
            sibling_q.filter(AgentFolder.parent_id.is_(None))
            if folder.parent_id is None
            else sibling_q.filter(AgentFolder.parent_id == folder.parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
```

Et ajouter `parent_id` au dict de retour de `update_agent_folder` :

```python
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active, "parent_id": folder.parent_id}
```

- [ ] **Step 6 : `delete_agent_folder` — bloquer si sous-dossiers**

Dans `backend/routers/agent_folders.py`, dans `delete_agent_folder`, après le calcul de `doc_count` et avant `db.delete(folder)` (vers ligne 133), ajouter une vérification de sous-dossiers et combiner :

```python
    child_count = (
        db.query(func.count(AgentFolder.id)).filter(AgentFolder.parent_id == folder_id).scalar()
    )
    if doc_count or child_count:
        raise HTTPException(status_code=409, detail="Folder is not empty")
```

(Remplacer le `if doc_count:` existant par ce bloc combiné.)

- [ ] **Step 7 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_agent_folders.py -v`
Expected (local) : les tests purs PASS, le reste SKIPPED. CI : tous PASS.

Run: `cd backend && ruff check routers/agent_folders.py && ruff format --check routers/agent_folders.py`
Expected: clean (sinon `ruff format routers/agent_folders.py`).

- [ ] **Step 8 : Commit**

```bash
git add backend/routers/agent_folders.py backend/tests/test_agent_folders.py
git commit -m "feat(rag): companion folder CRUD with parent_id (subfolders)"
```

---

## Task 4 : CRUD entreprise avec `parent_id`

**Files:**
- Modify: `backend/routers/company_rag.py` (list ~224-254 ; create ~262-292 ; rename ~295-332 ; delete ~334-361 ; `_folder_or_404` ~215-221)
- Test: `backend/tests/test_company_rag_folders.py`

- [ ] **Step 1 : Écrire les tests (qui échouent)**

Dans `backend/tests/test_company_rag_folders.py`, ajouter à la fin (réutilise le helper `_make_folder(db_session, company_id, name)` déjà présent dans ce fichier ; vérifier sa signature exacte en haut du fichier et adapter les appels) :

```python
# -- subfolders (company) ----------------------------------------------------


@pytest.mark.asyncio
async def test_company_create_subfolder(client, admin_cookies, db_session, test_company):
    parent = _make_folder(db_session, test_company.id, "Parent")
    resp = await client.post(
        "/api/company-rag/folders", json={"name": "Child", "parent_id": parent.id}, cookies=admin_cookies
    )
    assert resp.status_code == 200
    assert resp.json()["parent_id"] == parent.id


@pytest.mark.asyncio
async def test_company_create_subfolder_bad_parent_404(client, admin_cookies):
    resp = await client.post(
        "/api/company-rag/folders", json={"name": "Child", "parent_id": 999999}, cookies=admin_cookies
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_company_same_name_diff_parents_ok(client, admin_cookies, db_session, test_company):
    p1 = _make_folder(db_session, test_company.id, "P1")
    p2 = _make_folder(db_session, test_company.id, "P2")
    r1 = await client.post(
        "/api/company-rag/folders", json={"name": "2024", "parent_id": p1.id}, cookies=admin_cookies
    )
    r2 = await client.post(
        "/api/company-rag/folders", json={"name": "2024", "parent_id": p2.id}, cookies=admin_cookies
    )
    assert r1.status_code == 200 and r2.status_code == 200


@pytest.mark.asyncio
async def test_company_list_returns_parent_id(client, admin_cookies, member_cookies, db_session, test_company):
    parent = _make_folder(db_session, test_company.id, "ListParent")
    resp = await client.get("/api/company-rag/folders", cookies=member_cookies)
    assert resp.status_code == 200
    match = next(f for f in resp.json()["folders"] if f["id"] == parent.id)
    assert "parent_id" in match and match["parent_id"] is None


@pytest.mark.asyncio
async def test_company_delete_folder_with_subfolder_409(client, admin_cookies, db_session, test_company):
    parent = _make_folder(db_session, test_company.id, "HasChild")
    from database import CompanyFolder

    child = CompanyFolder(company_id=test_company.id, name="C", parent_id=parent.id)
    db_session.add(child)
    db_session.flush()
    resp = await client.delete(f"/api/company-rag/folders/{parent.id}", cookies=admin_cookies)
    assert resp.status_code == 409
```

- [ ] **Step 2 : Lancer (skip local)**

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -k "subfolder or parent or diff_parents" -v`
Expected: SKIPPED (DB). Passer à l'implémentation.

- [ ] **Step 3 : `list_company_folders` — renvoyer `parent_id`**

Dans `backend/routers/company_rag.py`, dans le dict de chaque dossier de `list_company_folders` (lignes 246-251), ajouter `parent_id` :

```python
                {
                    "id": f.id,
                    "name": f.name,
                    "parent_id": f.parent_id,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "document_count": int(counts.get(f.id, 0)),
                }
```

- [ ] **Step 4 : `create_company_folder` — accepter `parent_id`, unicité par parent**

Dans `backend/routers/company_rag.py`, remplacer le bloc de validation/création de `create_company_folder` (lignes 271-286) par :

```python
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
        parent_id = payload.get("parent_id")
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
            _folder_or_404(parent_id, company_id, db)  # parent must belong to this company
        sibling_q = db.query(CompanyFolder).filter(CompanyFolder.company_id == company_id, CompanyFolder.name == name)
        sibling_q = (
            sibling_q.filter(CompanyFolder.parent_id.is_(None))
            if parent_id is None
            else sibling_q.filter(CompanyFolder.parent_id == parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
        folder = CompanyFolder(company_id=company_id, name=name, parent_id=parent_id)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return {"id": folder.id, "name": folder.name, "parent_id": folder.parent_id, "document_count": 0}
```

- [ ] **Step 5 : `rename_company_folder` — collision parmi les frères**

Dans `backend/routers/company_rag.py`, dans `rename_company_folder`, remplacer le bloc de collision (lignes 312-322, la requête `collision = ...` jusqu'au `raise 409`) par :

```python
        sibling_q = db.query(CompanyFolder).filter(
            CompanyFolder.company_id == company_id, CompanyFolder.name == name, CompanyFolder.id != folder_id
        )
        sibling_q = (
            sibling_q.filter(CompanyFolder.parent_id.is_(None))
            if folder.parent_id is None
            else sibling_q.filter(CompanyFolder.parent_id == folder.parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
```

(`folder` est déjà résolu via `_folder_or_404` plus haut dans `rename_company_folder` ; vérifier le nom de la variable et l'aligner.)

- [ ] **Step 6 : `delete_company_folder` — bloquer si sous-dossiers**

Dans `backend/routers/company_rag.py`, dans `delete_company_folder`, après le calcul de `doc_count` (lignes 344-348) et avant le `db.delete(folder)`, remplacer le `if doc_count:` par un contrôle combiné :

```python
        child_count = (
            db.query(func.count(CompanyFolder.id)).filter(CompanyFolder.parent_id == folder_id).scalar()
        )
        if doc_count or child_count:
            raise HTTPException(status_code=409, detail="Folder is not empty")
```

- [ ] **Step 7 : Lancer les tests + lint**

Run: `cd backend && python -m pytest tests/test_company_rag_folders.py -v`
Expected (local) : SKIPPED (DB). CI : PASS.

Run: `cd backend && ruff check routers/company_rag.py && ruff format --check routers/company_rag.py`
Expected: clean (sinon `ruff format routers/company_rag.py`).

- [ ] **Step 8 : Commit**

```bash
git add backend/routers/company_rag.py backend/tests/test_company_rag_folders.py
git commit -m "feat(rag): company folder CRUD with parent_id (subfolders)"
```

---

## Task 5 : UI arbre — page sources companion

**Files:**
- Modify: `frontend/pages/sources/[agentId].js`
- Reference: `frontend/lib/api` (instance `api`)

- [ ] **Step 1 : Lire la page + repérer les ancrages**

Lire `frontend/pages/sources/[agentId].js` en entier. Repérer (et noter dans le rapport) : l'état `folders`, `selectedFolderId`, `newFolderName` ; les handlers `reloadFolders`, `handleCreateFolder`, `handleRenameFolder`, `handleToggleFolder`, `handleDeleteFolder`, `handleMoveDoc` ; la barre de dossiers actuelle (rendu plat des chips) et le filtre `visibleDocuments`. Confirmer que les dossiers renvoyés par l'API portent désormais `parent_id`.

- [ ] **Step 2 : Construire l'arbre et l'état de repliage**

Dans le composant, ajouter un état pour les dossiers repliés et une fonction qui construit l'arbre depuis la liste plate :

```javascript
  const [collapsedFolders, setCollapsedFolders] = useState({}); // id -> true (collapsed)

  const buildFolderTree = (flat) => {
    const byParent = {};
    flat.forEach((f) => {
      const key = f.parent_id ?? 'root';
      (byParent[key] = byParent[key] || []).push(f);
    });
    const sortByName = (a, b) => a.name.localeCompare(b.name);
    const make = (parentKey) =>
      (byParent[parentKey] || [])
        .sort(sortByName)
        .map((f) => ({ ...f, children: make(f.id) }));
    return make('root');
  };
```

- [ ] **Step 3 : Ajouter un état pour le parent du nouveau dossier**

```javascript
  const [createParentId, setCreateParentId] = useState(null); // parent for the next created folder
```

Et adapter `handleCreateFolder` pour inclure `parent_id` :

```javascript
  const handleCreateFolder = async () => {
    const name = newFolderName.trim();
    if (!name) return;
    try {
      await api.post(`/api/agents/${agentId}/folders`, { name, parent_id: createParentId });
      setNewFolderName('');
      setCreateParentId(null);
      await reloadFolders();
    } catch (e) {
      showToast(e?.response?.data?.detail || 'Erreur lors de la création du dossier', 'error');
    }
  };
```

(Si la page utilise `alert(...)` plutôt que `showToast`, garder la convention existante de la page — repérée au Step 1.)

- [ ] **Step 4 : Rendre l'arbre récursivement**

Remplacer le rendu plat de la barre de dossiers par un composant récursif. Ajouter, à l'intérieur du composant page, un sous-rendu (fonction locale qui retourne du JSX) :

```jsx
  const renderFolderNodes = (nodes, depth = 0) =>
    nodes.map((f) => (
      <div key={f.id}>
        <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
          {f.children.length > 0 ? (
            <button
              onClick={() => setCollapsedFolders((c) => ({ ...c, [f.id]: !c[f.id] }))}
              className="w-4 text-gray-500"
              title={collapsedFolders[f.id] ? 'Déplier' : 'Replier'}
            >
              {collapsedFolders[f.id] ? '▸' : '▾'}
            </button>
          ) : (
            <span className="w-4" />
          )}
          <button
            onClick={() => setSelectedFolderId(f.id)}
            className={`px-2 py-1 rounded text-sm ${selectedFolderId === f.id ? 'bg-primary-600 text-white' : 'bg-gray-100'} ${f.is_active ? '' : 'opacity-50'}`}
          >
            {f.name} ({f.document_count}){f.is_active ? '' : ' — inactif'}
          </button>
          {canEdit && (
            <>
              <button title="Sous-dossier" onClick={() => { setCreateParentId(f.id); }}>
                <Plus className="w-3.5 h-3.5" />
              </button>
              <button title="Actif/inactif" onClick={() => handleToggleFolder(f)}>
                {f.is_active ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
              </button>
              <button title="Renommer" onClick={() => handleRenameFolder(f)}>
                <Pencil className="w-3.5 h-3.5" />
              </button>
              <button title="Supprimer" onClick={() => handleDeleteFolder(f)}>
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
        {!collapsedFolders[f.id] && f.children.length > 0 && renderFolderNodes(f.children, depth + 1)}
      </div>
    ));
```

Puis, à l'endroit où la liste plate des dossiers était rendue, afficher :
- le bouton « Sans dossier » (inchangé) ;
- l'input de création + bouton, avec une indication du parent courant : si `createParentId` est défini, afficher « Nouveau sous-dossier dans : <nom> » + un bouton pour annuler (`setCreateParentId(null)`) ;
- `renderFolderNodes(buildFolderTree(folders))`.

S'assurer que les icônes `Plus, Eye, EyeOff, Pencil, Trash2` sont importées depuis `lucide-react` (Plus/Eye/EyeOff/Pencil/Trash2 sont déjà importées dans cette page depuis la Phase précédente — vérifier et compléter au besoin).

- [ ] **Step 5 : Sélecteurs de dossier (upload + déplacement) en chemins indentés**

Les `<select>` d'upload-cible et de déplacement de document listent `folders` à plat. Pour rester lisibles avec la hiérarchie, afficher le chemin/indentation. Ajouter un helper qui produit des options ordonnées avec préfixe :

```javascript
  const folderOptions = () => {
    const tree = buildFolderTree(folders);
    const out = [];
    const walk = (nodes, prefix) =>
      nodes.forEach((f) => {
        out.push({ id: f.id, label: prefix + f.name + (f.is_active ? '' : ' (inactif)') });
        walk(f.children, prefix + '— ');
      });
    walk(tree, '');
    return out;
  };
```

Et utiliser `folderOptions().map(o => <option key={o.id} value={o.id}>{o.label}</option>)` dans les deux `<select>` (upload-cible et déplacement), en gardant l'option « Sans dossier » (value `""`).

- [ ] **Step 6 : Lint + build**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 7 : Commit**

```bash
git add "frontend/pages/sources/[agentId].js"
git commit -m "feat(rag): tree folder UI + subfolder creation on companion sources page"
```

---

## Task 6 : UI arbre — page organisation (entreprise)

**Files:**
- Modify: `frontend/pages/organization.js`

- [ ] **Step 1 : Lire la section dossiers + repérer les ancrages**

Lire `frontend/pages/organization.js`, section company RAG. Repérer : l'état `folders`, `selectedFolderId` ; `loadFolders`, `handleCreateFolder`, `handleRenameFolder`, `handleDeleteFolder`, `handleUploadDoc`, `handleMoveDoc` ; le rendu plat de la barre de dossiers (lignes ~789-803). Noter les classes Tailwind/icônes utilisées (organization.js utilise un style propre — le respecter).

- [ ] **Step 2 : Construire l'arbre + état de repliage + parent de création**

Ajouter (mêmes patterns qu'en Task 5, adaptés au style de organization.js) :

```javascript
  const [collapsedFolders, setCollapsedFolders] = useState({});
  const [createParentId, setCreateParentId] = useState(null);

  const buildFolderTree = (flat) => {
    const byParent = {};
    flat.forEach((f) => {
      const key = f.parent_id ?? 'root';
      (byParent[key] = byParent[key] || []).push(f);
    });
    const make = (parentKey) =>
      (byParent[parentKey] || [])
        .sort((a, b) => a.name.localeCompare(b.name))
        .map((f) => ({ ...f, children: make(f.id) }));
    return make('root');
  };
```

- [ ] **Step 3 : `handleCreateFolder` avec `parent_id`**

Adapter `handleCreateFolder` pour passer `parent_id: createParentId` dans le POST `/api/company-rag/folders`, puis `setCreateParentId(null)` après succès. Conserver la convention de saisie existante (la page utilise `prompt(...)` pour le nom — garder `prompt`, ou un input ; mais le « + sous-dossier » d'un dossier doit fixer `createParentId` à l'id du dossier avant de demander le nom). Exemple :

```javascript
  const handleCreateSubfolder = async (parent) => {
    const name = window.prompt('Nom du sous-dossier');
    if (!name || !name.trim()) return;
    try {
      await api.post('/api/company-rag/folders', { name: name.trim(), parent_id: parent.id });
      await loadFolders();
    } catch (e) {
      alert(e?.response?.data?.detail || 'Erreur lors de la création du sous-dossier');
    }
  };
```

(Réutiliser le mécanisme d'erreur déjà utilisé dans la page — `alert` d'après l'exploration.)

- [ ] **Step 4 : Rendu récursif de l'arbre**

Remplacer le rendu plat de la barre de dossiers (~789-803) par un rendu récursif équivalent à celui de la Task 5, en utilisant les classes Tailwind et icônes de organization.js (glyphes ✎/🗑 déjà utilisés dans cette page — les conserver pour rester cohérent avec organization.js, et ajouter un « + » pour le sous-dossier et un chevron ▸/▾ pour replier). Chaque nœud : chevron (si enfants), bouton de sélection (nom + count), et au survol/à côté : « + sous-dossier » (`handleCreateSubfolder(f)`), renommer, supprimer.

- [ ] **Step 5 : Lint + build**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 6 : Commit**

```bash
git add frontend/pages/organization.js
git commit -m "feat(rag): tree folder UI + subfolder creation on organization page"
```

---

## Task 7 : UI arbre de sélection — page agents (sélection des dossiers entreprise)

**Files:**
- Modify: `frontend/pages/agents.js`

- [ ] **Step 1 : Lire la section de sélection + repérer les ancrages**

Lire `frontend/pages/agents.js`. Repérer : l'état `companyFolders` (chargé au montage, ~ligne 49, 56-58) ; le rendu des cases à cocher de dossiers (~598-619, affiché quand `include_company_rag=true`, logique tri-state) ; le champ de formulaire `company_rag_folder_ids` (~695-696). Noter comment la sélection est stockée (tableau d'ids).

- [ ] **Step 2 : Construire l'arbre des dossiers entreprise**

Ajouter une fonction `buildFolderTree` identique à celle des tasks précédentes (à partir de `companyFolders`, qui portent désormais `parent_id`).

- [ ] **Step 3 : Rendu récursif des cases à cocher**

Remplacer le rendu plat des cases à cocher (~598-619) par un rendu récursif indenté : chaque dossier est une case à cocher (la sélection reste un simple tableau d'ids — cocher un parent ajoute son id à la liste ; l'expansion au sous-arbre est faite côté backend à la récupération, donc l'UI n'a pas besoin de cocher automatiquement les enfants). Indenter les enfants (`paddingLeft: depth * 16`). Conserver la logique tri-state existante (tout/partiel/aucun) au niveau de l'en-tête si présente.

Optionnel (clarté) : afficher sous un parent coché une mention « (inclut les sous-dossiers) » pour signaler la sémantique récursive.

- [ ] **Step 4 : Lint + build**

Run: `cd frontend && npm run lint`
Expected: aucune nouvelle erreur.

Run: `cd frontend && npm run build`
Expected: build réussi.

- [ ] **Step 5 : Commit**

```bash
git add frontend/pages/agents.js
git commit -m "feat(rag): tree folder selection (recursive) on agents page"
```

---

## Self-Review (effectué par l'auteur du plan)

**Couverture de la spec (Phase 1) :**
- §1.1 Schéma `parent_id` + unicité frères + migration → Task 1 ✓
- §1.2 CRUD avec `parent_id` (companion + entreprise) + delete bloqué si sous-dossiers → Task 3 (companion) + Task 4 (entreprise) ✓
- §1.3 Récupération récursive (inactif companion + sélection entreprise) → Task 2 ✓
- §1.4 UI arbre (sources, organisation, agents) → Tasks 5, 6, 7 ✓

**Placeholders :** aucun TODO/TBD ; code fourni à chaque étape. Les Tasks 5-7 (frontend) demandent une lecture préalable des pages et une adaptation au style existant — les ancrages et patterns sont fournis ; c'est intentionnel (le code exact dépend du markup existant), pas un placeholder de logique.

**Cohérence des types/noms :** `parent_id` (colonne + payloads + réponses), `_descendant_folder_ids(start_ids, pairs) -> set`, `_inactive_agent_folder_ids` (renvoie la liste étendue), `buildFolderTree`/`renderFolderNodes`/`createParentId`/`collapsedFolders` cohérents entre les tasks frontend. Les contraintes `uq_company_folder_parent_name` / `uq_agent_folder_parent_name` cohérentes entre le modèle (Task 1 Steps 1-2) et la DDL (Task 1 Step 4).

**Points d'attention :**
- Le helper `_make_folder` diffère entre `test_agent_folders.py` (signature `(db_session, agent, name, is_active=True)`, accepte un objet agent) et `test_company_rag_folders.py` (signature `(db_session, company_id, name)`) — l'implémenteur doit utiliser la bonne signature par fichier (Task 4 Step 1 le rappelle).
- Les tests DB skippent en local ; la validation réelle (dont la migration de contrainte et la récursivité pgvector) se fait en CI.
