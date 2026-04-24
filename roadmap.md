# TAIC Companion - Roadmap Produit

> Derniere mise a jour : 23 avril 2026
> Version actuelle : 1.0 (Production sur Google Cloud Run)

---

## Table des matieres

1. [Etat actuel du produit](#1-etat-actuel-du-produit)
2. [Phase 1 - Consolidation technique (Mai-Juin 2026)](#2-phase-1--consolidation-technique-mai-juin-2026)
3. [Phase 2 - Experience utilisateur (Juillet-Aout 2026)](#3-phase-2--experience-utilisateur-juillet-aout-2026)
4. [Phase 3 - Fonctionnalites entreprise (Sept-Nov 2026)](#4-phase-3--fonctionnalites-entreprise-sept-nov-2026)
5. [Phase 4 - Intelligence avancee (Dec 2026 - Fev 2027)](#5-phase-4--intelligence-avancee-dec-2026-fev-2027)
6. [Phase 5 - Scale et expansion (Mars-Mai 2027)](#6-phase-5--scale-et-expansion-mars-mai-2027)
7. [Phase 6 - Plateforme ouverte (Juin-Aout 2027)](#7-phase-6--plateforme-ouverte-juin-aout-2027)
8. [Indicateurs cles (KPIs)](#8-indicateurs-cles-kpis)
9. [Risques et mitigations](#9-risques-et-mitigations)

---

## 1. Etat actuel du produit

### Architecture technique
| Composant | Technologie | Statut |
|-----------|-------------|--------|
| Backend API | FastAPI (Python 3.11) | Production - 80+ endpoints |
| Base de donnees | PostgreSQL 15 + pgvector | Production - 15 modeles, RLS multi-tenant |
| Cache | Redis 7 (avec fallback in-memory) | Production |
| Frontend | Next.js 14 (Pages Router) + React 18 + Tailwind | Production - 20 pages |
| Embeddings | Mistral embed (1024d) + pgvector HNSW | Production |
| LLM Providers | OpenAI, Mistral, Gemini, Perplexity | Production - configurable par agent |
| Deploiement | Google Cloud Run + Cloud SQL + Cloud Build | Production - CI/CD automatise |
| Stockage fichiers | Google Cloud Storage | Production |
| Graph de connaissances | Neo4j (optionnel, par organisation) | Production |

### Fonctionnalites existantes

**Authentification et securite**
- Inscription/connexion avec JWT (HttpOnly cookies)
- Authentification 2FA (TOTP) avec QR code et codes de secours
- Google OAuth (connexion sociale)
- Verification d'email
- Reset de mot de passe par email
- Chiffrement AES des secrets (tokens Slack, cles API, TOTP)

**Gestion des agents IA**
- Creation, modification, suppression d'agents
- 2 types d'agents : `conversationnel` (RAG classique) et `recherche_live` (Perplexity)
- Configuration personnalisee : contexte systeme, biographie, photo de profil
- LLM provider configurable (Mistral, OpenAI, Gemini, Perplexity)
- Partage d'agents entre utilisateurs (lecture/edition)
- Agents publics avec endpoint de chat ouvert
- Agents actionnables (Google Docs/Sheets via service account)

**RAG (Retrieval-Augmented Generation)**
- Upload de documents : PDF, DOCX, PPTX, XLSX, TXT, URL web
- Chunking intelligent avec overlap (base sur les tokens, NLTK)
- Embeddings Mistral (1024 dimensions) stockes en pgvector
- Recherche vectorielle HNSW pour retrieval rapide
- Cache des reponses RAG (Redis 5min, fallback in-memory)
- Cache des embeddings (Redis 24h)

**Sources de donnees**
- Upload de fichiers locaux (multi-format)
- Ingestion d'URLs web (readability + BeautifulSoup)
- Sync Notion (pages et bases de donnees)
- Sync Google Drive (dossiers entiers)
- Re-sync manuelle des sources Notion/Drive
- Documents de tracabilite (type separe du RAG)

**Conversations**
- Historique de conversations persistant par agent
- Feedback par message (like/dislike)
- Renommage et suppression de conversations
- Chat multi-agent via Teams

**Teams (multi-agents)**
- Creation d'equipes avec un agent leader et des agents d'action
- Routage intelligent des questions vers les agents specialises
- Chat unifie avec delegation automatique

**Organisation / Multi-tenant**
- Creation d'entreprise (avec validation admin)
- Invitations par email et par lien (invite code)
- Roles : owner, admin, member
- Isolation des donnees par Row-Level Security (RLS) PostgreSQL
- Integrations au niveau organisation (Neo4j, Notion, Slack)
- Slash commands configurables par organisation

**Integrations externes**
- Slack Bot : reponses aux messages/mentions dans Slack via les agents
- Notion : sync de pages et bases de donnees comme sources RAG
- Google Drive : sync de dossiers comme sources RAG
- Neo4j : graphe de connaissances pour contexte personne-centrique
- Google Docs/Sheets : creation de documents via actions d'agent
- Imagen 3 : generation d'images via Vertex AI

**Fonctionnalites supplementaires**
- Weekly Recap : emails de synthese hebdomadaire par agent
- Generation de fichiers (PDF, XLSX, CSV) a partir des reponses
- Export des donnees utilisateur (RGPD)
- Suppression de compte
- Ingestion d'emails avec pieces jointes
- Internationalisation (FR/EN) complete
- Administration : approbation des creations d'entreprise (pages HTML admin)

**Infrastructure**
- CI/CD GitHub Actions (Ruff, ESLint, pytest, Next.js build)
- 39 tests unitaires (auth + validation)
- Docker Compose pour dev local
- Cloud Build pour deploiement staging/production

---

## 2. Phase 1 : Consolidation technique (Mai-Juin 2026)

**Objectif** : Stabiliser la base technique, reduire la dette, ameliorer la fiabilite et la maintenabilite avant d'ajouter de nouvelles fonctionnalites.

### 2.1 Refactoring du backend

#### 2.1.1 Decoupage de main.py
- [ ] **Migrer vers un routeur FastAPI modulaire** : main.py fait ~120KB et 6500+ lignes. Le decouper en modules thematiques :
  - `routers/auth.py` : inscription, login, 2FA, OAuth, verification email
  - `routers/agents.py` : CRUD agents, partage, configuration
  - `routers/documents.py` : upload, download, suppression
  - `routers/conversations.py` : historique, messages, feedback
  - `routers/teams.py` : CRUD teams, chat multi-agent
  - `routers/organization.py` : company, membres, invitations, integrations
  - `routers/sources.py` : Notion links, Drive links, tracabilite
  - `routers/admin.py` : endpoints d'administration
  - `routers/public.py` : agents publics, chat public
  - `routers/slack.py` : webhook Slack, config
  - `routers/user.py` : profil, stats, export, suppression
- [ ] **Extraire la logique metier de main.py vers des services** :
  - `services/agent_service.py` : logique CRUD et partage d'agents
  - `services/document_service.py` : upload, processing, chunking
  - `services/conversation_service.py` : gestion des conversations
  - `services/organization_service.py` : gestion des entreprises et membres

#### 2.1.2 Amelioration de la base de donnees
- [ ] **Migrer vers Alembic** pour les migrations de schema (remplacer `ensure_columns()`)
- [ ] **Ajouter des index manquants** : analyser les requetes lentes et ajouter les index necessaires
- [ ] **Audit des requetes N+1** : identifier et corriger les chargements non optimises (utiliser `joinedload` systematiquement)
- [ ] **Connection pooling** : ajuster `pool_size` et `max_overflow` selon les metriques Cloud Run

#### 2.1.3 Gestion des erreurs
- [ ] **Middleware d'erreurs centralise** : reponses JSON uniformes pour toutes les erreurs
- [ ] **Logging structure** : migrer vers du logging JSON pour Cloud Logging (deja partiellement fait)
- [ ] **Health check ameliore** : verifier Redis, PostgreSQL, et les services externes dans `/health`

### 2.2 Tests et qualite

#### 2.2.1 Couverture de tests
- [ ] **Tests d'integration** : ajouter des tests avec une vraie base PostgreSQL (via testcontainers ou fixtures)
- [ ] **Tests des endpoints principaux** : `/ask`, `/upload-agent`, `/agents`, `/conversations`
- [ ] **Tests du RAG engine** : chunking, embedding, retrieval
- [ ] **Tests des integrations** : Slack, Notion, Drive (avec mocks)
- [ ] **Objectif : 70% de couverture** (actuellement ~39 tests unitaires seulement)

#### 2.2.2 Tests frontend
- [ ] **Installer Jest + React Testing Library**
- [ ] **Tests des hooks critiques** : `useAuth`, composants de conversation
- [ ] **Tests E2E avec Playwright** : flow login > creation agent > upload doc > question
- [ ] **Ajouter les tests au pipeline CI**

### 2.3 Securite

- [ ] **Audit de securite complet** :
  - Rate limiting sur tous les endpoints sensibles (login, register, forgot-password, ask)
  - Protection CSRF (verifier que les cookies SameSite sont corrects)
  - Validation stricte de tous les inputs (renforcer les schemas Pydantic)
  - Audit des permissions : verifier que chaque endpoint verifie l'appartenance tenant
- [ ] **Rotation des secrets** : mecanisme de rotation automatique des JWT_SECRET_KEY
- [ ] **Logs d'audit** : tracer les actions sensibles (login, partage, suppression)

### 2.4 Performance

- [ ] **Profiling des endpoints lents** : identifier les bottlenecks avec des metriques Cloud Monitoring
- [ ] **Optimisation du chunking** : paralleliser le processing de gros documents
- [ ] **Lazy loading frontend** : optimiser le bundle size (agents.js fait ~43KB)
- [ ] **Compression des reponses** : activer gzip/brotli sur Cloud Run

### 2.5 Documentation

- [ ] **Documentation API** : enrichir les schemas OpenAPI/Swagger avec descriptions et exemples
- [ ] **Documentation d'architecture** : diagrammes C4, flux de donnees, decisions d'architecture (ADR)
- [ ] **Guide de contribution** : CONTRIBUTING.md avec conventions de code, process PR, setup local

---

## 3. Phase 2 : Experience utilisateur (Juillet-Aout 2026)

**Objectif** : Ameliorer l'UX/UI pour augmenter l'adoption, la retention et la satisfaction utilisateur.

### 3.1 Refonte du dashboard

- [ ] **Dashboard analytique** : vue d'ensemble avec metriques cles
  - Nombre de questions posees par jour/semaine/mois
  - Agents les plus utilises
  - Taux de satisfaction (ratio likes/dislikes)
  - Volume de documents ingereres
  - Graphiques avec Recharts (deja installe)
- [ ] **Page d'accueil personnalisee** : agents recents, conversations en cours, suggestions
- [ ] **Recherche globale** : barre de recherche unifiee (agents, documents, conversations)

### 3.2 Amelioration du chat

- [ ] **Streaming des reponses** : affichage mot par mot en temps reel (SSE ou WebSocket)
  - Backend : `StreamingResponse` avec les APIs streaming de Mistral/OpenAI/Gemini
  - Frontend : consommation du stream avec `EventSource` ou `fetch` + `ReadableStream`
- [ ] **Markdown avance** : rendu des tableaux, blocs de code avec coloration syntaxique, LaTeX
- [ ] **Citations des sources** : afficher les chunks utilises pour generer la reponse avec liens vers les documents
- [ ] **Regeneration de reponse** : bouton pour regenerer une reponse insatisfaisante
- [ ] **Edition de message** : permettre de modifier sa question et regenerer
- [ ] **Mode multi-modal** : upload d'images dans le chat (vision models)
- [ ] **Suggestions de questions** : proposer des questions pertinentes basees sur les documents

### 3.3 Gestion des documents amélioree

- [ ] **Preview de documents** : visualisation inline des PDF, images, textes
- [ ] **Progression d'upload visuelle** : barre de progression detaillee (upload > processing > chunking > embedding)
- [ ] **Gestion par lots** : selection multiple, suppression en masse, reorganisation
- [ ] **Drag & drop ameliore** : zones de drop visuelles, preview avant upload
- [ ] **Filtres et tri** : par date, taille, type, agent associe
- [ ] **Recherche dans les documents** : recherche full-text dans le contenu des chunks

### 3.4 UI/UX general

- [ ] **Mode sombre** : theme dark complet (Tailwind dark mode)
- [ ] **Design responsive** : optimisation mobile/tablette pour toutes les pages
- [ ] **Onboarding guide** : tutoriel interactif pour les nouveaux utilisateurs
- [ ] **Raccourcis clavier** : navigation rapide (Ctrl+K pour recherche, etc.)
- [ ] **Notifications in-app** : systeme de notifications pour partages, invitations, completions
- [ ] **Skeleton loading** : etats de chargement elegants sur toutes les pages
- [ ] **Animations et micro-interactions** : transitions fluides, feedback visuel

### 3.5 Page de profil enrichie

- [ ] **Historique d'activite** : timeline des actions recentes
- [ ] **Preferences utilisateur** : langue par defaut, theme, notifications
- [ ] **Gestion des sessions** : voir et revoquer les sessions actives
- [ ] **Photo de profil** : upload et gestion d'avatar

---

## 4. Phase 3 : Fonctionnalites entreprise (Sept-Nov 2026)

**Objectif** : Renforcer les fonctionnalites B2B pour le marche enterprise.

### 4.1 Gestion avancee des organisations

- [ ] **Dashboard admin organisation** :
  - Vue d'ensemble de l'utilisation par membre
  - Statistiques d'usage des agents (questions, documents, tokens consommes)
  - Gestion des quotas et limites par utilisateur/agent
- [ ] **Roles granulaires** : au-dela de owner/admin/member
  - `viewer` : lecture seule sur les agents partages
  - `editor` : modification des agents et documents
  - `admin` : gestion des membres et parametres
  - `owner` : controle total + facturation
- [ ] **Groupes / departements** : organiser les utilisateurs par departement avec des permissions distinctes
- [ ] **SSO SAML/OIDC** : integration Single Sign-On pour les grands comptes
  - Support SAML 2.0 (Azure AD, Okta, OneLogin)
  - Support OIDC (Keycloak, Auth0)
  - Auto-provisioning des utilisateurs depuis le directory

### 4.2 Systeme de permissions avance

- [ ] **ACL par agent** : permissions fines (lire, editer, supprimer, partager) par utilisateur et par groupe
- [ ] **Politique de retention** : duree de conservation des conversations et documents
- [ ] **Isolation stricte des agents** : empécher le cross-tenant access meme en cas de bug
- [ ] **Audit trail complet** : journal detaille de toutes les actions avec export

### 4.3 Facturation et abonnements

- [ ] **Integration Stripe** :
  - Plans : Free, Pro, Enterprise
  - Facturation par usage (nombre de questions, volume de documents, tokens LLM)
  - Gestion des moyens de paiement
  - Factures et historique
- [ ] **Quotas et limites** :
  - Nombre d'agents par plan
  - Volume de stockage documents
  - Nombre de questions par mois
  - Taille max des uploads
- [ ] **Page pricing** : landing page avec comparaison des plans
- [ ] **Portail client** : gestion de l'abonnement, upgrade/downgrade, annulation
- [ ] **Alertes d'usage** : notifications quand on approche des limites

### 4.4 Templates d'agents

- [ ] **Marketplace de templates** : catalogue de configurations d'agents pre-faites
  - RH : reponses aux questions des employes
  - Support client : FAQ et documentation produit
  - Juridique : analyse de contrats et conformite
  - Finance : rapports et analyses financieres
  - IT : documentation technique et troubleshooting
- [ ] **Import/export de configuration d'agent** : JSON portable
- [ ] **Versioning de configuration** : historique des modifications d'un agent

### 4.5 Webhooks et API publique

- [ ] **API publique documentee** : endpoints REST pour integration tierce
  - Authentification par API key
  - Rate limiting par cle
  - Documentation Swagger/ReDoc interactive
- [ ] **Webhooks sortants** : notifier des systemes externes sur les evenements
  - Nouvelle question posee
  - Document ajoute/supprime
  - Agent cree/modifie
  - Feedback recu
- [ ] **Widget embeddable** : composant chat incrustable sur n'importe quel site web
  - Snippet JS a copier-coller
  - Configuration visuelle (couleurs, position, comportement)
  - Mode bulle ou panel

---

## 5. Phase 4 : Intelligence avancee (Dec 2026 - Fev 2027)

**Objectif** : Exploiter les avancees IA pour differencier TAIC sur le marche.

### 5.1 RAG avance

- [ ] **Hybrid search** : combiner recherche vectorielle + BM25 (full-text) pour une meilleure precision
- [ ] **Re-ranking** : utiliser un modele de re-ranking (Cohere Rerank, cross-encoder) pour affiner les resultats
- [ ] **Chunking adaptatif** : ajuster la taille des chunks selon le type de document et la densite d'information
- [ ] **Multi-vector retrieval** : generer plusieurs embeddings par chunk (titre, resume, contenu)
- [ ] **Query expansion** : reformuler automatiquement les questions pour elargir le retrieval
- [ ] **Metadata filtering** : filtrer les chunks par metadata (date, source, type) dans la requete
- [ ] **RAG evaluation** : pipeline automatise pour mesurer la qualite des reponses
  - Metriques : faithfulness, relevance, answer correctness
  - Dashboard de suivi de la qualite RAG dans le temps

### 5.2 Agents autonomes

- [ ] **Chaines d'actions** : permettre aux agents d'executer des sequences d'actions
  - Si la reponse necessite un calcul > creer un Google Sheet
  - Si la question porte sur un process > generer un document PDF
  - Si le sujet est sensible > router vers un humain
- [ ] **Function calling** : integration native du function calling des LLMs
  - Definition d'outils personnalises par agent
  - Execution securisee des appels de fonction
  - Validation des parametres et des resultats
- [ ] **Agent orchestrateur** : un meta-agent qui decide quel agent utiliser automatiquement
  - Classification automatique des intentions
  - Routage dynamique vers le bon agent specialise
  - Boucle de feedback pour ameliorer le routage

### 5.3 Fine-tuning et personnalisation

- [ ] **Fine-tuning automatise** : utiliser les feedbacks (like/dislike) pour fine-tuner un modele
  - Pipeline : collecte des paires Q/R aimees > formatage > envoi a l'API de fine-tuning
  - Le champ `finetuned_model_id` existe deja dans le modele Agent
  - Le module `finetune_buffered_likes.py` existe deja (a completer)
- [ ] **Style de reponse configurable** : ton formel/informel, longueur, format
- [ ] **Prompts systeme dynamiques** : ajuster le contexte selon le profil de l'utilisateur

### 5.4 Multimodal

- [ ] **Vision** : analyser des images uploadees dans le chat (GPT-4V, Gemini Pro Vision)
- [ ] **Audio** : transcription vocale et Q&A audio (Whisper + TTS)
- [ ] **Video** : extraction de contenu video (transcription + key frames)
- [ ] **Generation d'images avancee** : ameliorer l'integration Imagen 3 avec preview et gallery

### 5.5 Knowledge Graph avance

- [ ] **Construction automatique du graphe** : extraire automatiquement les entites et relations des documents ingeres
- [ ] **Visualisation du graphe** : interface interactive pour explorer le graphe de connaissances
- [ ] **GraphRAG** : combiner le retrieval vectoriel avec la traversee du graphe pour des reponses plus riches
- [ ] **Support multi-graphes** : un graphe par agent ou par departement

---

## 6. Phase 5 : Scale et expansion (Mars-Mai 2027)

**Objectif** : Preparer la plateforme pour une croissance significative.

### 6.1 Infrastructure et scalabilite

- [ ] **Migration pgvector natif** : remplacer FAISS par pgvector pour tout le retrieval
  - Le code utilise deja `embedding_vec` (pgvector) mais a aussi un fallback FAISS/JSON
  - Supprimer le code legacy FAISS et la colonne `embedding` (JSON text)
- [ ] **Queue de taches** : migrer les taches async vers Celery ou Cloud Tasks
  - Processing de documents
  - Envoi d'emails
  - Sync Notion/Drive
  - Generation de recaps hebdomadaires
- [ ] **Auto-scaling avance** : min/max instances Cloud Run selon les patterns de trafic
- [ ] **CDN pour les assets** : CloudFront ou Cloud CDN pour le frontend
- [ ] **Base de donnees read replicas** : separer les lectures/ecritures pour les requetes analytiques
- [ ] **Monitoring avance** : dashboards Grafana, alertes PagerDuty, SLOs definis

### 6.2 Multi-region

- [ ] **Deploiement multi-region** : EU et US au minimum
  - Routage geographique via Cloud Load Balancing
  - Base de donnees regionale pour la conformite RGPD
- [ ] **Residency des donnees** : garantir que les donnees restent dans la region choisie
- [ ] **Latence optimisee** : embeddings et LLM calls dans la region la plus proche

### 6.3 Compliance et certifications

- [ ] **Conformite RGPD complete** :
  - DPA (Data Processing Agreement) automatise
  - Droit a l'oubli (suppression complete des donnees) - partiellement implemente
  - Registre des traitements
  - Consentement granulaire
- [ ] **SOC 2 Type II** : audit et certification pour les clients enterprise
- [ ] **ISO 27001** : mise en conformite et certification
- [ ] **HDS (Hebergement de Donnees de Sante)** : si le marche sante est vise
- [ ] **Politique de confidentialite IA** : transparence sur l'utilisation des donnees par les LLMs

### 6.4 Internationalisation

- [ ] **Langues supplementaires** : Espagnol, Allemand, Italien, Portugais, Arabe
- [ ] **Detection automatique de la langue** : adapter la langue de reponse du LLM
- [ ] **Documentation multilingue** : aide en ligne et guides dans toutes les langues supportees

---

## 7. Phase 6 : Plateforme ouverte (Juin-Aout 2027)

**Objectif** : Transformer TAIC en plateforme ouverte pour maximiser la valeur.

### 7.1 Marketplace d'integrations

- [ ] **Connecteurs pre-construits** :
  - CRM : Salesforce, HubSpot, Pipedrive
  - Communication : Microsoft Teams, Discord
  - Productivite : Confluence, Jira, Asana, Trello
  - Stockage : SharePoint, OneDrive, Dropbox, Box
  - Email : Gmail (au-dela de l'ingestion), Outlook
  - ERP : SAP, Oracle
- [ ] **Framework de plugins** : SDK pour developper des connecteurs tiers
- [ ] **OAuth flow** pour chaque integration : connexion securisee sans stocker les credentials

### 7.2 API ouverte

- [ ] **SDK clients** : librairies officielles Python, JavaScript/TypeScript, Go
- [ ] **CLI** : outil en ligne de commande pour gerer les agents et documents
- [ ] **GraphQL** : alternative a REST pour les requetes complexes
- [ ] **Documentation interactive** : portail developpeur avec sandbox de test

### 7.3 White-label

- [ ] **Customisation de marque** : logo, couleurs, domaine personnalise
- [ ] **Multi-instance** : deploiement dedie pour les grands comptes
- [ ] **Configuration sans code** : builder visuel pour personnaliser le comportement des agents
- [ ] **API de theming** : personnalisation programmatique de l'interface

### 7.4 Analytics et BI

- [ ] **Dashboard analytique avance** :
  - Tendances d'utilisation et predictions
  - Analyse des questions sans reponse (knowledge gaps)
  - Performance par source de donnees
  - Cout par agent (tokens, stockage, calcul)
- [ ] **Export vers BI** : connecteurs pour Looker, Metabase, Tableau
- [ ] **Rapports automatises** : rapports PDF/email periodiques avec KPIs personnalises
- [ ] **A/B testing d'agents** : comparer les performances de differentes configurations

---

## 8. Indicateurs cles (KPIs)

### Metriques produit
| KPI | Cible Q3 2026 | Cible Q4 2026 | Cible Q2 2027 |
|-----|---------------|---------------|---------------|
| Utilisateurs actifs mensuels (MAU) | 500 | 2 000 | 10 000 |
| Agents crees | 200 | 1 000 | 5 000 |
| Questions posees / mois | 10 000 | 50 000 | 500 000 |
| Taux de satisfaction (likes) | 70% | 80% | 85% |
| Organisations actives | 20 | 80 | 300 |
| Documents ingeres | 5 000 | 25 000 | 100 000 |

### Metriques techniques
| KPI | Cible |
|-----|-------|
| Uptime | 99.9% |
| Latence P95 (reponse RAG) | < 3s |
| Latence P95 (pages frontend) | < 1s |
| Couverture de tests | > 80% |
| Temps de deploiement | < 10 min |
| Score securite (OWASP) | A |

### Metriques business
| KPI | Cible Q4 2026 | Cible Q2 2027 |
|-----|---------------|---------------|
| MRR (Monthly Recurring Revenue) | 5 000 EUR | 30 000 EUR |
| Clients payants | 15 | 80 |
| Churn mensuel | < 5% | < 3% |
| ARPU (Average Revenue Per User) | 50 EUR | 80 EUR |
| NPS (Net Promoter Score) | > 40 | > 50 |

---

## 9. Risques et mitigations

### Risques techniques
| Risque | Impact | Probabilite | Mitigation |
|--------|--------|-------------|------------|
| main.py monolithique ralentit le developpement | Eleve | Haute | Phase 1 : refactoring en routeurs |
| Faible couverture de tests = regressions | Eleve | Haute | Phase 1 : objectif 70%+ couverture |
| Dependance a un seul provider LLM | Moyen | Moyenne | Deja mitige : multi-provider (Mistral, OpenAI, Gemini, Perplexity) |
| Scalabilite du processing de documents | Eleve | Moyenne | Phase 5 : queue de taches (Celery/Cloud Tasks) |
| Fuite de donnees inter-tenant | Critique | Faible | RLS PostgreSQL + audit de permissions |
| Cout des API LLM | Eleve | Haute | Cache agressif (Redis), quotas par plan, suivi des couts |

### Risques business
| Risque | Impact | Probabilite | Mitigation |
|--------|--------|-------------|------------|
| Marche sature (RAG SaaS) | Eleve | Haute | Differenciation par les integrations (Notion, Drive, Slack, Neo4j) et le multi-agent |
| Reglementations IA (AI Act EU) | Moyen | Haute | Phase 5 : compliance proactive, transparence |
| Changement de pricing des API LLM | Moyen | Moyenne | Architecture multi-provider, modeles open-source en fallback |
| Difficulte d'acquisition client | Eleve | Moyenne | Templates pre-construits, onboarding simplifie, free tier |

---

## Priorites immediates (Sprint Mai 2026)

En resume, les chantiers les plus critiques pour les prochaines semaines :

1. **Refactoring main.py** : decoupage en routeurs FastAPI (impacte la velocite de developpement)
2. **Streaming des reponses** : feature la plus demandee par les utilisateurs
3. **Tests d'integration** : securiser la base avant d'ajouter de nouvelles features
4. **Dashboard analytique** : donner de la visibilite aux utilisateurs sur l'usage de leurs agents
5. **Rate limiting** : securiser les endpoints critiques contre les abus

---

*Ce document est vivant et sera mis a jour regulierement en fonction des retours utilisateurs, des evolutions du marche et des priorites business.*
