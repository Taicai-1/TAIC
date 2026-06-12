# Feature Missions : page Automatisations

**Date :** 2026-06-12
**Statut :** validé

## Contexte et objectif

Nouvelle automatisation « Mission » : l'utilisateur définit un **objectif précis**, uploade un **planning** (événements datés), ajoute des **documents sources** (comme pour le RAG) et connecte un **companion** à la mission. Chaque semaine, le companion regarde les événements de la semaine qui arrive et produit un **récap** orienté objectif, enrichi par les docs sources, avec un bref rappel de la semaine écoulée.

Choix validés avec l'utilisateur :
- **Ingestion du planning :** upload libre (PDF, Excel, CSV, Word…) + parsing LLM **une seule fois à l'upload** en événements structurés stockés en base, avec écran de validation/édition avant insertion. Le récap ne relit jamais le fichier brut : requête SQL sur les dates.
- **Fenêtre du récap :** semaine à venir analysée en détail + bref rappel de la semaine passée.
- **Livraison :** email au créateur + historique consultable in-app.
- **Déclenchement :** jour et heure configurables par mission (défaut lundi 8h) + bouton « Générer maintenant ».
- **Docs sources :** silotés à la mission (pas injectés dans le RAG général du companion).
- **Rôle du companion :** génère le récap (personnalité + provider LLM) **et** chat dédié dans le contexte de la mission.
- **Portée :** plusieurs missions par utilisateur, un companion peut servir plusieurs missions ; missions **privées au créateur** (`user_id`), isolation tenant `company_id` + RLS.
- **Architecture :** réutilisation maximale de l'existant (pipeline documents, scheduler APScheduler, email_service, Conversation/Message).

## 1. Modèle de données

Migration alembic `0007_missions`.

**`missions`** (nouvelle table)
- `id` PK, `company_id` FK companies (NOT NULL), `user_id` FK users (créateur, NOT NULL)
- `agent_id` FK agents ON DELETE SET NULL, nullable — le companion connecté ; une mission peut exister sans companion (mais le récap et le chat exigent un companion)
- `name` VARCHAR(255) NOT NULL, `objective` TEXT NOT NULL
- `status` VARCHAR(20) NOT NULL DEFAULT `active` — `active` | `archived` (archivée = plus de récap planifié, lecture seule)
- `recap_enabled` BOOLEAN NOT NULL DEFAULT true
- `recap_weekday` INTEGER NOT NULL DEFAULT 0 — 0 = lundi … 6 = dimanche
- `recap_hour` INTEGER NOT NULL DEFAULT 8 — heure Europe/Paris, comme les Recaps existants
- `created_at`, `updated_at`

**`mission_events`** (nouvelle table)
- `id` PK, `mission_id` FK missions ON DELETE CASCADE, `company_id`
- `event_date` DATE NOT NULL, `title` VARCHAR(255) NOT NULL, `description` TEXT nullable
- `source` VARCHAR(10) NOT NULL DEFAULT `upload` — `upload` | `manual`
- `created_at`
- Index composite `(mission_id, event_date)`

**`mission_recaps`** (nouvelle table) — historique in-app **et** anti-doublon scheduler
- `id` PK, `mission_id` FK missions ON DELETE CASCADE, `company_id`
- `period_start` DATE NOT NULL, `period_end` DATE NOT NULL — la fenêtre « semaine à venir » couverte
- `content` TEXT nullable — le récap en markdown
- `status` VARCHAR(20) NOT NULL — `success` | `error` | `no_data`
- `error_message` TEXT nullable
- `email_sent` BOOLEAN NOT NULL DEFAULT false
- `trigger` VARCHAR(10) NOT NULL DEFAULT `scheduled` — `scheduled` | `manual`
- `created_at`

**Colonnes ajoutées**
- `documents.mission_id` FK missions ON DELETE CASCADE, nullable, index — même pattern que `agent_id` nullable. Un document appartient à un agent OU à une mission OU à l'organisation.
- `conversations.mission_id` FK missions ON DELETE CASCADE, nullable, index — conversations du chat mission.

**RLS :** politiques `tenant_isolation` sur les 3 nouvelles tables via `ensure_rls_policies()` existant. Colonnes ajoutées via la migration + `ensure_columns()` si le pattern l'exige.

## 2. Ingestion du planning

