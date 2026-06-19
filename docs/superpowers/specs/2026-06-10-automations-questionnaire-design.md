# Refonte questionnaire : page Automatisations

**Date :** 2026-06-10
**Statut :** validé

## Contexte et objectif

La feature questionnaire a été livrée comme un type de companion (`agent.type == "questionnaire"`). La revue de code a confirmé qu'elle est inutilisable en l'état (tous les endpoints admin plantent, export RAG cassé, modale d'export sur une route inexistante, page répondant cassée sur les cas limites) et le couplage avec les agents complique tout.

Décision : **supprimer entièrement** le type de companion questionnaire et **reconstruire** la feature comme une entité autonome, dans une nouvelle page **Automatisations** conçue pour accueillir d'autres automatisations à l'avenir.

Choix validés avec l'utilisateur :
- Expérience répondant : **formulaire classique** (toutes les questions visibles, soumission unique) — plus de chat ni de LLM côté répondant.
- Données existantes : **repartir de zéro** (drop des tables actuelles, aucune migration de données).
- Types de questions : les 4 actuels — `open`, `single_choice`, `multiple_choice`, `rating`.
- Accès : comme les companions — tout utilisateur connecté de la company (isolation `company_id` + RLS).

## 1. Suppression de l'existant

### Fichiers supprimés
- `backend/routers/questionnaires.py`
- `backend/schemas/questionnaires.py`
- `frontend/components/questionnaire/` (QuestionCard, QuestionBuilder, InvitationsTab, ResponsesTab, ExportModal)
- `frontend/pages/questionnaire/[token].js` (réécrit à neuf, voir §4)
- `frontend/public/locales/en/questionnaire.json` et `frontend/public/locales/fr/questionnaire.json` (réécrits à neuf)

### Références purgées
- `backend/database.py` : modèles `QuestionnaireQuestion`, `QuestionnaireResponse`, `QuestionnaireAnswer` ; entrées `welcome_message`/`closing_message` dans `ensure_columns()` ; entrées RLS des anciennes tables ; colonnes `welcome_message` et `closing_message` du modèle `Agent`.
- `backend/routers/public.py` : les 3 endpoints `/questionnaire/{token}` (GET, /answer, /complete) et leurs imports.
- `backend/routers/agents.py` : toutes les branches `type == "questionnaire"` (create, update, override `llm_provider`, gestion et sérialisation de `welcome_message`/`closing_message`).
- `backend/validation.py` : `questionnaire` retiré du pattern du champ `type`.
- `backend/email_service.py` : `send_questionnaire_invitation_email()` réécrite (voir §3).
- `backend/main.py` : import et enregistrement de l'ancien router questionnaires.
- `backend/helpers/agent_helpers.py` : entrées `questionnaire` dans les maps provider/model si présentes.
- `frontend/pages/agents.js` : imports des composants questionnaire, type `questionnaire` dans `AGENT_TYPES_CONFIG` et le dropdown, champs `welcome_message`/`closing_message` du formulaire (état initial et resets), namespace i18n, les 3 onglets questionnaire.
- `frontend/pages/index.js` : envoi de `welcome_message`/`closing_message` dans le flux d'édition.
- `frontend/public/locales/{en,fr}/agents.json` et `chat.json` : clés liées au questionnaire.
- Recherche finale `grep -ri questionnaire` sur backend/ et frontend/ pour garantir qu'il ne reste rien d'autre que la nouvelle implémentation.

### Migration base de données
Migration alembic `0006_automations_questionnaires` :
- DROP des tables `questionnaire_answers`, `questionnaire_responses`, `questionnaire_questions` (dans cet ordre, FK obligent).
- DROP des colonnes `agents.welcome_message` et `agents.closing_message`.
- CREATE des 4 nouvelles tables (§2).
- Politiques RLS `tenant_isolation` sur les 4 nouvelles tables, via le mécanisme existant (`ensure_rls_policies()` dans `database.py`, mis à jour).

## 2. Modèle de données

Entité racine autonome, plus aucun lien avec `agents`.

**`questionnaires`**
- `id` PK, `company_id` FK companies (NOT NULL), `user_id` FK users (créateur, NOT NULL)
- `title` VARCHAR(255) NOT NULL, `description` TEXT nullable
- `created_at`, `updated_at`

**`questionnaire_questions`**
- `id` PK, `questionnaire_id` FK questionnaires ON DELETE CASCADE, `company_id`
- `question_text` TEXT NOT NULL
- `question_type` VARCHAR(20) NOT NULL — `open` | `single_choice` | `multiple_choice` | `rating`
- `options` TEXT (JSON) nullable — liste de choix pour single/multiple_choice, `{"min":1,"max":5}` pour rating, NULL pour open
- `position` INT NOT NULL, `required` BOOL NOT NULL DEFAULT true
- `created_at`

**`questionnaire_responses`** (une ligne = une invitation)
- `id` PK, `questionnaire_id` FK ON DELETE CASCADE, `company_id`
- `respondent_email` VARCHAR(255) NOT NULL, `respondent_name` VARCHAR(255) nullable
- `token` VARCHAR(64) UNIQUE NOT NULL (généré via `secrets.token_urlsafe`)
- `status` VARCHAR(20) NOT NULL DEFAULT `pending` — `pending` | `completed` (plus de `in_progress` : soumission unique)
- `email_sent` BOOL NOT NULL DEFAULT false — corrige le bug « email échoué = invitation perdue à jamais »
- `invited_at`, `completed_at` nullable

**`questionnaire_answers`**
- `id` PK, `response_id` FK questionnaire_responses ON DELETE CASCADE, `question_id` FK questionnaire_questions ON DELETE CASCADE, `company_id`
- `answer_text` TEXT — pour multiple_choice : JSON array sérialisé ; pour rating : la note en texte
- `answered_at`

## 3. API backend

### Router admin : `backend/routers/automations.py`
Auth : `user_id: str = Depends(verify_token)` (le pattern correct utilisé partout ailleurs — corrige le bug `user["user_id"]`). Scoping : toutes les requêtes filtrent par `company_id` de l'utilisateur (helper interne `_get_questionnaire(questionnaire_id, company_id, db)` → 404 sinon). Validation par schémas pydantic en signature d'endpoint (422 natifs, pas de `payload: dict`).

- `POST /api/automations/questionnaires` — corps `{title, description?, questions: [{question_text, question_type, options?, position, required}]}`. Crée le questionnaire et ses questions.
- `GET /api/automations/questionnaires` — liste avec compteurs agrégés (nb questions, nb invités, nb complétés) en requêtes groupées (pas de N+1).
- `GET /api/automations/questionnaires/{id}` — détail avec questions ordonnées par position.
- `PUT /api/automations/questionnaires/{id}` — met à jour titre/description/questions (stratégie replace : on supprime et recrée les questions ; refusé en 409 si des réponses complétées existent, pour ne pas désynchroniser réponses et questions).
- `DELETE /api/automations/questionnaires/{id}` — cascade sur questions/réponses/answers.
- `POST /api/automations/questionnaires/{id}/invite` — corps `{recipients: [{email, name?}]}`. Dédoublonnage en une seule requête `respondent_email.in_()`, création des tokens, envoi des emails via `BackgroundTasks` (l'endpoint répond immédiatement), `email_sent` mis à jour par la tâche de fond. Retourne invités/ignorés.
- `POST /api/automations/questionnaires/{id}/responses/{response_id}/resend` — régénère l'envoi pour une invitation `pending` (corrige l'impossibilité actuelle de ré-inviter).
- `GET /api/automations/questionnaires/{id}/responses?status=&limit=&offset=` — paginé (défaut 50), avec compteurs.
- `GET /api/automations/questionnaires/{id}/responses/{response_id}` — détail avec answers jointes aux questions.
- `DELETE /api/automations/questionnaires/{id}/responses/{response_id}` — supprime une invitation/réponse.
- `POST /api/automations/questionnaires/{id}/export` — corps `{response_ids: [...], target_agent_id}`. Vérifie que l'agent cible appartient à la company et est de type `conversationnel` ou `actionnable`. Construit un markdown par réponse (titre, répondant, date, Q/R) puis appelle **`rag_engine.ingest_text_content()`** — le pipeline d'ingestion existant (Document/DocumentChunk corrects, `embedding_vec`). Corrige l'export actuellement cassé.

Enregistrement dans `main.py` comme les autres routers.

### Endpoints publics : `backend/routers/public.py`
- `GET /questionnaire/{token}` — si complété : `{completed: true}` ; sinon `{completed: false, title, description, questions: [...]}` (sans informations internes : pas d'ids company, pas d'email).
- `POST /questionnaire/{token}/submit` — corps `{respondent_name?, answers: [{question_id, value}]}`. Valide : token existant (404), pas déjà complété (409), toutes les questions `required` répondues (422), `question_id` appartenant au questionnaire, valeur conforme au type (choix dans les options, note dans la plage). Insère toutes les answers et passe la réponse en `completed` dans une seule transaction.

### Email : `backend/email_service.py`
`send_questionnaire_invitation_email(to_email, questionnaire_title, company_name, respondent_name, questionnaire_url)` — même template TAIC brandé que l'actuel, le titre du questionnaire remplaçant le nom de l'agent.

## 4. Frontend

### Page `frontend/pages/automations.js`
- Entrée **« Automatisations »** ajoutée à la navigation (`components/Layout.js`), visible pour tout utilisateur connecté.
- Auth via `useAuth()`, API via `lib/api` (patterns existants).
- Barre d'onglets extensible (structure tableau `TABS = [...]`) ; seul onglet actuel : **Questionnaires**. Les futures automatisations s'ajouteront comme nouveaux onglets.
- L'onglet Questionnaires bascule entre vue **liste** et vue **détail**, synchronisée avec l'URL par query params (`?questionnaire=<id>`) pour permettre les liens directs.

### Composants `frontend/components/automations/questionnaire/`
- **`QuestionnaireList.js`** — cartes (titre, nb questions, nb réponses/invités, date) + bouton « Nouveau questionnaire » ; suppression avec confirmation.
- **`QuestionnaireEditor.js`** — création/édition : titre, description, liste de `QuestionCard` avec ajout/suppression/réordonnancement.
- **`QuestionCard.js`** — édition d'une question : texte, sélecteur de type (4 types), options dynamiques selon le type, toggle requis.
- **`QuestionnaireDetail.js`** — sous-onglets **Questions** (éditeur), **Invitations**, **Réponses**.
- **`InvitationsTab.js`** — saisie d'emails en lot (textarea, séparateur virgule/retour ligne), envoi, tableau des invités avec statut (`pending`/`completed`, badge email non envoyé) et bouton « Renvoyer ».
- **`ResponsesTab.js`** — liste paginée des réponses complétées, détail Q/R au clic, sélection multiple + bouton « Exporter vers un companion ».
- **`ExportModal.js`** — sélection du companion cible via `GET /agents` (le chemin correct), confirmation, appel export.
- Constantes partagées (couleurs de statut, labels de types de questions) dans un module commun du dossier pour éviter la duplication actuelle.

### Page publique `frontend/pages/questionnaire/[token].js` (réécrite)
Formulaire classique sans auth :
- En-tête : titre + description.
- Toutes les questions visibles, rendu par type : textarea (open), radios (single_choice), checkboxes (multiple_choice), étoiles (rating).
- Validation client des requis, messages d'erreur par question, un seul bouton « Envoyer ».
- États : chargement, token invalide (message clair), déjà complété (`completed: true` → écran dédié), succès après soumission (écran de remerciement statique).

### i18n
- Nouveaux `frontend/public/locales/{fr,en}/questionnaire.json` (page publique) et namespace `automations` (page admin).
- Purge des clés questionnaire dans `agents.json` et `chat.json`.

## 5. Gestion d'erreurs et garde-fous

- Validation pydantic en signature (jamais `payload: dict`) → 422 détaillés.
- Échec d'envoi d'email : l'invitation reste en base avec `email_sent = false`, visible dans l'UI, ré-envoyable — jamais bloquante.
- Export RAG : transaction unique via le pipeline existant ; erreurs remontées en 4xx/5xx explicites, pas d'`except` silencieux.
- Endpoints publics : aucune fuite d'information interne ; la surface non authentifiée se limite aux deux routes token.

## 6. Tests

`backend/tests/test_questionnaires.py`, sur le pattern existant (`conftest.py` + `factories.py`, cf. `test_endpoints_teams.py`) :
- CRUD questionnaire + questions (création avec les 4 types, PUT refusé en 409 si réponses complétées, DELETE cascade).
- Invite : dédoublonnage, création des tokens, `email_sent` sur échec simulé, resend.
- Public : GET token invalide/valide/complété ; submit avec requis manquant (422), double soumission (409), valeurs hors options.
- Export : agent cible d'une autre company refusé, appel correct à `ingest_text_content` (mocké).

## Hors scope

- Les bugs confirmés par la revue de code hors feature questionnaire (migration RLS des équipes, routing orchestrateur non-Mistral, proposition d'action enchaînée, blocage de l'event loop, etc.) — à traiter séparément.
- Autres automatisations futures : seule la structure d'onglets extensible est prévue, aucune autre automatisation n'est implémentée.
- Sauvegarde partielle des réponses côté répondant (soumission unique uniquement).
