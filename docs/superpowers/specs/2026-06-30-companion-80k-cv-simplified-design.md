# Companion IA sur 80 000 CV — Design simplifié (réutilisation de l'existant)

**Date :** 30 juin 2026
**Produit :** TAIC Companion
**Statut :** Proposition technique — validée sur la direction, en attente de revue du spec
**Remplace/allège :** `2026-06-24-companion-80k-cv-design.md` (approche B, version industrialisée)

---

## 1. Objectif et principe directeur

Mettre en place un *companion* spécialisé sur une base de **80 000 CV**, couvrant les **trois
usages** : Q&A sur un candidat, sourcing/matching, et analytics sur la base. C'est une
**fonctionnalité récurrente du produit** (plusieurs clients importeront des bases de CV), pas un
import ponctuel.

**Principe directeur :** ne **rien reconstruire** de ce que TAIC possède déjà. Le travail se réduit
à *brancher une étape d'extraction de métadonnées dans la mécanique d'import de dossier RAG qui
existe déjà*, plus une couche de requête par-dessus le RAG existant.

Ce document conserve l'**approche B** du spec du 24 juin (couche « candidat » structurée + recherche
hybride + sélection d'intention) — indispensable parce que l'**analytics impose des métadonnées
structurées** — mais en **allège radicalement l'implémentation** en réutilisant l'infrastructure
existante.

---

## 2. Ce qui existe déjà et qu'on réutilise tel quel

| Brique existante | Fichier | Réutilisation |
|---|---|---|
| Recherche vectorielle pgvector + index HNSW | `backend/database.py`, `rag_engine.py` | Tient 200K+ vecteurs (80K CV) sans nouvelle infra |
| Import de dossier (squelette générique) | `backend/folder_import.py` (`run_folder_import`) | **Point d'extension central** : boucle sur les fichiers, crée les dossiers à la volée, appelle un callback `ingest_file` injecté, reporte la progression Redis (`import_task:{id}`) |
| Ingestion d'un document | `rag_engine.py` (`ingest_text_content`, `process_document_for_user`) | Chunking + embeddings + écriture `Document`/`DocumentChunk` |
| RAG Entreprise + dossiers | `is_company_rag`, `folder_id`, `CompanyFolder`, router `company_rag.py` | Les CV = `Document` standard dans un dossier « base CV » → le RAG fonctionne déjà dessus |
| Isolation multi-tenant | `company_id` sur documents ET chunks | Base CV cloisonnée par client, gratuitement |
| Multi-fournisseurs IA | `openai_client.py`, `mistral_client.py`, `gemini_client.py` | Petit modèle économique pour l'extraction ; tool-calling pour la sélection d'intention |
| Cache embeddings + RAG | `redis_client.py` | Inchangé |

> Note : `CLAUDE.md` mentionne encore FAISS — obsolète, le code utilise pgvector. Ce design se base
> sur l'état réel du code.

---

## 3. Ce qu'on NE construit PAS (l'économie par rapport au spec du 24 juin)

- ❌ **Pas de Cloud Run Job dédié.** L'ingestion réutilise le mécanisme d'import en tâche de fond
  existant (`run_folder_import` + statut Redis `import_task:{id}`), avec la **limite de 200 fichiers
  levée** pour les dossiers marqués « base CV ».
- ❌ **Pas de table `cv_ingestion_jobs`.** L'idempotence et la reprise sont gratuites : un CV est
  **skippé si son `CandidateProfile` existe déjà**. Relancer l'import ne retraite que ce qui manque.
- ❌ **Pas de routeur d'intention sur-mesure.** On utilise le **tool-calling** de l'agent (déjà
  disponible via les clients LLM intégrés) : trois outils (sourcing / analytics / Q&A) que le modèle
  choisit lui-même selon la question.

---

## 4. Ce qu'on construit (strict nécessaire pour les 3 usages)

### 4.1 Table `candidate_profiles` (la seule vraie nouvelle structure)

Relation 1:1 avec `Document`. On garde une table dédiée plutôt qu'une colonne JSONB sur `Document` :
l'analytics a besoin d'index dédiés, et `Document` est partagé par toutes les fonctionnalités de
TAIC (missions, recaps, intégrations) — on ne le pollue pas.

```
candidate_profiles
  id                INTEGER  PK
  document_id       INTEGER  FK → documents.id  (UNIQUE)        -- 1:1, sert aussi de garde d'idempotence
  company_id        INTEGER  FK → companies.id                  -- isolation tenant
  folder_id         INTEGER  FK → company_folders.id

  full_name         TEXT
  current_title     TEXT
  location          TEXT
  seniority         TEXT      (junior / confirmé / senior / lead …)
  years_experience  INTEGER

  skills            JSONB     → index GIN   (filtre + agrégation)
  languages         JSONB
  education_level   TEXT
  last_company      TEXT

  raw_extraction    JSONB     -- sortie LLM complète : ré-extraire/évoluer sans migration
  extraction_status TEXT      (pending / done / failed)
  extraction_model  TEXT      -- traçabilité du modèle utilisé
  created_at        TIMESTAMP
```