### Parsing (preview, sans écriture)
`POST /api/automations/missions/{id}/planning/parse` — multipart, un fichier.
1. Extraction texte via `file_loader.py` existant (PDF, DOCX, XLSX, CSV, TXT).
2. Un appel LLM (provider du companion connecté, sinon Mistral) avec consigne de sortie JSON strict : `[{"date": "YYYY-MM-DD", "title": str, "description": str|null}]`. Le prompt impose : dates au format ISO, année courante par défaut si absente du document, ignorer tout ce qui n'est pas un événement daté.
3. Validation Pydantic de chaque entrée (date parseable, title non vide). Les entrées invalides sont écartées et comptées.
4. Réponse : `{events: [...], skipped: int}` — **rien n'est écrit en base**. Si 0 événement, erreur explicite invitant à la saisie manuelle.

### Validation utilisateur (écriture)
`POST /api/automations/missions/{id}/events/bulk` — body `{events: [...], replace_upload: bool}`.
- L'utilisateur a pu corriger dates/titres et supprimer des lignes dans l'écran de validation frontend.
- `replace_upload=true` : supprime d'abord les événements `source='upload'` existants (les `manual` sont conservés). Proposé par le frontend lors d'un re-upload.
- Insère les événements avec `source='upload'`.

### CRUD manuel
- `POST /api/automations/missions/{id}/events` (source=`manual`), `PUT /events/{event_id}`, `DELETE /events/{event_id}`.
- `GET /api/automations/missions/{id}/events?from=&to=` — liste triée par date, filtre optionnel.

## 3. Documents sources

`POST /api/automations/missions/{id}/documents` — multipart. Réutilise le pipeline de `/upload-agent` (`routers/documents.py`) : extraction `file_loader`, chunking + embeddings pgvector dans `rag_engine`, traitement async via Redis (`doc_task:{uuid}`, polling `/upload-status/{task_id}`) avec fallback synchrone. Seule différence : le `Document` est créé avec `mission_id` (et `agent_id=NULL`). La logique commune est factorisée en helper partagé plutôt que dupliquée.

