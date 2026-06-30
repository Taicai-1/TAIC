# Dossiers dans le RAG des companions — Design

**Date:** 2026-06-26
**Statut:** Approuvé (design), prêt pour le plan d'implémentation

## Contexte & objectif

Le RAG entreprise (`company_rag`) supporte des dossiers (`CompanyFolder`) pour
organiser les documents partagés et choisir quels dossiers un agent utilise. Le
RAG des companions (documents rattachés à un agent via `Document.agent_id`) stocke
les documents à plat, sans dossiers.

Objectif : permettre la création de dossiers dans le RAG des companions, avec :

1. **Organisation** — ranger/regrouper les documents d'un companion.
2. **Contrôle de récupération** — un interrupteur actif/inactif par dossier ; un
   dossier inactif n'est pas utilisé par le companion pour répondre.

### Décisions de cadrage (validées)

- Les dossiers servent à l'organisation **et** au contrôle de récupération (option B).
- Contrôle via un **interrupteur `is_active` par dossier** (les documents
  appartiennent déjà au companion — pas besoin d'une liste de sélection sur l'agent).
- **Parité fonctionnelle complète** avec le RAG entreprise : créer, renommer,
  supprimer (si vide), uploader directement dans un dossier, déplacer un document.
- Dossier **optionnel** : un document peut ne pas avoir de dossier (zone « Sans
  dossier »). Les documents existants restent sans dossier. Rétrocompatible.

## Architecture

Le design réutilise les patterns existants du RAG entreprise (`CompanyFolder`,
`routers/company_rag.py`, `organization.js`) transposés au scope par agent.

### 1. Modèle de données

**Nouvelle table `AgentFolder`** (dans `backend/database.py`, calquée sur
`CompanyFolder` lignes 576-584) :

| Colonne      | Type                                   | Notes                              |
|--------------|----------------------------------------|------------------------------------|
| `id`         | Integer PK                             |                                    |
| `agent_id`   | Integer FK → `agents.id`, NOT NULL, index |                                 |
| `company_id` | Integer FK → `companies.id`, index     | Isolation tenant / RLS             |
| `name`       | String(255), NOT NULL                  |                                    |
| `is_active`  | Boolean, NOT NULL, défaut `True`, server_default `'true'` | Contrôle de récupération |
| `created_at` | DateTime, défaut `utcnow`              |                                    |

- Contrainte d'unicité `UniqueConstraint("agent_id", "name", name="uq_agent_folder_name")`.
- Ajoutée à `TENANT_TABLES` (`backend/database.py` ~ligne 1271) pour bénéficier des
  policies RLS, comme `company_folders`.

**Nouvelle colonne `documents.agent_folder_id`** :

- `Column(Integer, ForeignKey("agent_folders.id", ondelete="SET NULL"), nullable=True, index=True)`.
- `NULL` = document « Sans dossier ».
- On **ne réutilise pas** la colonne `folder_id` existante (réservée au RAG
  entreprise, FK → `company_folders`) : pas de mélange sémantique. Les docs d'agent
  ont `is_company_rag=False` et `folder_id=NULL` ; les docs entreprise ont
  `agent_id=NULL` et `agent_folder_id=NULL`. Aucun chevauchement.

**Migrations :**

- La table `agent_folders` est créée automatiquement par
  `Base.metadata.create_all(bind=engine)` au démarrage (`main.py` ~ligne 427).
- La colonne `documents.agent_folder_id` est ajoutée à la liste de `ensure_columns()`
  (`backend/database.py` ~ligne 1074) avec `ADD COLUMN IF NOT EXISTS` :
  `("documents", "agent_folder_id", "INTEGER REFERENCES agent_folders(id) ON DELETE SET NULL")`.
  Elle doit aussi figurer sur le modèle `Document`.

### 2. Endpoints backend — nouveau routeur `backend/routers/agent_folders.py`

Calqué sur `routers/company_rag.py` (helpers `_folder_or_404`, validation du nom,
pré-check 409 + contrainte DB), mais scope par agent via les helpers existants
`helpers/agent_helpers.py` :

- `_user_can_edit_agent(user_id, agent_id, db)` pour les mutations (create/rename/
  toggle/delete/move/upload).
- `_user_can_access_agent(user_id, agent_id, db)` pour la lecture.

Le routeur doit être enregistré dans `main.py` là où les autres routeurs sont inclus.

| Méthode | Chemin                                                   | Rôle                                                        |
|---------|----------------------------------------------------------|-------------------------------------------------------------|
| GET     | `/api/agents/{agent_id}/folders`                         | Liste des dossiers (id, name, is_active, document_count) + compteur « sans dossier » |
| POST    | `/api/agents/{agent_id}/folders`                         | Créer (nom requis, unique par agent, max 100 caractères)    |
| PUT     | `/api/agents/{agent_id}/folders/{folder_id}`             | Renommer **et/ou** changer `is_active` (payload `{name?, is_active?}`) |
| DELETE  | `/api/agents/{agent_id}/folders/{folder_id}`             | Supprimer si vide (409 si le dossier contient des documents) |
| PUT     | `/api/agents/{agent_id}/documents/{document_id}/folder`  | Déplacer (`folder_id` = id cible, ou `null` pour « sans dossier ») |