**Index :** GIN sur `skills` ; B-tree sur `years_experience`, `seniority`, `location`, `company_id`.
`document_id` UNIQUE.

**Migration :** suivre le pattern de migration légère déjà utilisé dans `database.py` (cf. la liste
de colonnes ajoutées idempotentes autour de la ligne 1161) plutôt qu'un nouvel outil de migration.

### 4.2 Flag `is_cv_base` sur `CompanyFolder`

Une colonne booléenne `is_cv_base` (défaut `FALSE`) sur `CompanyFolder`. Marque un dossier comme
base CV → déclenche l'extraction de métadonnées à l'ingestion et active les outils CV de l'agent.

### 4.3 Extraction branchée dans le callback `ingest_file`

C'est le cœur de la simplification. Le callback `ingest_file(filename, content, folder_id)` injecté
dans `run_folder_import` reçoit une étape supplémentaire, **uniquement** si le dossier cible est une
base CV :

1. Ingestion standard (inchangée) : extraction texte → chunks → embeddings → `Document` +
   `DocumentChunk`.
2. **Garde d'idempotence** : si un `CandidateProfile` existe déjà pour ce `document_id`, on saute
   l'extraction.
3. **Un seul appel LLM en JSON mode** (schéma strict, function calling) sur le texte du CV → champs
   `full_name, current_title, seniority, years_experience, skills[], languages[], education,
   location, summary`. Petit modèle économique (`mistral-small` / `gpt-4o-mini` / `gemini-flash`).
4. **Normalisation légère des compétences** (minuscule + nettoyage : « ReactJS » → « react ») pour
   des filtres/stats cohérents.
5. Écriture du `CandidateProfile` **dans la même transaction** que le `Document`. En cas d'échec
   d'extraction : `extraction_status = failed`, le `Document` reste valide (le RAG fonctionne quand
   même), ré-extraction possible plus tard.

L'extraction est **purement additive** : aucune modification du chemin de requête RAG, des missions
ou des recaps.

### 4.4 Embeddings par lot

