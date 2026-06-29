# Sous-dossiers RAG + import de dossier — Design

**Date:** 2026-06-26
**Statut:** Approuvé (design), prêt pour les plans d'implémentation
**Découpage:** 2 phases / 2 plans séquentiels (Phase 2 dépend de Phase 1)

## Contexte & objectif

Les deux systèmes de dossiers RAG — entreprise (`CompanyFolder`) et companion
(`AgentFolder`) — sont aujourd'hui **plats** (aucun `parent_id`, aucune notion
d'arborescence ni d'import de répertoire). On veut, pour **les deux systèmes** :

1. **Sous-dossiers** : pouvoir créer des dossiers imbriqués (hiérarchie).
2. **Import d'un dossier entier** : au-delà d'un fichier, importer un répertoire ;
   s'il contient des sous-dossiers, recréer l'arborescence.

### Décisions de cadrage (validées)

- **Sémantique récursive (sous-arbre)** : l'état d'un dossier s'applique à tout son
  sous-arbre. Companion : un dossier inactif exclut ses descendants de la
  récupération. Entreprise : sélectionner un dossier parent inclut les documents de
  ses descendants.
- **Import** : le dossier racine importé est **recréé** à l'emplacement de
  destination (dossier sélectionné, ou racine), et l'arborescence est recréée
  dessous. **Collision de nom → fusion** dans le dossier existant (réutilisation).
- **Profondeur illimitée**.
- **Fichiers non supportés** : ignorés et comptés ; un sous-dossier qui finirait
  vide n'est **pas** créé. L'import ne casse pas pour un fichier parasite.
- **Suppression** d'un dossier : bloquée (409) tant qu'il contient des documents
  **ou** des sous-dossiers.

### Hors périmètre (YAGNI)

- Déplacement / re-parentage de dossiers (le déplacement de **documents** existe déjà).
- Suppression récursive (on bloque tant que non vide).
- Plafond de profondeur.

---

## Architecture par couche (rappel de l'existant)

Touchés des deux côtés : modèles `CompanyFolder`/`AgentFolder` (`backend/database.py`),
routeurs `backend/routers/company_rag.py` et `backend/routers/agent_folders.py`,
récupération `backend/rag_engine.py` (`search_similar_texts_for_user`,
`_inactive_agent_folder_ids`, filtre `company_rag_folder_ids`), sélection des dossiers
entreprise par l'agent (`backend/routers/agents.py` : `_parse_folder_ids`/`_folder_ids_out`,
champ `Agent.company_rag_folder_ids`), pipeline d'upload (`backend/routers/documents.py`
`_process_document_background` → `process_document_for_user` → `ingest_text_content`),
et les UI `frontend/pages/organization.js`, `frontend/pages/sources/[agentId].js`,
`frontend/pages/index.js`, `frontend/pages/agents.js`.

---

# Phase 1 — Sous-dossiers (hiérarchie)

## 1.1 Schéma (`backend/database.py`)

Ajout d'une colonne `parent_id` sur **`CompanyFolder`** et **`AgentFolder`** :

```python
parent_id = Column(
    Integer, ForeignKey("<table>.id", ondelete="CASCADE"), nullable=True, index=True
)  # NULL = top-level folder; CASCADE so a deleted parent takes its subtree
```

- `CompanyFolder.parent_id` → FK self `company_folders.id`.
- `AgentFolder.parent_id` → FK self `agent_folders.id`.
- `ON DELETE CASCADE` : sûr car la suppression applicative est bloquée tant que non
  vide (au moment d'une suppression, le dossier n'a pas d'enfant) ; le CASCADE ne
  joue qu'en cas de suppression « forcée » en amont (ex. suppression d'un agent qui
  cascade déjà sur `agent_folders`).
- **Unicité entre frères** : remplacer `UniqueConstraint(<tenant>, name)` par
  `UniqueConstraint(<tenant>, parent_id, name)`. Note Postgres : deux `NULL` de
  `parent_id` sont considérés distincts par une contrainte UNIQUE, donc la contrainte
  ne garantit pas à elle seule l'unicité au niveau racine. Le **pré-check applicatif**
  (déjà présent dans les endpoints create/rename) reste le garde-fou principal et
  filtre par `parent_id` (y compris `IS NULL`).
- **Migration** : `parent_id` ajoutée à la liste `ensure_columns()`
  (`ADD COLUMN IF NOT EXISTS … REFERENCES <table>(id) ON DELETE CASCADE`). Les
  dossiers existants restent racine (`parent_id` NULL). Aucune donnée à migrer.

## 1.2 CRUD dossiers (les deux routeurs)

`backend/routers/company_rag.py` et `backend/routers/agent_folders.py` :

