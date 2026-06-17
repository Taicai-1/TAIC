# RAG Entreprise — Dossiers + sélection par agent (+ fix UX)

**Date :** 2026-06-17
**Branche :** `feature/company-rag-folders` (depuis `dev`)
**Statut :** Spec validée — prêt pour le plan d'implémentation

## Contexte

La feature « RAG Entreprise » existe déjà (livrée 2026-06-15, sur `dev`) :
- `Document.is_company_rag` (bool) marque un doc partagé d'organisation (`agent_id=NULL`, `company_id` défini).
- `Agent.include_company_rag` (bool) : opt-in par agent.
- `backend/routers/company_rag.py` : `GET` (tout membre) / `POST` + `DELETE` (admin/owner) sur `/api/company-rag/documents`.
- Récupération : `rag_engine.py` unionne les docs entreprise quand l'agent opte, sous le filtre tenant `company_id`.
- Frontend : section « RAG Entreprise » dans `pages/organization.js`, toggle dans création (`agents.js`) / édition (`index.js`) d'agent.

## Objectif

1. **Dossiers** : organiser les documents entreprise en dossiers (liste plate, pas de sous-dossiers).
2. **Sélection par agent** : à l'activation du RAG entreprise, tous les dossiers sont inclus par défaut, avec possibilité de choisir un sous-ensemble.
3. **Fix UX** : un doc uploadé apparaît sans avoir à changer de page et revenir.

## Décisions de conception (validées)

