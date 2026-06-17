# Safe Launch — Sprint de durcissement avant client #1

**Date :** 2026-06-17
**Auteur :** Jeremy + Claude
**Statut :** Validé (design) — en attente de revue du spec
**Échéance :** 1 semaine (premier client payant)

## Contexte

TAIC Companion est une plateforme SaaS RAG multi-tenant (instance partagée, isolation
par `company_id` + RLS Postgres) déployée sur Google Cloud Run + Cloud SQL + GCS, prod
déjà live. On onboarde le premier client payant dans une semaine. Le client utilisera la
**plateforme complète**. Contrainte data : **hébergement UE suffisant**, OpenAI/Mistral/Gemini
autorisés comme sous-traitants.

L'objectif n'est PAS de réécrire la plateforme : le code est mature (RLS, secrets chiffrés,
2FA, logging structuré, gestion d'erreurs centralisée, Alembic, ~380 tests backend, CI). Il
s'agit de **verrouiller les couches transversales** qui protègent chaque client et chaque
feature, et de **reporter** la refonte profonde par sous-système dans un backlog documenté.

### Périmètre

- **Inclus :** P0 (isolation tenant, garde-fous coût LLM, sécurité déploiement) + sous-ensemble
  sécurité critique de P1 (clé chiffrement obligatoire, lockout login, backup codes 2FA,
  validation entrées critiques, timeouts LLM) + smoke test manuel de bout en bout.
- **Exclu (backlog post-lancement, voir §8) :** ops RGPD avancées, rotation clé chiffrement,
  migration scheduler → Cloud Scheduler, unification Alembic complète, tests E2E frontend,
  migration Pydantic v1→v2.

## État vérifié de la prod (RLS)

Requête lancée sur la base prod (rôle `applydiuser`) le 2026-06-17 :

- **Rôle app : `rolsuper=false`, `rolbypassrls=false`** → RLS est réellement appliqué (pas de bypass).
- **10 tables cœur `enabled+forced`, 2 policies** (OK) : `agents`, `agent_shares`, `documents`,
  `document_chunks`, `agent_actions`, `teams`, `conversations`, `messages`, `notion_links`,
  `weekly_recap_logs`.
- **`recaps` et `recap_documents` : policy présente mais `rls_enabled=false`** → policies INERTES,
  tables NON isolées. **Fuite cross-tenant réelle.**
- **`drive_links` : aucune RLS, aucune policy** → non isolée.
- **Absentes de la prod** : `agent_templates`, `company_folders`, `missions`, `mission_events`,
  `mission_recaps`, `mission_recap_schedules`, `questionnaires*`. La prod est antérieure au `dev`.
  Au prochain déploiement ces tables seront créées **sans RLS** (le startup crée les policies mais
  ne fait jamais `ENABLE/FORCE`).

**Conclusion :** l'isolation cœur tient, mais l'activation RLS n'est pas déterministe ; le trou se
reproduit à chaque nouvelle table. C'est la priorité n°1.

## Principe de « terminé » (Definition of Done)

Chaque workstream livre : **code + tests + une note de vérification** (commande lancée + sortie
réelle) prouvant le résultat. Aucune affirmation « ça devrait marcher » sans preuve.

---

## WS1 — Isolation des tenants (priorité maximale)

**Objectif :** rendre l'isolation prouvable et déterministe, fermer les trous IDOR applicatifs.

### Changements

1. **Activation RLS déterministe et idempotente au startup.** Dans `ensure_rls_policies()`
   (`backend/database.py`), pour chaque table tenant : exécuter `ALTER TABLE <t> ENABLE ROW LEVEL
   SECURITY` puis `FORCE ROW LEVEL SECURITY` **avant** de créer les policies, de façon idempotente.
   Source unique de la liste des tables tenant (constante partagée) pour éviter la dérive entre
   `ensure_rls_policies`, `delete_company` et les futures tables.
2. **Réparer `recaps` et `recap_documents`** : enable+force (policies déjà présentes).
3. **Ajouter l'isolation sur `drive_links`** : policy `tenant_isolation` + `service_bypass` + enable/force.
4. **Couvrir les tables à venir** : `agent_templates`, `company_folders` — ajoutées à la liste tenant
   pour que leur RLS soit posée dès leur création en prod.
5. **Tables `missions*` et `questionnaires*`** : restent en isolation applicative (raisons documentées :
   scheduler/endpoints publics). On **durcit et teste** les filtres applicatifs (company_id + user_id),
   sans poser de RLS qui casserait ces flux. Décision tracée dans le code.
6. **Corriger les IDOR applicatifs** (fetch par id sans contrôle company) :
   - `routers/organization.py` : 4 endpoints de partage d'agent (`share`, `delete share`, `put share`,
     `get shares`) → filtrer `Agent.company_id == membership.company_id`.
   - `routers/agents.py` : update membres d'équipe (`Team.company_id`), suppression d'agent (`company_id`).
   - `routers/conversations.py` : `_verify_conversation_owner` → vérifier `conversation.company_id`.
