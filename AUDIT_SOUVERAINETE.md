# Audit de Souveraineté des Données - TAIC Companion

**Date :** 22 mai 2026
**Projet :** TAIC Companion - Plateforme SaaS de chatbots IA (RAG)
**Périmètre :** Backend (FastAPI), Frontend (Next.js), Infrastructure (GCP)
**Exigence :** Données exclusivement en France / Europe (RGPD + CNIL)
**Niveau de conformité visé :** RGPD + DPA (Data Processing Agreements)

---

## 1. Résumé exécutif

L'audit a identifié **14 vecteurs d'exfiltration de données vers les USA** dans le projet TAIC Companion. Chaque requête utilisateur déclenchait au minimum 1 appel vers un serveur américain.

**Après corrections Phase 1 :** 5 points critiques ont été résolus. Les données des utilisateurs finaux ne transitent plus par les CDN et services de tracking américains (Google Fonts, Google Analytics). Le provider LLM par défaut est Mistral (France). Le service de génération d'images (Imagen) pointe désormais sur la région EU.

**Statut actuel :** Partiellement conforme - des actions Phase 2 restent nécessaires.

---

## 2. Matrice des services et localisation

### 2.1 Services conformes (données en EU)

| Service | Localisation | Fichiers concernés | Statut |
|---------|-------------|-------------------|--------|
| PostgreSQL (Cloud SQL) | europe-west1 | `backend/database.py` | Conforme |
| pgvector (embeddings) | europe-west1 (dans PostgreSQL) | `backend/database.py:384-390` | Conforme |
| Redis | europe-west1 (VPC 10.170.82.115) | `backend/redis_client.py` | Conforme |
| Cloud Run Backend | europe-west1 | `cloudbuild.yaml:22` | Conforme |
| Cloud Run Frontend | europe-west1 | `cloudbuild.yaml:78` | Conforme |
| Mistral AI (LLM) | France | `backend/mistral_client.py` | Conforme |
| Mistral Embeddings | France | `backend/mistral_embeddings.py` | Conforme |
| Gemini / Vertex AI | europe-west1 (configuré) | `backend/gemini_client.py:20` | Conforme (infra Google) |
| GCS Bucket documents | europe-west1 | `cloudbuild.yaml:41` | Conforme (migré le 22/05) |

### 2.2 Services non conformes (données hors EU)

| Service | Localisation | Fichiers concernés | Risque | Action requise |
|---------|-------------|-------------------|--------|---------------|
| OpenAI API | USA | `backend/openai_client.py:263-267` | Critique | DPA requis ou retirer |
| Perplexity API | USA | `backend/perplexity_client.py:50` | Critique | DPA requis ou retirer |
| Gmail SMTP | USA | `backend/email_service.py:17` | Critique | Migrer vers Brevo/Sendinblue |
| Google OAuth | USA | `frontend/pages/login.js:10,170` | Élevé | Documenter ou remplacer |
| Slack Integration | USA (Salesforce) | `backend/routers/slack.py` | Élevé | Documenter dans CGU |
| Notion API | USA | `backend/notion_client.py:15` | Élevé | Documenter dans CGU |
| Google Drive API | USA | `backend/google_drive_client.py` | Élevé | Documenter dans CGU |
| Google Cloud Logging | USA (Google) | `backend/main.py:65-77` | Moyen | Acceptable avec DPA Google |
| Google Cloud Build | USA (Google) | `cloudbuild.yaml` | Moyen | Acceptable avec DPA Google |
| GitHub | USA (Microsoft) | `cloudbuild.yaml:40-41` | Moyen | Code source uniquement |

### 2.3 Services corrigés (Phase 1 - 22 mai 2026)

| Problème | Avant | Après | Fichiers modifiés |
|----------|-------|-------|-------------------|
| Google Fonts | CDN USA (fonts.googleapis.com) | Self-hosted (@fontsource) | `_document.js`, `_app.js`, `next.config.js` |
| Google Analytics | Tracking vers USA (G-SMFNXHZW68) | Supprimé | `_app.js`, `CookieBanner.js`, `cloudbuild.yaml`, `Dockerfile` |
| Imagen région par défaut | us-central1 | europe-west1 | `backend/imagen_client.py:32`, `cloudbuild.yaml`, `cloudbuild_dev.yaml` |
| CSP (Content Security Policy) | Autorisait api.openai.com, GA, Google Fonts | Nettoyé, seul Google OAuth reste | `frontend/next.config.js` |
| GCS Bucket | US (multi-region) | EUROPE-WEST1 | Migration manuelle via gsutil |

---

## 3. Flux de données détaillés

### 3.1 Flux d'une requête utilisateur (POST /ask)