- Dossiers **plats** (pas d'imbrication).
- Dossier **obligatoire** à l'upload (pas de bac « Non classé »).
- Défaut « tous les dossiers » = **dynamique** : inclut les dossiers présents ET futurs.
- Gestion complète : créer, renommer, supprimer, déplacer un doc.
- Suppression d'un dossier **bloquée si non vide**.
- Migration des docs entreprise existants → dossier « Général » auto-créé par organisation.

## 1. Modèle de données

### Nouvelle table `CompanyFolder` (`database.py`)
| Colonne | Type | Notes |
|---|---|---|
| `id` | Integer, PK | |
| `company_id` | Integer, FK `companies.id`, indexé, non-null | frontière tenant |
| `name` | String, non-null | |
| `created_at` | DateTime, défaut now | |

Contrainte : `UniqueConstraint("company_id", "name")` — pas deux dossiers de même nom dans une org.

### `Document` — nouvelle colonne
- `folder_id` : Integer, FK `company_folders.id`, **nullable au niveau DB** (les docs normaux/agents n'en ont pas), **obligatoire au niveau applicatif** pour les docs `is_company_rag=True`.
- Ajoutée via la liste `ensure_columns` de `database.py` (même mécanisme que `is_company_rag`).

### `Agent` — nouvelle colonne
- `company_rag_folder_ids` : Text (JSON), nullable.
- Sémantique : `NULL` / `[]` = **tous les dossiers** (présents et futurs, dynamique). Liste d'ids = sous-ensemble. Un id pointant vers un dossier supprimé est inerte (le filtre `in_` ne matche rien).
- Ajoutée via `ensure_columns`.

### Migration au boot (idempotente)
Pour chaque `company_id` ayant ≥1 doc `is_company_rag=True` avec `folder_id IS NULL` :
1. Récupérer ou créer le dossier « Général » de cette org (via l'unicité `(company_id, name)`).
2. Affecter `folder_id` de ces docs au dossier « Général ».

## 2. Endpoints backend (`routers/company_rag.py`)

Sécurité inchangée : `_require_company_id` + `require_role(..., "admin")` pour les mutations ; lecture pour tout membre ; frontière tenant = `company_id` du caller.

### Dossiers
- `GET /api/company-rag/folders` — liste les dossiers de l'org (tout membre), chaque entrée avec `id`, `name`, `created_at`, `document_count`.
- `POST /api/company-rag/folders` — créer (admin/owner). Body `{name}`. `409` si nom déjà pris dans l'org. `400` si nom vide.
- `PUT /api/company-rag/folders/{id}` — renommer (admin/owner). Body `{name}`. `409` si collision. `404` si hors org.
- `DELETE /api/company-rag/folders/{id}` — supprimer (admin/owner). `400` si le dossier contient des docs (bloqué si non vide). `404` si hors org.

### Documents
- `POST /api/company-rag/documents` — ajout du champ form **`folder_id` obligatoire**. Valide que le dossier appartient à l'org (sinon `400`). Propagé via `_process_document_background` → `process_document_for_user` (nouveau param `folder_id`).
- `GET /api/company-rag/documents` — renvoie `folder_id` en plus ; accepte un filtre optionnel `?folder_id=`.
- `PUT /api/company-rag/documents/{id}/folder` — déplacer un doc (admin/owner). Body `{folder_id}`. Valide doc + dossier cible dans l'org.

### Threading `folder_id`
- `backend/routers/documents.py` : `_process_document_background(...)` reçoit un nouveau param `folder_id` (transmis à `process_document_for_user`).
- `backend/rag_engine.py` : `process_document_for_user(...)` reçoit `folder_id` et le pose sur la ligne `Document`.

## 3. Récupération RAG (`rag_engine.py`)

Là où `include_company_rag` est déjà lu depuis l'agent (3 chemins : `get_answer`, `get_answer_stream`, `search_similar_texts_for_user`), lire aussi `company_rag_folder_ids` (parsé du JSON, défaut `[]`).

Logique de filtrage de la branche « docs entreprise » de l'union :
- `include_company_rag` vrai **et** liste de dossiers **non vide** → restreindre les docs entreprise à `Document.folder_id.in_(selected_ids)`.
- liste vide / `NULL` → comportement actuel inchangé (tous les docs entreprise de l'org).

Le filtre s'applique **uniquement** à la branche docs entreprise ; les docs propres à l'agent ne sont pas affectés. `search_similar_texts_for_user` reçoit un nouveau param `company_rag_folder_ids: list = None`.

## 4. Frontend

### `pages/organization.js` — section « RAG Entreprise » organisée par dossiers
- Liste / barre de dossiers avec compteur de docs ; bouton « + Nouveau dossier » (admin).
- Sélection d'un dossier → affiche ses documents ; l'upload se fait dans le dossier sélectionné (`folder_id` rempli automatiquement).
- Actions admin par dossier : renommer ; supprimer (désactivé / message clair si non vide).
- Action par document : déplacer vers un autre dossier (menu déroulant des dossiers).
- Membres non-admin : lecture seule (comme aujourd'hui).
- État : `folders`, `selectedFolderId`, en plus de `companyDocs`.

### Agent — création (`agents.js`) et édition (`index.js`)
- Sous le toggle « RAG Entreprise », quand activé : multi-select des dossiers, **tout coché par défaut**.
- « Tout coché » → envoyer `[]` (= dynamique, inclut les futurs dossiers). Décoché → envoyer les ids sélectionnés.
- Champ envoyé au backend : `company_rag_folder_ids` (JSON). Lu/écrit dans `routers/agents.py` (create form param + update).

### i18n
- Nouvelles clés dans `organization.json` (fr+en) : titres dossiers, actions, messages d'erreur (dossier non vide, nom dupliqué).
- Nouvelles clés dans `agents.json` (fr+en) : label du multi-select de dossiers.

## 5. Fix du bug d'affichage

**Cause :** l'upload async renvoie `task_id` + `status: processing` ; `loadCompanyDocs()` est appelé avant que la tâche de fond ait créé la ligne `Document`. L'utilisateur doit changer de page et revenir pour voir le doc.

**Fix :** dans `handleCompanyDocUpload` (`organization.js`), réutiliser le pattern de polling existant (cf. `pollUploadStatus` dans `index.js` interrogeant `/upload-status/{task_id}` toutes les 2s). Si la réponse contient un `task_id`, poll jusqu'à `completed`/`failed` puis `loadCompanyDocs()`. Le bouton reste en état « upload en cours » pendant le polling. Cas sync (sans Redis) : reload immédiat comme aujourd'hui.

## Sécurité / multi-tenant

- Tout accès dossier/doc filtré par `company_id` du caller.
- Mutations (créer/renommer/supprimer dossier, upload, déplacer, delete doc) réservées admin/owner via `require_role`.
- `folder_id` fourni par le client toujours validé comme appartenant à l'org du caller avant usage.
- Le filtrage par dossier en récupération s'applique **en plus** du filtre tenant `company_id` existant (jamais en remplacement).

## Tests

- Backend (`backend/tests/test_company_rag.py`, DB-backed, SKIP local / run CI) : CRUD dossiers, unicité de nom, suppression bloquée si non vide, upload exige `folder_id` valide, déplacement de doc, filtrage récupération par sous-ensemble de dossiers, isolation tenant.
- Lint : ruff (backend), ESLint + build Next.js (frontend).

## Hors périmètre (YAGNI)

- Sous-dossiers / hiérarchie.
- Bac « Non classé ».
- Snapshot figé des dossiers par agent (on retient le mode dynamique).
- Déplacement / upload en masse multi-fichiers.