- **Helper `_folder_or_404`** : inchangé (résout un dossier dans le tenant/agent).
- **Helper de validation du parent** : si un `parent_id` est fourni, il doit exister
  et appartenir au même tenant/agent (sinon 404).
- **Créer** (`POST …/folders`) : accepte `parent_id` optionnel dans le payload.
  Pré-check d'unicité du nom **dans le parent** (`parent_id == X` ou `IS NULL`).
  Crée le dossier avec `parent_id`.
- **Lister** (`GET …/folders`) : ajoute `parent_id` à chaque dossier renvoyé. Les
  `document_count` restent les documents **directs** du dossier (inchangé).
- **Renommer** (`PUT …`) : pré-check de collision parmi les frères (même `parent_id`).
- **Supprimer** (`DELETE …`) : bloqué (409) si le dossier a des documents **ou** au
  moins un sous-dossier (`COUNT(children) > 0` en plus du `COUNT(docs) > 0`).
- **Déplacement de documents** (`PUT …/documents/{id}/folder`) : inchangé.

## 1.3 Récupération récursive (`backend/rag_engine.py`)

Helper partagé d'expansion d'arbre (en mémoire, une requête pour charger les paires
`(id, parent_id)` du tenant/agent, puis DFS) :

```python
def _descendant_folder_ids(folder_ids, all_pairs):
    """Return folder_ids plus all their descendants, given (id, parent_id) pairs."""
```

- **Companion** : `_inactive_agent_folder_ids(agent_id, db)` renvoie désormais
  l'ensemble **étendu** = tous les dossiers inactifs **et leurs descendants**. Le
  filtre d'exclusion dans `search_similar_texts_for_user` (branche `elif agent_id:`)
  est inchangé dans sa forme : `or_(agent_folder_id IS NULL, agent_folder_id NOT IN
  excluded)`. La **signature de cache RAG** (qui inclut déjà cet ensemble) suit
  automatiquement → un toggle sur un parent invalide bien le cache.
- **Entreprise** : avant le filtre `Document.folder_id.in_(company_rag_folder_ids)`,
  étendre `company_rag_folder_ids` à son sous-arbre via `_descendant_folder_ids`
  (sur les `CompanyFolder` de la company). Ainsi sélectionner « Juridique » inclut
  « Juridique/Contrats ».

## 1.4 Frontend (arbre)