Ajouter `get_embeddings_batch(texts)` (l'API Mistral accepte plusieurs entrées par appel) → 32–64
chunks par appel. Fort gain de débit à 80K CV, **coût identique**. Utilisé par le callback
d'ingestion ; le chemin d'upload unitaire existant peut le réutiliser sans changement de coût.

### 4.5 Ingestion à l'échelle (lever la limite des 200 fichiers)

`folder_import.py` plafonne aujourd'hui à `MAX_IMPORT_FILES = 200` / 200 MB (garde-fou anti-abus
pour l'upload web). Pour un dossier `is_cv_base`, ce plafond est relevé et l'import s'exécute en
**tâche de fond** (mécanisme `BackgroundTasks`/Redis déjà en place), pas dans la requête HTTP.

**Source des fichiers (à confirmer §8) :** pour des bases de cette taille, l'apport via
drag-and-drop navigateur n'est pas réaliste. Options réutilisant l'existant, par ordre de
simplicité : (a) **import depuis un préfixe GCS** que le client alimente, (b) **import Drive**
(l'intégration Drive existe déjà — `drive_folder_id` dans `database.py`). Le format réel des CV
fourni par le client tranche ce point.

### 4.6 Couche de requête — 3 outils de l'agent

Quand l'agent est pointé sur un dossier `is_cv_base`, on lui expose trois outils (via le
tool-calling déjà intégré aux clients LLM). Le modèle choisit selon la question — **pas de routeur
maison**.

- **Sourcing / matching** : recherche vectorielle existante, **dédupliquée par candidat**
  (`GROUP BY document_id`, un résultat = un candidat, pas un extrait) + **filtre SQL** sur
  `candidate_profiles` (compétence via `skills @> '["react"]'`, séniorité, localisation).
  Reranking léger. Sortie : liste classée de candidats + lien CV.
- **Analytics** : ~3–5 helpers SQL paramétrés sur `candidate_profiles` (compter par compétence,
  séniorité moyenne, répartition géographique…). Restitution en langage naturel.
- **Q&A candidat** : identification du candidat puis RAG existant **scopé à ses chunks**.

---

## 5. Architecture (vue d'ensemble)

```
   INGESTION (tâche de fond, réutilise run_folder_import)
   ─────────────────────────────────────────────────────
   Source CV (GCS / Drive)
        │
        ▼  run_folder_import(... ingest_file=callback_cv ...)
   ingest_file (par CV) :
        ├─ ingestion standard → Document + DocumentChunk (pgvector)   [INCHANGÉ]
        └─ si is_cv_base : 1 appel LLM JSON → CandidateProfile         [NOUVEAU]
        progression → Redis import_task:{id}                          [EXISTANT]

   COMPANION (requête, temps réel) — outils de l'agent (tool-calling)
   ──────────────────────────────────────────────────────────────────
   Sourcing  → vecteur dédupliqué par candidat + filtre SQL + rerank
   Analytics → agrégation SQL sur candidate_profiles
   Q&A       → RAG existant scopé au candidat
```

---

## 6. Découpage en phases

| Phase | Livrable | Dépend de |
|---|---|---|
| **1. Fondation** | Table `candidate_profiles` + flag `is_cv_base` + extraction dans le callback + `get_embeddings_batch` + levée du plafond pour les bases CV + **POC 500–1000 CV** | — |
| **2. Sourcing** | Outil sourcing : vecteur dédupliqué par candidat + filtres SQL + reranking | Phase 1 |
| **3. Analytics** | Outil analytics : helpers SQL d'agrégation | Phase 1 |
| **4. Q&A candidat** | Outil Q&A : identification candidat + RAG scopé | Phase 1 |

Les phases 2, 3 et 4 sont **indépendantes entre elles** une fois la Phase 1 livrée. Comparé au spec
du 24 juin, la Phase 1 est bien plus légère : « 1 table + 1 flag + ~50 lignes dans le callback +
embeddings batch », le reste de l'infra étant déjà en place.

---

## 7. Tests

- **Tests unitaires** (sans DB, conformes au pipeline CI actuel — Ruff + pytest) : validation du
  JSON d'extraction, normalisation des compétences, `get_embeddings_batch`, garde d'idempotence
  (skip si `CandidateProfile` existe), dédup par candidat côté sourcing.
- **Tests DB** (comme `test_company_rag_folders.py`, `test_folder_import.py`) : extraction branchée
  dans le callback, écriture transactionnelle, agrégations SQL analytics.
- **POC obligatoire avant le run complet** : ingérer 500–1000 vrais CV pour mesurer **qualité
  d'extraction** et **coût réel** avant de lancer les 80 000.

---

## 8. Points à confirmer avec le client / la direction

1. **Format / source des CV** : PDF individuels ? export ATS ? → tranche entre import GCS (§4.5a) et
   import Drive (§4.5b).
2. **Modèle d'extraction** : `mistral-small` vs `gpt-4o-mini` vs `gemini-flash` — tranché par le POC.
3. **RGPD** (§9).
4. **Priorité des phases** : Sourcing (2) ou Analytics (3) après la fondation ?

---

## 9. RGPD / données personnelles (contrainte transverse)

80 000 CV = grande quantité de données personnelles. À cadrer **avant** ingestion :

- **Base légale & consentement** : le client doit disposer du droit de traiter ces CV.
- **Rétention / purge** : politique de conservation.
- **Contrôle d'accès** : qui interroge l'assistant (déjà cloisonné par `company_id`, à formaliser
  côté rôles).
- **Masquage PII** : option pour ne pas exposer email/téléphone dans les réponses.
- **Droit à l'effacement** : suppression du `Document` → cascade chunks + `CandidateProfile`
  (`ON DELETE CASCADE` sur `document_id`).

---

## 10. Coûts (ordre de grandeur, inchangé vs spec du 24 juin)

- **One-shot d'ingestion 80K CV** : embeddings ~5–10 € + extraction (petit modèle) quelques
  dizaines d'€ → **≈ 30–60 €**. À affiner par le POC.
- **Récurrent par requête** : 1 embedding + 1 appel LLM, déjà mis en cache (Redis). Comparable à une
  requête TAIC actuelle.
- **Infrastructure** : **aucune nouvelle brique** → pas de coût d'infra supplémentaire.

---

## 11. Risques et mitigations

| Risque | Mitigation |
|---|---|
| Qualité d'extraction hétérogène (CV mal formatés/scannés) | POC 500–1000 CV ; `raw_extraction` pour ré-extraire sans tout reprendre ; statut `failed` traçable |
| CV scannés (images sans texte) | Détecté au POC ; OCR éventuel hors périmètre Phase 1 |
| Plafond d'import levé → run long | Tâche de fond + idempotence (skip si `CandidateProfile` existe) → relançable sans tout refaire |
| Quotas / coûts API sous-estimés | Embeddings par lot ; POC avant le run complet |
| RGPD non cadré | Cadrage écrit avant ingestion (§9) |

---

## 12. Prochaine étape

1. Revue de ce spec.
2. Confirmation des points §8 avec le client.
3. Plan d'implémentation détaillé de la **Phase 1** (writing-plans).
4. **POC 500–1000 CV** → mesure qualité + coût réels.
5. Go/No-Go pour l'ingestion complète des 80 000 CV.
