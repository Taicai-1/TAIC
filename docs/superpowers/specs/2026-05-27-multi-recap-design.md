# Multi-Recap Feature Design

**Date:** 2026-05-27
**Status:** Approved
**Approach:** A - Nouvelle table Recap avec table de liaison RecapDocument

## Context

Actuellement, chaque agent a un seul recap configurable (frequence, heure, prompt, destinataires). Les emails recus via le @ du companion creent des documents traceability inclus automatiquement dans ce recap unique. Les conversations et pages Notion sont aussi toutes incluses.

## Objectif

Permettre la creation de plusieurs recaps independants par agent, chacun avec sa propre configuration complete et ses propres documents.

## Regles metier

- Chaque recap est totalement independant : nom, frequence, heure, prompt, destinataires
- Les emails recus via le @ du companion vont dans TOUS les recaps par defaut
- L'utilisateur peut toggle on/off chaque document par recap dans l'UI
- Toutes les conversations sont incluses dans tous les recaps (filtrage prevu pour une version future)
- Toutes les pages Notion sont incluses dans tous les recaps

---

## 1. Modele de donnees

### Nouvelle table `recaps`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer, PK | |
| `agent_id` | FK -> agents.id, NOT NULL | Agent parent |
| `company_id` | FK -> companies.id, nullable | Tenant isolation (RLS) |
| `name` | String(100), NOT NULL | Nom du recap (ex: "Recap Ventes") |
| `enabled` | Boolean, default True | Active/desactive |
| `frequency` | String(20), default "weekly" | daily / weekly / monthly |
| `hour` | Integer, default 9 | Heure d'envoi (0-23) |
| `prompt` | Text, nullable | Prompt personnalise |
| `recipients` | Text, nullable | JSON array d'emails supplementaires |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

### Nouvelle table `recap_documents`

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | Integer, PK | |
| `recap_id` | FK -> recaps.id, ON DELETE CASCADE | |
| `document_id` | FK -> documents.id, ON DELETE CASCADE | |
| `included` | Boolean, default True | Toggle on/off |
| `company_id` | FK -> companies.id, nullable | RLS |

Contrainte unique sur `(recap_id, document_id)`.

### Modification de `weekly_recap_logs`

- Ajout colonne `recap_id` FK -> recaps.id, nullable (pour migration progressive)
- Le champ `agent_id` reste pour query rapide

### Champs deprecies sur Agent

Les champs suivants deviennent obsoletes apres migration et seront supprimes dans un second temps :
- `weekly_recap_enabled`
- `weekly_recap_prompt`
- `weekly_recap_recipients`
- `recap_frequency`
- `recap_hour`

---

## 2. API Endpoints

### CRUD Recaps

| Methode | Route | Description |
|---------|-------|-------------|
| `GET` | `/api/agents/{agent_id}/recaps` | Liste tous les recaps de l'agent |
| `POST` | `/api/agents/{agent_id}/recaps` | Creer un nouveau recap |
| `PUT` | `/api/agents/{agent_id}/recaps/{recap_id}` | Modifier un recap |
| `DELETE` | `/api/agents/{agent_id}/recaps/{recap_id}` | Supprimer un recap |

### Gestion des documents par recap

| Methode | Route | Description |
|---------|-------|-------------|
| `GET` | `/api/recaps/{recap_id}/documents` | Liste les docs du recap avec statut `included` |
| `PUT` | `/api/recaps/{recap_id}/documents/{document_id}` | Toggle `included` on/off |

### Actions recap

| Methode | Route | Description |
|---------|-------|-------------|
| `POST` | `/api/recaps/{recap_id}/preview` | Preview HTML du recap |
| `POST` | `/api/recaps/{recap_id}/send` | Envoi immediat |
| `POST` | `/api/weekly-recap/trigger` | Inchange - itere sur les Recaps au lieu des Agents |

### Retrocompatibilite

Les anciens endpoints (`/agents/{id}/recap-preview`, `/agents/{id}/recap-send`) restent fonctionnels temporairement et redirigent vers le premier recap de l'agent.

---

## 3. Logique metier

### Creation de RecapDocuments a l'ingestion d'email

Quand un email arrive via `/api/emails/ingest` :

