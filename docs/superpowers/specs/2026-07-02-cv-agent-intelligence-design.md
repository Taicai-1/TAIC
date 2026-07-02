# Companion CV — Intelligence conversationnelle (Phases 2-4) — Design

**Date :** 2 juillet 2026
**Produit :** TAIC Companion
**Statut :** Design validé — en attente de plan d'implémentation
**Prérequis :** Phase 1 livrée (table `candidate_profiles` peuplée à l'ingestion). Voir
`2026-06-30-companion-80k-cv-simplified-design.md`.

---

## 1. Objectif

Rendre les **3 usages** du companion CV réellement exploitables **dans le chat** :
- **Sourcing / matching** (Phase 2) — liste classée de candidats distincts, filtrée.
- **Analytics** (Phase 3) — agrégations sur la base (compter, moyenne, répartition).
- **Q&A candidat** (Phase 4) — questions ciblées sur un candidat précis.

Aujourd'hui seul le RAG standard répond (Q&A approximatif, sourcing pauvre, analytics
impossible). Ce design ajoute un **routeur d'intention + 3 outils** par-dessus l'existant.

---

## 2. Ce qui existe déjà et qu'on réutilise

| Brique | Emplacement | Réutilisation |
|---|---|---|
| Réponse conversationnelle | `rag_engine.get_answer(...)` (rag_engine.py:249) et `get_answer_stream(...)` (556) | Point d'injection du routeur CV |
| Endpoints chat | `routers/ask.py` `/ask` (26) et `/ask-stream` (190) | Inchangés (le routage vit dans `get_answer*`) |
| Recherche vectorielle | `rag_engine.search_similar_texts_for_user(query_embedding, user_id, db, top_k, selected_doc_ids, agent_id, company_id, include_company_rag, company_rag_folder_ids, ...)` (902) | Sourcing (groupé par candidat) + Q&A (scopé à 1 doc) |
| Expansion sous-arbre de dossiers | `rag_engine._expand_company_folder_ids(...)` (865) | Résoudre les dossiers effectifs de l'agent |
| Tool-calling multi-fournisseurs | `openai_client.get_chat_response_with_tools(messages, tools, model_id, gemini_only) -> ToolCallResponse` (703) ; `ToolCallResponse{content, tool_call}` (695) | Le routeur d'intention |
| Réponse déterministe JSON | `openai_client.get_chat_response_json(...)` / `get_chat_response(...)` | Génération de la réponse finale NL |
| Embeddings | `mistral_embeddings.get_embedding_fast(text)` | Embedding de la requête de sourcing |
| Données candidat | table `candidate_profiles` (database.py:673) : `full_name, current_title, location, seniority, years_experience, skills(JSONB+GIN), languages(JSONB), education_level, last_company, raw_extraction, ...` | Filtres + agrégations SQL |
| Sélection modèle par agent | `helpers/agent_helpers.resolve_model_id(agent)` (28) | Modèle du routeur + réponse |

---

## 3. Architecture cible

```
  Message utilisateur → /ask(-stream) → get_answer(_stream)
        │
        ▼
  Agent a-t-il un dossier « base CV » dans ses dossiers RAG effectifs ?
        │ non → RAG standard actuel (INCHANGÉ)
        │ oui ▼
  ROUTEUR CV : 1 appel get_chat_response_with_tools([cv_sourcing, cv_analytics, cv_qa])
        │
        ├─ aucun outil appelé → RAG standard (fallback)
        │
        ├─ cv_sourcing(args) → search_candidates() ─┐
        ├─ cv_analytics(args) → aggregate_candidates() ─┤→ résultat structuré
        └─ cv_qa(args)      → find_candidate + RAG ciblé ─┘
                                        │
                                        ▼
                 Réponse finale NL (streamée) à partir du résultat de l'outil
```

**Nouveau module `backend/cv_agent.py`** — une seule responsabilité : l'intelligence CV.
Contient : les 3 schémas d'outils, le routeur, la génération de la réponse finale, et la
couche d'accès données (`search_candidates`, `aggregate_candidates`, `find_candidate_by_name`).
Découpage interne clair : chaque fonction est testable indépendamment.

**Activation** : un helper `agent_has_cv_base_folder(agent, db) -> bool` (résout les dossiers
effectifs via `_expand_company_folder_ids` et vérifie `CompanyFolder.is_cv_base`). Appelé au
début de `get_answer` / `get_answer_stream`. Si faux → aucun changement de comportement.

**Coût** : 2 appels LLM par message sur un companion CV (routage + réponse). Acceptable.

---

## 4. Phase 2 — Sourcing

**Outil** `cv_sourcing(skills: string[], seniority?: string, location?: string, min_years?: int, free_text?: string)`.