Pages : `frontend/pages/organization.js` (entreprise),
`frontend/pages/sources/[agentId].js` (companion),
`frontend/pages/agents.js` (sélection des dossiers entreprise par l'agent).

- Reconstruction d'un **arbre** à partir de la liste plate `folders` (via `parent_id`),
  rendu **repliable** (chevron par dossier ayant des enfants).
- **« + sous-dossier »** sur chaque dossier (ouvre une saisie de nom, POST avec
  `parent_id` = id du dossier).
- Companion : l'interrupteur actif/inactif reste par dossier ; visuellement, un
  dossier inactif (et idéalement son sous-arbre) est atténué.
- `agents.js` (sélection entreprise) : arbre de cases à cocher ; cocher un parent
  vaut pour son sous-arbre (l'expansion réelle est faite côté backend à la
  récupération — l'UI peut simplement refléter la sélection des ids choisis).
- Le filtrage de la liste de documents par dossier sélectionné reste sur les
  documents **directs** du dossier (cohérent avec l'existant).

---

# Phase 2 — Import d'un dossier entier

## 2.1 Frontend (les deux systèmes)

- Bouton **« Importer un dossier »** à côté de « Importer un fichier », via
  `<input type="file" webkitdirectory directory multiple>`.
- Pour chaque fichier sélectionné, le navigateur expose `webkitRelativePath`
  (ex. `Contrats/2024/bail.pdf`). Le frontend :
  1. filtre les extensions non supportées (`.pdf`, `.txt`, `.docx`, `.ics`, `.json`) ;
  2. construit une requête multipart : `files[]` (les fichiers supportés) + `paths[]`
     (les `webkitRelativePath` correspondants, même ordre) + `parent_id` (destination
     = dossier sélectionné, ou vide pour racine) ;
  3. POST vers l'endpoint d'import, récupère `import_task_id`, puis **poll**
     `…/import-status/{id}` et affiche une **barre de progression** + un
     **récapitulatif** final (« N importés, M ignorés »).
- Pages : `frontend/pages/sources/[agentId].js` + `frontend/pages/index.js`
  (companion), `frontend/pages/organization.js` (entreprise).

## 2.2 Endpoints

- Companion : `POST /api/agents/{agent_id}/folders/import`
  (perm : `_user_can_edit_agent`).
- Entreprise : `POST /api/company-rag/folders/import` (perm : rôle admin).
- Champs multipart : `files: list[UploadFile]`, `paths: list[str]` (parallèle),
  `parent_id: int | None` (destination).
- Statut : `GET /api/agents/{agent_id}/folders/import-status/{task_id}` et
  `GET /api/company-rag/folders/import-status/{task_id}`.
- Réponse du POST : `{ "import_task_id": "...", "status": "processing" }`.

## 2.3 Traitement (job d'arrière-plan, logique partagée)

Un module helper partagé `backend/folder_import.py` (testable indépendamment) :

```python
def resolve_folder_for_path(rel_dir_segments, destination_parent_id, tenant_ctx, db, cache) -> int:
    """Ensure the folder chain for rel_dir_segments exists under destination_parent_id,
    merging into existing same-named children. Return the leaf folder id. Cache by path."""
```

Flux du job (un seul `import_task_id`, repli synchrone si Redis absent) :

1. Initialiser le statut Redis : `{total, done, skipped, failed, status:"processing",
   root_folder_id:null}` (TTL 1h, comme `doc_task:*`).
2. Pour chaque `(file, path)` :
   - Valider le fichier (extension + taille + magic bytes, comme l'upload simple).
     Invalide / non supporté → `skipped += 1`, continuer.
   - Découper `path` en segments de dossiers + nom de fichier. Le **premier segment
     est le dossier racine importé** (recréé sous la destination). Résoudre la chaîne
     via `resolve_folder_for_path` (création paresseuse + fusion + cache par chemin) →
     `folder_id` feuille. Mémoriser `root_folder_id` (1ʳᵉ chaîne résolue).
   - Ingestion via le pipeline existant (`process_document_for_user` /
     `ingest_text_content`) avec le `agent_folder_id` / `folder_id` résolu. `done += 1`
     (ou `failed += 1` en cas d'erreur d'ingestion, sans casser le lot).
   - Mettre à jour le statut Redis.
3. Statut final `status:"completed"` avec les compteurs + `root_folder_id`.

**Aucun dossier vide** : la chaîne de dossiers n'est créée que lors de la résolution
d'un fichier réellement importé (création paresseuse). Un sous-dossier ne contenant
que des fichiers non supportés n'est donc jamais créé.

## 2.4 Validation & limites

- Réutiliser les validateurs existants (`validate_file_content`, taille max, cap de
  pages PDF) par fichier ; un échec compte en « ignoré/échoué », pas d'arrêt du lot.
- Garde-fous d'abus : **nombre max de fichiers par import** et **taille totale max**
  (constantes alignées sur les limites d'upload existantes). Au-delà → 413/400 au POST
  avec message clair.
- Permissions identiques aux uploads simples (édition de l'agent / admin entreprise).

## 2.5 Tests

- **Backend (unitaire, sans DB)** : `resolve_folder_for_path` / construction d'arbre
  depuis une liste de chemins — fusion, déduplication par chemin, pas de dossiers
  vides, profondeur > 2.
- **Backend (DB, CI)** : import → dossiers créés avec les bons `parent_id`, documents
  rattachés au bon dossier, fichiers non supportés ignorés (compteurs), fusion dans un
  dossier existant. Récursivité de récupération de la Phase 1 (un parent inactif exclut
  les docs d'un sous-dossier ; un parent sélectionné côté entreprise inclut les docs du
  sous-dossier).
- **Frontend** : lint + build.

---

## Fichiers touchés (synthèse)

| Fichier | Phase | Changement |
|---------|-------|------------|
| `backend/database.py` | 1 | `parent_id` sur les 2 modèles ; `ensure_columns` ; unicité `(tenant, parent_id, name)` |
| `backend/routers/company_rag.py` | 1 | create/list/rename/delete avec `parent_id` |
| `backend/routers/agent_folders.py` | 1 | idem côté agent |
| `backend/rag_engine.py` | 1 | `_descendant_folder_ids` ; `_inactive_agent_folder_ids` récursif ; expansion `company_rag_folder_ids` |
| `frontend/pages/organization.js` | 1 | arbre + « + sous-dossier » |
| `frontend/pages/sources/[agentId].js` | 1 | arbre + « + sous-dossier » |
| `frontend/pages/agents.js` | 1 | arbre de cases à cocher (sélection entreprise) |
| `backend/folder_import.py` | 2 | **nouveau** : résolution/fusion d'arbre depuis des chemins |
| `backend/routers/agent_folders.py` | 2 | endpoints import + import-status (companion) |
| `backend/routers/company_rag.py` | 2 | endpoints import + import-status (entreprise) |
| `frontend/pages/organization.js` | 2 | bouton import dossier + progression |
| `frontend/pages/sources/[agentId].js` | 2 | bouton import dossier + progression |
| `frontend/pages/index.js` | 2 | bouton import dossier (companion) |
| `backend/tests/…` | 1 & 2 | tests hiérarchie + import |