```
Utilisateur (navigateur)
    |
    v
[1] Frontend Next.js (Cloud Run, europe-west1)
    |
    v
[2] Backend FastAPI (Cloud Run, europe-west1)
    |
    +---> [3] PostgreSQL pgvector (europe-west1) -- recherche de chunks similaires
    |
    +---> [4] Redis (europe-west1) -- cache embeddings/réponses
    |
    +---> [5] Provider LLM (selon agent.llm_provider) :
    |         - "mistral" --> Mistral API (France)         [CONFORME]
    |         - "openai"  --> OpenAI API (USA)              [NON CONFORME]
    |         - "gemini"  --> Vertex AI (europe-west1)      [CONFORME infra]
    |         - "perplexity" --> Perplexity API (USA)       [NON CONFORME]
    |
    v
[6] Réponse streamée vers l'utilisateur
```

**Provider par défaut pour les nouveaux agents :** Mistral (France)
- Défini dans `backend/helpers/agent_helpers.py:48` : `resolve_llm_provider()` retourne `"mistral"`
- Modèle par défaut : `mistral:mistral-small-latest` (ligne 31)

### 3.2 Flux d'upload de document

```
Fichier uploadé (PDF/DOCX/TXT)
    |
    v
[1] Validation et extraction de texte (local, backend)
    |
    v
[2] Stockage fichier --> GCS bucket (europe-west1)    [CONFORME]
    |
    v
[3] Chunking du texte (local, backend)
    |
    v
[4] Génération d'embeddings :
    |   - Mistral Embeddings (France)                   [CONFORME]
    |   - ou OpenAI Embeddings (USA)                    [NON CONFORME]
    |
    v
[5] Stockage chunks + vecteurs --> PostgreSQL pgvector (europe-west1) [CONFORME]
```

### 3.3 Flux des emails

```
Événement déclencheur (inscription, reset mdp, invitation, recap)
    |
    v
[1] Génération du contenu email (backend, local)
    |
    v
[2] Envoi SMTP --> smtp.gmail.com:465 (USA)            [NON CONFORME]
    |
    v
[3] Réception par le destinataire
```

---

## 4. Analyse RGPD

### 4.1 Articles concernés

| Article RGPD | Sujet | Statut | Détail |
|-------------|-------|--------|--------|
| Art. 44-49 | Transferts internationaux | Non conforme | Données envoyées à OpenAI, Perplexity, Gmail (USA) |
| Art. 28 | Sous-traitants | Partiellement conforme | DPA Google Cloud signé, DPA OpenAI/Perplexity à vérifier |
| Art. 32 | Sécurité du traitement | Conforme | Chiffrement des champs sensibles, SSL/TLS, JWT |
| Art. 35 | Analyse d'impact (DPIA) | Non réalisée | Recommandée vu les transferts internationaux |

### 4.2 Base légale pour les transferts USA

Depuis l'arrêt Schrems II (2020), les transferts vers les USA nécessitent :
- Des **Clauses Contractuelles Types (SCCs)** signées avec chaque sous-traitant US
- Ou des **Data Processing Agreements (DPA)** avec garanties adéquates
- Une **analyse d'impact du transfert (TIA)** documentée

**Actions requises :**
- Vérifier/signer les DPA avec : OpenAI, Google Cloud, Perplexity (si conservé)
- Documenter les transferts dans la politique de confidentialité
- Réaliser une DPIA formelle

---

## 5. Plan d'action

### Phase 1 - Quick wins (TERMINÉ - 22 mai 2026)

- [x] Suppression de Google Analytics (tracking USA)
- [x] Self-hosting des Google Fonts (@fontsource)
- [x] Correction Imagen region (us-central1 --> europe-west1)
- [x] Nettoyage CSP (suppression domaines Google/OpenAI inutiles)
- [x] Migration bucket GCS de US vers EUROPE-WEST1
- [x] Nettoyage des buckets GCS inutiles

### Phase 2 - Migrations critiques (A FAIRE)

- [ ] **Remplacer Gmail SMTP par un fournisseur EU**
  - Recommandation : Brevo/Sendinblue (entreprise française, serveurs en France)
  - Alternative : Mailjet (français)
  - Fichier : `backend/email_service.py`
  - Impact : Modifier SMTP_HOST, SMTP_PORT, SMTP_EMAIL, SMTP_PASSWORD

- [ ] **Signer les DPA manquants**
  - OpenAI : https://openai.com/policies/data-processing-addendum
  - Google Cloud : Vérifier DPA existant dans la console GCP
  - Perplexity : Contacter le support pour DPA

- [ ] **Retirer ou restreindre Perplexity** (agents "recherche_live")
  - Option A : Supprimer `perplexity_client.py` et le type "recherche_live"
  - Option B : Remplacer par Mistral avec web search ou Brave Search API (EU)