`GET /api/automations/missions/{id}/documents` et `DELETE .../documents/{doc_id}` — liste et suppression (cascade chunks, GCS comme l'existant).

Le retrieval RAG côté mission filtre les chunks sur les documents `mission_id = X` uniquement. Les documents de mission n'apparaissent jamais dans le RAG général du companion.

## 4. Génération du récap

### Scheduler
Dans `recap_scheduler.py`, le tick horaire existant appelle en plus `_run_scheduled_mission_recaps()` :
- Missions `status='active'`, `recap_enabled=true`, `agent_id` non NULL.
- `_is_mission_due(mission, now)` : `now.weekday() == recap_weekday` ET `now.hour == recap_hour` (Europe/Paris) ET dernier `mission_recaps` avec statut `success`/`no_data` et `trigger='scheduled'` vieux de plus de 6 jours (anti-doublon, même pattern que `_is_recap_due`).

### `process_mission_recap(mission, db, trigger)` — nouveau module `backend/mission_recap.py`
1. **Fenêtre glissante** depuis la date d'exécution `D` : à venir = `[D, D+6]`, rappel = `[D-7, D-1]`. Requêtes SQL sur `mission_events.event_date`.
2. **Enrichissement RAG** : pour chaque événement à venir, retrieval vectoriel sur les chunks des documents de la mission (requête = `title + description`), top-k limité ; budget global de contexte plafonné.
3. **Prompt** au LLM du companion (son provider/personnalité via les clients existants) : objectif de la mission + bref rappel des événements passés + événements à venir avec leurs extraits docs. Sortie attendue : récap markdown structuré — ① rappel express de la semaine passée, ② semaine à venir analysée sous l'angle de l'objectif (priorités, points d'attention, liens avec les docs).
4. **Persistance** : ligne `mission_recaps` (`period_start=D`, `period_end=D+6`, `content`, `status`, `trigger`).
5. **Email** : si `trigger='scheduled'` et `status='success'`, envoi au créateur via `email_service.send_email` (sujet : nom de la mission + période), puis `email_sent=true`. Aucun événement à venir → `status='no_data'`, pas d'appel LLM, pas d'email. Erreur LLM → `status='error'` + `error_message`, pas d'email.

### Génération manuelle
`POST /api/automations/missions/{id}/recaps/generate` : appelle `process_mission_recap(trigger='manual')` en synchrone (réponse = le récap). Pas d'email, pas d'impact sur l'anti-doublon du scheduler. Exige un companion connecté et au moins un événement à venir (sinon 400 explicite).

`GET /api/automations/missions/{id}/recaps?limit=&offset=` — historique trié du plus récent au plus ancien.

## 5. Chat mission

`POST /api/automations/missions/{id}/chat` — body `{message, conversation_id?}`. Exige un companion connecté.
- Conversation créée/retrouvée avec `mission_id` (et `agent_id` = companion, pour réutiliser le flux existant).
- Contexte système injecté : objectif de la mission + événements `[D-7, D+7]` + retrieval RAG sur les docs de la mission (pas ceux du companion).
- Réponse générée par le provider/personnalité du companion via le moteur existant ; messages persistés (`Message`).
- `GET /api/automations/missions/{id}/conversations` + récupération des messages via les endpoints conversation existants si compatibles, sinon endpoint dédié minimal.

## 6. Backend — organisation

- `backend/routers/missions.py` — tous les endpoints ci-dessus, préfixe `/api/automations/missions`, pattern de `routers/automations.py` (auth `verify_token`, filtre `user_id` créateur + `company_id`).
- `backend/schemas/missions.py` — Pydantic : MissionCreate/Update, ParsedEvent (date ISO obligatoire), EventsBulk, EventCreate/Update, ChatRequest.
- `backend/mission_recap.py` — `process_mission_recap`, construction du prompt, fenêtres de dates.
- `backend/recap_scheduler.py` — ajout `_is_mission_due` + `_run_scheduled_mission_recaps` dans le tick.
- Enregistrement du router dans `main.py`.

**Accès :** une mission n'est visible/modifiable que par son créateur (`user_id`), contrairement aux questionnaires (company-wide). 404 si la mission n'appartient pas à l'utilisateur.

## 7. Frontend

`frontend/pages/automations.js` : ajout de l'onglet `missions` (icône `Target` de lucide-react).

`frontend/components/automations/missions/` (pattern questionnaire) :
- `MissionsTab.js` — fetch liste, route List/Editor/Detail, query params.
- `MissionList.js` — cartes (nom, objectif tronqué, companion, date du dernier récap), bouton créer, suppression avec confirmation.
- `MissionEditor.js` — création/édition : nom, objectif (textarea), dropdown companion (fetch des agents de l'utilisateur).
- `MissionDetail.js` — sous-onglets : `planning`, `documents`, `recaps`, `chat`, `settings`.
- `PlanningTab.js` — upload du planning → écran de validation des événements parsés (table éditable : date, titre, description, suppression de ligne ; option « remplacer le planning précédent ») → validation ; liste des événements (à venir / passés) avec CRUD manuel.
- `DocumentsTab.js` — upload (polling `/upload-status` comme l'existant), liste, suppression.
- `RecapsTab.js` — historique des récaps (rendu markdown via le renderer existant), bouton « Générer maintenant » avec spinner, badges de statut.
- `ChatTab.js` — chat avec le companion dans le contexte mission, réutilise les composants de conversation existants autant que possible.
- `SettingsTab.js` — recap_enabled, jour/heure, changer de companion, archiver, supprimer.

**i18n :** section `missions.*` dans `frontend/public/locales/{fr,en}/automations.json`.

## 8. Gestion d'erreurs

- Parsing : fichier illisible, LLM hors format ou 0 événement → message clair, l'utilisateur peut saisir manuellement. Le JSON LLM est parsé défensivement (extraction du bloc JSON, retry une fois en cas d'échec de parse).
- Companion supprimé → `agent_id` passe à NULL (SET NULL) ; récap planifié sauté avec log, l'UI invite à reconnecter un companion.
- Mission archivée → exclue du scheduler, endpoints d'écriture refusés (400), lecture seule.
- Récap : toute erreur est persistée dans `mission_recaps` (`status='error'`) — visible in-app, jamais silencieuse.

## 9. Tests

`backend/tests/` (unitaires, sans DB, pattern existant) :
- Fenêtres de dates du récap (à venir / rappel, bornes incluses).
- `_is_mission_due` : weekday, heure, anti-doublon, mission sans companion.
- Schémas : ParsedEvent rejette dates invalides / titres vides ; EventsBulk.
- Parsing défensif de la sortie LLM (JSON valide, JSON entouré de texte, sortie invalide).

## Hors périmètre (V2 potentielles)

- Partage des missions à l'équipe / destinataires multiples du récap email.
- Connexion calendrier (ICS, Google Calendar) comme source d'événements.
- Statut d'avancement par événement (fait / reporté) alimentant le rappel hebdo.