1. Le document traceability est cree comme aujourd'hui
2. Query tous les `Recap` de l'agent concerne
3. Pour chaque recap, creer une entree `RecapDocument(recap_id, document_id, included=True)`

### Scheduler (`recap_scheduler.py`)

Le scheduler itere sur les **Recaps** au lieu des **Agents** :

1. Query tous les Recap avec `enabled=True`
2. Pour chaque Recap, verifier `_is_due(recap, now)`
3. Si due -> `process_recap(recap, db)`

### Generation du recap (`weekly_recap.py`)

`process_recap(recap, db)` remplace `process_agent_recap(agent, db)` :

1. **Conversations** : fetch toutes les conversations de `recap.agent_id` des N derniers jours
2. **Documents** : fetch les documents traceability filtres par `RecapDocument` — uniquement ceux ou `included=True` pour ce recap, crees dans les N derniers jours
3. **Notion** : fetch toutes les pages Notion de l'agent
4. **Prompt** : utilise `recap.prompt` (ou prompt par defaut si null)
5. **LLM call** -> HTML -> envoi aux destinataires du recap (`recap.recipients` + owner)
6. **Email** : sujet du mail inclut le nom du recap : "Recap {recap.name} - {agent_name}"
7. **Log** : cree un `WeeklyRecapLog` avec `recap_id` renseigne

### Migration des donnees existantes

Pour chaque agent qui a `weekly_recap_enabled=True` :

1. Creer un `Recap` avec les valeurs actuelles (frequency, hour, prompt, recipients)
2. Nom par defaut : "Recap principal"
3. Creer des `RecapDocument(included=True)` pour tous les documents traceability existants de l'agent

---

## 4. Frontend

### Vue liste des recaps (dans la config de l'agent)

- Header "Recaps" avec bouton "+ Nouveau recap"
- Chaque recap est une carte/accordeon : nom, frequence, statut, nombre de docs
- Clic sur une carte -> ouvre le detail/edition

### Vue detail d'un recap (modale ou accordeon deplie)

- Champ nom (text input)
- Toggle active/desactive
- Selecteur frequence (daily/weekly/monthly)
- Selecteur heure (0-23)
- Textarea prompt personnalise
- Gestion des destinataires (input email + chips)
- Bouton "Envoyer maintenant"
- Bouton supprimer

### Section Documents dans le detail du recap

- Liste de tous les documents traceability de l'agent
- Chaque doc a un toggle on/off (champ `included`)
- Indicateur visuel : docs inclus vs exclus
- Possibilite de filtrer/chercher

### State management

```
recaps: []                    // Liste des recaps de l'agent courant
currentRecap: null            // Recap en cours d'edition
recapDocuments: []            // Docs du recap courant avec statut included
```

Chargement au moment ou l'utilisateur selectionne un agent : `GET /api/agents/{agent_id}/recaps`. Detail des docs charge a l'ouverture d'un recap specifique.

### Flux de creation

1. Clic "+ Nouveau recap"
2. Formulaire avec nom + settings de base
3. POST `/api/agents/{agent_id}/recaps`
4. Tous les docs existants automatiquement associes (included=True) cote backend
5. L'utilisateur ajuste les docs dans la section Documents

---

## 5. Edge cases

### Suppression d'un recap

- CASCADE supprime les `RecapDocument` associes
- Les documents eux-memes restent dans le RAG
- Les `WeeklyRecapLog` sont conserves pour l'historique

### Suppression d'un document

- CASCADE sur `RecapDocument.document_id` nettoie les associations
- Aucun impact sur les recaps

### Agent sans recap

- Le scheduler l'ignore
- L'UI affiche un etat vide avec bouton "+ Nouveau recap"

### Recap sans documents

- Se genere avec conversations + Notion uniquement
- Si aucune donnee du tout, statut `no_data`

### Multi-tenant (RLS)

- `Recap` et `RecapDocument` ont un `company_id`
- Le scheduler utilise `app.service_bypass`

### Nouveaux documents apres creation du recap

- Email ingest cree un `RecapDocument(included=True)` pour chaque recap existant de l'agent
- Creation d'un recap apres qu'un document existe : le backend cree les `RecapDocument(included=True)` pour tous les docs traceability existants