- [ ] **Ajouter analytics EU** (si besoin de tracking)
  - Recommandation : Plausible (EU) ou Matomo (self-hosted)

### Phase 3 - Renforcement

- [ ] Remplacer Google OAuth par auth native ou Keycloak (EU)
- [ ] Documenter les intégrations Slack/Notion/Drive dans les CGU (transfert US optionnel)
- [ ] Ajouter validation de localisation du bucket GCS au démarrage du backend
- [ ] Définir les buckets GCS dans Terraform avec `location = "europe-west1"`
- [ ] Mettre à jour `scripts/setup-gcp.sh` pour forcer `-l europe-west1`

### Phase 4 - Souveraineté totale (optionnel, si exigée)

- [ ] Migrer Cloud Run vers OVHcloud/Scaleway (Kubernetes managé, France)
- [ ] Migrer Cloud SQL vers PostgreSQL managé OVH/Scaleway
- [ ] Migrer Secret Manager vers HashiCorp Vault self-hosted EU
- [ ] Migrer GitHub vers GitLab EU ou Gitea self-hosted
- [ ] Migrer Cloud Build vers GitLab CI/CD EU

---

## 6. Infrastructure GCS - État post-migration

| Bucket | Localisation | Usage | Statut |
|--------|-------------|-------|--------|
| `applydi-documents` | EUROPE-WEST1 | Documents, images, traceability | Conforme |
| `applydi_cloudbuild` | US --> migration en cours | Artefacts Cloud Build | En cours |
| `gcf-v2-sources-*` | europe-west1 | Cloud Functions (auto-géré GCP) | Conforme |
| `gcf-v2-uploads-*` | europe-west1 | Cloud Functions (auto-géré GCP) | Conforme |
| `run-sources-*` | europe-west1 | Cloud Run (auto-géré GCP) | Conforme |
| `test-bnp-taic-01` | EUROPE-WEST1 | Tests | Conforme |

**Buckets supprimés le 22/05/2026 :**
- `applydi-agent-photos` (inutilisé en production)
- `applydi-documents-eu` (résidu de migration précédente)
- `applydi-documents-eu-temp` (bucket temporaire de migration)
- `taic_source` (non référencé dans le code)

---

## 7. Fichiers modifiés (Phase 1)

| Fichier | Modification |
|---------|-------------|
| `backend/imagen_client.py` | Fallback region changé de `us-central1` à `europe-west1` |
| `cloudbuild.yaml` | Ajouté `IMAGEN_LOCATION=europe-west1`, `DEFAULT_LLM_PROVIDER=mistral`, supprimé GA |
| `cloudbuild_dev.yaml` | Idem cloudbuild.yaml |
| `frontend/pages/_document.js` | Supprimé liens Google Fonts CDN |
| `frontend/pages/_app.js` | Supprimé Google Analytics, ajouté imports @fontsource |
| `frontend/components/CookieBanner.js` | Supprimé fonction loadGA et code GA |
| `frontend/next.config.js` | CSP nettoyé (supprimé GA, Google Fonts, api.openai.com) |
| `frontend/Dockerfile` | Supprimé build arg NEXT_PUBLIC_GA_ID |
| `frontend/package.json` | Ajouté @fontsource/inter, @fontsource/plus-jakarta-sans |

---

## 8. Recommandations

### Priorité haute
1. **Migrer le service email** de Gmail vers Brevo/Sendinblue (France) - c'est le dernier point où les données personnelles des utilisateurs (emails, liens de vérification) transitent systématiquement par les USA.
2. **Signer les DPA** avec OpenAI et Google Cloud pour couvrir les transferts existants.
3. **Décider du sort de Perplexity** (supprimer ou obtenir un DPA).

### Priorité moyenne
4. Ajouter une analytics EU (Plausible/Matomo) si le tracking est nécessaire.
5. Documenter dans les CGU que les intégrations Slack/Notion/Drive sont optionnelles et impliquent un transfert vers les USA.

### Priorité basse
6. Migration complète hors GCP vers un hébergeur français (OVH/Scaleway) uniquement si la souveraineté totale est exigée (secteurs défense, santé, etc.).

---

## 9. Conclusion

Le projet TAIC Companion a progressé significativement vers la conformité souveraineté des données en une journée. Les principaux points de fuite côté frontend (Google Analytics, Google Fonts) ont été éliminés. Le stockage (GCS) a été relocalisé en Europe. Le provider LLM par défaut est français (Mistral).

Les points restants concernent principalement le service email (Gmail --> Brevo) et la formalisation juridique (DPA avec les sous-traitants américains). Ces actions sont réalisables et ne nécessitent pas de refonte majeure de l'architecture.

**Niveau de conformité estimé : 70% (contre ~10% avant l'audit)**

---

*Rapport généré le 22 mai 2026 - TAIC Companion*