7. **Middleware `tenant_isolation_middleware`** (`main.py`) : remplacer `except Exception: pass` par un
   log explicite (warning + request_id) ; garantir le comportement fail-closed pour les écritures
   (refuser une écriture si `company_id` n'a pas pu être résolu pour un utilisateur authentifié).

### Tests / DoD

- Nouveau `backend/tests/test_cross_tenant_idor.py` : utilisateur Société A tente d'accéder/modifier
  agents, documents, équipes, partages, conversations, recaps, missions de Société B → 403/404, jamais
  de données. Inclut un test prouvant que RLS est `enabled+forced` sur toutes les tables tenant après startup.
- Note de vérification : relancer la requête RLS prod après déploiement → toutes les tables tenant
  `enabled=true, forced=true`.

---

## WS2 — Garde-fous coût & abus LLM

**Objectif :** borner le blast-radius financier ; empêcher qu'un abus (surtout endpoint public) génère une facture LLM illimitée.

### Changements

1. **Table `LLMUsageLog`** (`user_id`, `company_id`, `agent_id`, `provider`, `model`, `input_tokens`,
   `output_tokens`, `cost_usd`, `created_at`, index sur `company_id, created_at`). Migration Alembic.
2. **Instrumentation** : enregistrer chaque appel LLM (openai/mistral/gemini) avec tokens + coût estimé.
   Point central côté `rag_engine`/clients pour ne pas oublier de chemin.
3. **Plafonds de dépense** : cap mensuel par tenant + cap journalier par agent public. Dépassement →
   refus propre (429 + message) plutôt qu'appel LLM. Configurable (valeurs par défaut prudentes).
4. **Endpoint de chat public** (`routers/public.py`) : ajouter le cap par agent public en plus du rate-limit IP.
5. **Budget Cloud Billing + alerte** : configurer un budget GCP + alerte (la dépendance
   `google-cloud-billing-budgets` est déjà présente). Documenter la procédure.

### Tests / DoD

- Tests : un appel LLM écrit bien une ligne `LLMUsageLog` ; dépassement de cap → 429 sans appel LLM.
- Note de vérification : simulation de dépassement de cap sur l'endpoint public → refus.

---

## WS3 — Sécurité du déploiement (prod live)

**Objectif :** aucun déploiement « cowboy » la semaine d'onboarding ; rollback en une commande.

### Changements

1. **CI au vert** : lancer `ruff format .` sur les fichiers non formatés et committer ; confirmer que les
   3 jobs CI passent sur `dev`.
2. **Déploiement derrière CI verte** : protection de branche sur `main` (et `dev`) exigeant les 3 jobs CI,
   et/ou conditionner Cloud Build au succès de la CI. Le déploiement ne doit plus être découplé des tests.
3. **Verrou sur les migrations au startup** : `pg_advisory_lock` dans `alembic/env.py` (ou autour de
   l'upgrade au startup) pour qu'une seule instance applique les migrations ; les autres attendent.
4. **Pool DB vs limite Cloud SQL** : aujourd'hui `pool_size=3, max_overflow=10` × jusqu'à 10 instances
   = 130 connexions potentielles > limite ~100. Ajuster pool et/ou `max-instances` et/ou la limite Cloud SQL
   pour rester sous le plafond avec marge.
5. **Procédure de rollback** : documenter + répéter une fois `gcloud run services update-traffic
   <svc> --to-revisions=<revision_précédente>=100`. Inclure la stratégie en cas de migration non réversible
   (le code doit rester compatible N-1 : pas de DROP destructif dans le même déploiement).

### Tests / DoD

- CI verte prouvée (capture du run).
- Note de vérification : un rollback réel testé sur une révision précédente en prod (ou staging).

---

## WS4 — Durcissement auth & secrets (sous-ensemble critique)

**Objectif :** fermer les risques d'auth les plus exploitables et garantir le chiffrement en prod.

### Changements

1. **`ENCRYPTION_KEY` obligatoire en prod** : au startup, si `GOOGLE_CLOUD_PROJECT` est défini et
   `ENCRYPTION_KEY` absente → `RuntimeError` (refus de démarrer). Empêche tout stockage de secret en clair.
2. **Verrouillage de compte** : suivi des échecs de login par utilisateur ; lockout temporaire après N
   échecs (ex. 5 / 10 min) avec backoff. Complète le rate-limit IP existant.
3. **Backup codes 2FA** : générer 10 codes (hashés bcrypt) à l'activation 2FA, affichés une fois, utilisables
   en fallback dans `verify_2fa`. Le champ existe déjà mais n'est jamais peuplé → récupération impossible aujourd'hui.
4. **Durée JWT + refresh** : réduire l'access token (ex. 1h) et ajouter un mécanisme de refresh, ou à
   défaut documenter et raccourcir. (Si le refresh complet déborde, on raccourcit + on note le refresh en backlog.)
5. **Rotation du PAT GitHub fuité** : révoquer le token présent dans `MEMORY.md` et le retirer du fichier.

### Tests / DoD

- Tests : démarrage refusé sans `ENCRYPTION_KEY` en mode prod ; lockout après N échecs ; login via backup code.
- Note de vérification : round-trip backup code OK.

---

## WS5 — Essentiels de robustesse + smoke test

**Objectif :** éviter les crashs/hangs sur les entrées et les pannes fournisseurs ; valider les parcours réels.

### Changements

1. **Validation des entrées** : remplacer les `Form()`/`dict` bruts par des modèles Pydantic avec
   `max_length` sur les endpoints critiques (création/màj agent, équipe, company_rag). Priorité aux endpoints
   que le client touche.
2. **Uploads** : whitelist de `content_type` (PDF/TXT/DOCX/PPTX/XLSX) + pré-vérification du nombre de pages
   PDF (`MAX_PDF_PAGES`) avant traitement complet ; sanitization du nom de fichier (anti path-traversal).
3. **Pagination** : ajouter `skip`/`limit` (avec borne max) sur les endpoints de liste qui font `.all()`
   (conversations, agents, teams, company-rag documents…).
4. **Timeouts/retries** : imposer un timeout réel sur les appels Mistral/Gemini/Notion (le param existe mais
   n'est pas toujours passé) + retry exponentiel borné, et échec gracieux (message clair) si un fournisseur est down.
5. **Gestion d'erreurs prod** : vérifier que le handler global ne renvoie jamais de stack trace au client
   quand `ENVIRONMENT != development` ; supprimer le middleware catch-all redondant si confirmé.

### Smoke test manuel (bout en bout)

Sur staging puis prod (compte de test), couvrir les parcours du client : signup/login + 2FA, création
d'agent, upload de document (chaque format), Q&A RAG, company-RAG + folders, partage d'agent, conversation,
missions/recaps si activés, endpoint public. Checklist dans le plan d'implémentation, résultats consignés.

### Tests / DoD

- Tests : entrée trop longue → 422 ; PDF hors limite → refus propre ; fournisseur LLM en erreur → 503/message,
  pas de hang ; liste paginée bornée.
- Note de vérification : checklist smoke test cochée avec captures.

---

## 8. Backlog post-lancement (reporté, à planifier semaine +1)

- **RGPD ops :** suppression cascade des blobs GCS sur delete document/compte/société ; export par société
  (Art. 20) ; log d'audit des accès aux données ; liste écrite des sous-traitants (OpenAI, Mistral, Gemini,
  Brevo) + DPA ; effacement Neo4j ; politique de rétention des messages.
- **Clé de chiffrement :** versioning + rotation sans perte (colonne `key_version`, playbook).
- **Fiabilité scheduler :** migration APScheduler → Cloud Scheduler/Cloud Tasks (recaps manqués/dupliqués sur
  scale-to-zero) ; verrou distribué sur les jobs.
- **Migrations :** unification complète Alembic (retrait progressif des `ensure_*` ad-hoc).
- **Frontend :** suite E2E Playwright (login → créer agent → poser question) câblée en CI ; seuil de couverture.
- **Dette :** migration Pydantic v1→v2 (`@validator` → `@field_validator`).

## 9. Séquencement sur la semaine

1. **J1 :** WS1 (isolation) — le plus risqué, à sécuriser d'abord. WS3.1 (CI verte) en parallèle.
2. **J2 :** Fin WS1 + tests IDOR. WS3 (verrou migrations, pool, rollback).
3. **J3 :** WS2 (coût/abus LLM).
4. **J4 :** WS4 (auth/secrets).
5. **J5 :** WS5 (robustesse) + début smoke test.
6. **J6 :** Smoke test complet sur staging→prod, corrections.
7. **J7 :** Marge / buffer / go-no-go.

## 10. Risques

- **RLS sur nouvelles tables au déploiement** : le déploiement du `dev` (folders, missions) doit s'accompagner
  de l'activation RLS déterministe (WS1) — sinon fenêtre de non-isolation. Ordre de déploiement à respecter.
- **Refresh JWT** : si le mécanisme complet déborde du temps, on raccourcit la durée et on reporte le refresh.
- **RGPD contractuel** : si le client exige export/effacement dès le jour 1, remonter les items concernés de §8 en P0.