**`search_candidates(db, company_id, folder_ids, *, skills=None, seniority=None, location=None, min_years=None, query_embedding=None, limit=10)`** :
1. **Filtre SQL** sur `candidate_profiles` (tenant `company_id` + `folder_id IN folder_ids`) :
   `skills @> '["react"]'` (chaque compétence demandée, normalisée comme à l'ingestion),
   `seniority = …`, `location ILIKE …`, `years_experience >= min_years`. Statut `done` uniquement.
2. **Signal vectoriel** (si `free_text`/`query_embedding`) : recherche pgvector sur les chunks des
   documents candidats, **groupée par `document_id`** (meilleur score par candidat). Réutilise la
   logique de `search_similar_texts_for_user` restreinte à ces documents.
3. **Classement** : score = (nb de critères satisfaits) puis score vectoriel décroissant. Pas de
   rerank LLM en v1.
4. **Sortie** : liste de `{document_id, full_name, current_title, seniority, years_experience,
   matched_skills, score}`, taille ≤ limit.

**Réponse finale** : le LLM présente la liste classée avec justification et référence au CV
(`document_id`). Les sources renvoyées suivent le format standard `{text, document_name, score,
document_id}`.

---

## 5. Phase 3 — Analytics

**Outil** `cv_analytics(metric: "count"|"avg_experience"|"distribution", dimension: "skill"|"seniority"|"location"|"language", filter?: {skill?, seniority?, location?, min_years?})`.

**`aggregate_candidates(db, company_id, folder_ids, *, metric, dimension, filter=None)`** :
- **SQL construit côté serveur à partir de dimensions/métriques WHITELISTÉES** — jamais de SQL
  libre issu du LLM. `metric`/`dimension` mappés à des fragments SQL fixes ; `filter` appliqué en
  clauses paramétrées.
  - `count` + `dimension=skill` → `COUNT` par compétence via `jsonb_array_elements_text(skills)`.
  - `avg_experience` → `AVG(years_experience)` (éventuellement filtré).
  - `distribution` + `dimension=seniority|location|language` → `COUNT ... GROUP BY`.
- Toujours borné à `company_id` + `folder_ids` + `extraction_status='done'`.
- **Sortie** : `{metric, dimension, rows: [{key, value}, ...], total}`.

**Réponse finale** : le LLM rend les chiffres en langage naturel + éventuellement un petit tableau
texte. Pas de génération de graphiques en v1.

---

## 6. Phase 4 — Q&A candidat

**Outil** `cv_qa(candidate_name: string, question: string)`.

**`find_candidate_by_name(db, company_id, folder_ids, name) -> list[{document_id, full_name}]`** :
- Match sur `full_name` (`ILIKE %name%`), borné tenant + dossiers. Retourne les correspondances.
- 0 → la réponse finale indique « aucun candidat de ce nom ». >1 → la réponse demande de préciser
  (liste les homonymes). 1 → on continue.

**Traitement** : RAG ciblé — `search_similar_texts_for_user(..., selected_doc_ids=[document_id])`
sur les chunks du seul candidat, puis réponse. Effort réduit (réutilise tout le RAG existant).

---

## 7. Intégration & robustesse

- **Injection** : au début de `get_answer` et `get_answer_stream`, si `agent_has_cv_base_folder`,
  déléguer à `cv_agent.answer_cv(...)` / `answer_cv_stream(...)` ; sinon flux actuel intact.
- **Streaming** : l'appel de routage (`get_chat_response_with_tools`) est non-streamé (rapide) ;
  la réponse finale est streamée via les mêmes événements SSE (`token` / `done` / `error`).
- **Fallback** : si le routeur n'appelle aucun outil, ou en cas d'erreur d'un outil, on retombe sur
  le RAG standard (jamais d'échec dur pour l'utilisateur).
- **Isolation tenant** : `company_id` + `folder_ids` (sous-arbre) sur **chaque** requête SQL et
  vectorielle. Lecture seule → aucun flow de confirmation.
- **Historique** : la conversation (messages précédents) est passée au routeur et à la réponse.

---

## 8. Découpage en livrables

| Étape | Livrable | Dépend de |
|---|---|---|
| **A. Fondation** | `cv_agent.py` : couche données (stubs testés) + `agent_has_cv_base_folder` + routeur + branchement dans `get_answer(_stream)` + fallback | Phase 1 |
| **B. Q&A** (Phase 4) | `find_candidate_by_name` + outil `cv_qa` + RAG ciblé | A |
| **C. Sourcing** (Phase 2) | `search_candidates` + outil `cv_sourcing` + classement | A |
| **D. Analytics** (Phase 3) | `aggregate_candidates` (SQL whitelisté) + outil `cv_analytics` | A |

B/C/D sont indépendants une fois A livré. Ordre conseillé A→B→C→D (Q&A valide le routeur en premier).

---

## 9. Tests

- **Unitaires purs (sans DB)** : normalisation/mapping des filtres, construction des fragments SQL
  whitelistés (analytics), logique de classement (sourcing), résolution du tool-call (mock de
  `get_chat_response_with_tools`), sérialisation des sorties.
- **Tests DB (CI, réel PG)** : `search_candidates` (filtres + groupement par candidat),
  `aggregate_candidates` (count/avg/distribution), `find_candidate_by_name` (0/1/n), isolation
  `company_id`/dossiers.
- **Tests d'intégration** : `answer_cv` route correctement selon l'intent (mock LLM + mock outils) ;
  fallback RAG quand aucun outil ; le flux non-CV reste inchangé.
- Conforme au pipeline CI actuel (Ruff **format** + lint + pytest ; les tests DB skippent en local).

---

## 10. Risques et limites (v1)

| Point | Choix v1 |
|---|---|
| Qualité de routage d'intention | Un seul appel tool-calling ; fallback RAG si ambiguïté → jamais bloquant |
| SQL analytics | Whitelisté/paramétré, pas de SQL libre → pas d'injection, mais dimensions limitées |
| Rerank sourcing | Score simple (critères + vecteur), pas de rerank LLM → amélioration ultérieure |
| Graphiques analytics | Hors périmètre v1 (texte/tableau) — le générateur de fichiers existe pour plus tard |
| Homonymes en Q&A | Demande de préciser ; pas de désambiguïsation automatique fine |
| Coût | 2 appels LLM/message sur companions CV (petit modèle possible pour le routage) |

---

## 11. Prochaine étape

Plan d'implémentation détaillé (writing-plans), découpé A→B→C→D, exécuté en subagent-driven dans un
worktree isolé, chaque tâche en TDD.