Détails :
- `MAX_FOLDER_NAME_LENGTH = 100` (comme `company_rag.py`).
- Le `document_count` par dossier est calculé par agrégation
  `group_by(Document.agent_folder_id)` filtrée sur `agent_id` et `document_type='rag'`.
- Le compteur « sans dossier » = documents `rag` de l'agent avec
  `agent_folder_id IS NULL` et `mission_id IS NULL`.
- La validation du dossier cible (move/upload) vérifie qu'il appartient bien à
  l'agent (`_folder_or_404(folder_id, agent_id, db)` → 404 sinon, pas d'id-probing).

### 3. Upload dans un dossier

- `/upload-agent` (`backend/routers/documents.py` ~ligne 675) accepte un paramètre
  form optionnel `folder_id`. S'il est fourni, il est validé (appartenance à
  l'agent) puis propagé :
  `_process_document_background(...)` → `process_document_for_user(...)` →
  `ingest_text_content(...)` via un **nouveau paramètre `agent_folder_id`**.
- Absent → document sans dossier (comportement actuel strictement inchangé).
- `ingest_text_content` / `process_document_for_user` (`backend/rag_engine.py`)
  reçoivent `agent_folder_id` et le positionnent sur la ligne `Document` créée
  (en parallèle du `folder_id` entreprise déjà géré).

### 4. Récupération RAG (contrôle actif/inactif)

Dans `backend/rag_engine.py`, branche `elif agent_id:` (~ligne 918) : exclure les
documents rangés dans un dossier **inactif**. Les documents sans dossier
(`agent_folder_id IS NULL`) et ceux d'un dossier **actif** restent inclus.

```python
inactive_folder_ids = (
    db.query(AgentFolder.id)
    .filter(AgentFolder.agent_id == agent_id, AgentFolder.is_active.is_(False))
)
agent_scope = and_(
    Document.agent_id == agent_id,
    Document.mission_id.is_(None),
    or_(
        Document.agent_folder_id.is_(None),
        Document.agent_folder_id.notin_(inactive_folder_ids),
    ),
)
```

Le reste de la branche (union avec `company_scope` quand `include_company_rag`) est
inchangé. Ce filtre couvre automatiquement le **chat public** d'un companion, qui
passe par la même requête de récupération.

### 5. Frontend — `frontend/pages/sources/[agentId].js`

- `GET /api/agents/{agent_id}/sources` (`backend/routers/sources.py` ~ligne 302)
  enrichi :
  - Nouveau tableau `folders` : `[{id, name, is_active, document_count}]`.
  - Chaque document inclut `agent_folder_id`.
- UI calquée sur le RAG entreprise (`frontend/pages/organization.js`) :
  - Barre/onglets de dossiers + entrée « Sans dossier ».
  - Boutons créer / renommer / supprimer un dossier.
  - **Toggle actif/inactif** par dossier (indique visuellement qu'un dossier inactif
    n'est pas utilisé pour répondre).
  - Sélecteur de dossier à l'upload.
  - Menu « déplacer vers… » sur chaque document.
- Gestion d'état : liste des dossiers, dossier sélectionné, handlers CRUD + toggle +
  move (mêmes patterns que `organization.js` lignes 175-298).

### 6. Tests

Tests backend calqués sur `backend/tests/test_company_rag_folders.py` :

- CRUD dossiers (créer, renommer, toggle is_active, supprimer).
- Unicité du nom par agent (409).
- Upload d'un document dans un dossier.
- Déplacement d'un document (vers un dossier / vers « sans dossier »).
- Suppression bloquée si le dossier n'est pas vide (409).
- Permissions : un utilisateur sans droit d'édition sur l'agent est rejeté.
- **Filtrage de récupération** : un document dans un dossier inactif est exclu des
  résultats RAG ; un document sans dossier ou dans un dossier actif est inclus.

## Fichiers touchés

| Fichier                                      | Changement                                                       |
|----------------------------------------------|-----------------------------------------------------------------|
| `backend/database.py`                        | Modèle `AgentFolder`, colonne `Document.agent_folder_id`, `ensure_columns()`, `TENANT_TABLES` |
| `backend/routers/agent_folders.py`           | **Nouveau** routeur (CRUD dossiers + move)                      |
| `backend/main.py`                            | Enregistrer le nouveau routeur                                  |
| `backend/routers/documents.py`               | `/upload-agent` accepte `folder_id`, propagation au background  |
| `backend/rag_engine.py`                      | `agent_folder_id` dans `ingest_text_content` / `process_document_for_user` ; filtre récupération |
| `backend/routers/sources.py`                 | `folders` + `agent_folder_id` dans la réponse sources           |
| `frontend/pages/sources/[agentId].js`        | UI dossiers (tabs, CRUD, toggle, upload, move)                  |
| `backend/tests/test_agent_folders.py`        | **Nouveaux** tests                                              |

## Hors périmètre (YAGNI)

- Pas de sous-dossiers / hiérarchie imbriquée (dossiers à plat, comme le RAG entreprise).
- Pas de liste de sélection de dossiers sur l'agent (le contrôle se fait par `is_active`).
- Pas de migration forcée des documents existants vers un dossier par défaut (ils
  restent « sans dossier »).
