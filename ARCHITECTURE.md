# TAIC Companion - Architecture Technique Exhaustive

> Document a destination du CTO - Genere le 11/02/2026
> Version: 1.0

---

## TABLE DES MATIERES

1. [Vue d'ensemble](#1-vue-densemble)
2. [Diagramme d'architecture globale](#2-diagramme-darchitecture-globale)
3. [Backend (FastAPI)](#3-backend-fastapi)
4. [Frontend (Next.js)](#4-frontend-nextjs)
5. [Base de donnees (PostgreSQL)](#5-base-de-donnees-postgresql)
6. [Pipeline RAG](#6-pipeline-rag)
7. [Integrations LLM](#7-integrations-llm)
8. [Securite](#8-securite)
9. [Infrastructure & Deploiement](#9-infrastructure--deploiement)
10. [Flux de donnees critiques](#10-flux-de-donnees-critiques)
11. [Integrations externes](#11-integrations-externes)
12. [Points d'attention & dette technique](#12-points-dattention--dette-technique)

---

## 1. VUE D'ENSEMBLE

**TAIC Companion** est une plateforme SaaS B2B permettant de creer des chatbots IA d'entreprise bases sur du RAG (Retrieval-Augmented Generation). Les utilisateurs uploadent des documents, creent des agents IA personnalises, et ces agents repondent aux questions en se basant sur le contenu des documents.

### Stack technique

| Couche | Technologie | Version |
|--------|-------------|---------|
| Backend API | FastAPI (Python) | 3.11 |
| Frontend | Next.js (Pages Router) | 14.0.0 |
| UI Framework | React + Tailwind CSS | 18.2.0 / 3.3.5 |
| Base de donnees | PostgreSQL | 15 |
| Cache / Rate Limiting | Redis | 7-alpine |
| Recherche vectorielle | Cosine similarity (numpy) | - |
| Embeddings | OpenAI text-embedding-3-small | 1536 dim |
| LLM Providers | OpenAI, Mistral, Google Gemini | Multi-provider |
| Stockage fichiers | Google Cloud Storage | - |
| Deploiement | Google Cloud Run | europe-west1 |
| CI/CD | Google Cloud Build | - |
| Secrets | Google Secret Manager | - |
| i18n | next-i18next | FR/EN |

---

## 2. DIAGRAMME D'ARCHITECTURE GLOBALE

```
                                   INTERNET
                                      |
                          +-----------+-----------+
                          |                       |
                   +------v------+         +------v------+
                   |  FRONTEND   |         |   SLACK     |
                   |  Cloud Run  |         |   Webhook   |
                   |  Next.js 14 |         +------+------+
                   |  :3000      |                |
                   |  512Mi/1CPU |                |
                   +------+------+                |
                          |                       |
                          | HTTPS (Authorization  |
                          | header + cookie)      |
                          |                       |
                   +------v-----------------------v------+
                   |           BACKEND (FastAPI)         |
                   |           Cloud Run :8080           |
                   |           4Gi / 1CPU                |
                   |           0-10 instances             |
                   +--+-------+-------+-------+-------+--+
                      |       |       |       |       |
               +------v+  +--v---+ +-v----+ +v-----+ +v-----------+
               |Postgres|  |Redis | | GCS  | |Secret| |VPC Connector|
               |CloudSQL|  |Memory | |Bucket| |Mgr  | |   Redis     |
               |  :5432 |  |Store | |Docs  | |      | | 10.170.x.x |
               +--------+  +------+ +------+ +------+ +-------------+
                                        |
                              +---------+---------+
                              |         |         |
                         +----v---+ +---v----+ +--v-----+
                         | OpenAI | |Mistral | | Gemini |
                         |  API   | |  API   | |VertexAI|
                         +--------+ +--------+ +--------+
```

### Flux de communication

```
Utilisateur --> Frontend (Next.js, CSR)
                    |
                    |--> localStorage (JWT token)
                    |--> Authorization: Bearer {token}
                    |
                    v
               Backend (FastAPI)
                    |
                    |--> PostgreSQL (donnees relationnelles)
                    |--> Redis (rate limiting distribue)
                    |--> GCS (fichiers documents, photos agents)
                    |--> Secret Manager (cles API, credentials)
                    |--> LLM Provider (OpenAI/Mistral/Gemini)
                    |
                    v
               Reponse JSON --> Frontend --> Utilisateur
```

---

## 3. BACKEND (FastAPI)

### 3.1 Structure des fichiers

```
backend/
├── main.py              # App FastAPI, 80+ endpoints, middleware, CORS (~120KB)
├── auth.py              # JWT, bcrypt, verification token
├── database.py          # SQLAlchemy models, engine config
├── rag_engine.py        # Pipeline RAG complet
├── actions.py           # Actions Google Docs/Sheets (~43KB)
├── file_loader.py       # Extraction texte multi-format
├── openai_client.py     # Client OpenAI (chat + embeddings)
├── mistral_client.py    # Client Mistral
├── gemini_client.py     # Client Gemini via Vertex AI
├── encryption.py        # Chiffrement Fernet (AES-128-CBC)
├── requirements.txt     # ~40 dependances Python
└── Dockerfile           # python:3.11-slim, non-root user
```

### 3.2 Inventaire complet des endpoints API (~45+ endpoints)

#### Authentification

| Methode | Route | Auth | Rate Limit | Description |
|---------|-------|------|------------|-------------|
| `POST` | `/register` | Non | 5/15min | Inscription (username, email, password) |
| `POST` | `/login` | Non | 5/15min | Connexion, retourne JWT + set cookie HttpOnly |
| `GET` | `/auth/verify` | Cookie/Header | - | Verification status authentification |
| `POST` | `/logout` | Oui | - | Suppression cookie HttpOnly |
| `POST` | `/forgot-password` | Non | 5/15min | Demande reset password (envoie email) |
| `POST` | `/reset-password` | Non | 5/15min | Reset password avec token |

#### Gestion des Agents

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `GET` | `/agents` | Oui | Liste des agents de l'utilisateur |
| `POST` | `/agents` | Oui | Creation agent (name, contexte, biographie, statut, type, llm_provider, email_tags, photo) |
| `GET` | `/agents/{id}` | Oui | Detail d'un agent |
| `PUT` | `/agents/{id}` | Oui | Mise a jour agent |
| `DELETE` | `/agents/{id}` | Oui | Suppression agent + cascade (docs, conversations, teams) |

#### Gestion des Documents

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/upload` | Oui | Upload document (attache au user) |
| `POST` | `/upload-agent` | Oui | Upload document pour un agent specifique |
| `POST` | `/upload-url` | Oui | Ingestion URL web comme document |
| `GET` | `/user/documents` | Oui | Liste documents (optionnel: ?agent_id=X) |
| `DELETE` | `/documents/{id}` | Oui | Suppression document |
| `GET` | `/documents/{id}/download-url` | Oui | URL signee GCS (5 min expiry) |
| `GET` | `/documents/{id}/download` | Oui | Proxy download depuis GCS |
| `POST` | `/api/agent/extractText` | Oui | Extraction texte brut d'un fichier |

#### RAG & Question-Reponse

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/ask` | Oui | Requete RAG (question, agent_id OU team_id, selected_documents, conversation_id, history) |

#### Conversations & Messages

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/conversations` | Non | Creer conversation (agent_id ou team_id) |
| `GET` | `/conversations` | Non | Lister conversations (?agent_id ou ?team_id) |
| `POST` | `/conversations/{id}/messages` | Non | Ajouter message (role: user/agent, content) |
| `GET` | `/conversations/{id}/messages` | Non | Recuperer messages (tri chronologique) |
| `PUT` | `/conversations/{id}/title` | Non | Modifier titre conversation |
| `DELETE` | `/conversations/{id}` | Non | Supprimer conversation + messages |
| `PATCH` | `/messages/{id}/feedback` | Non | Feedback like/dislike sur message |

#### Teams (Collaboration)

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `GET` | `/teams` | Oui | Lister equipes de l'utilisateur |
| `POST` | `/teams` | Oui | Creer equipe (name, contexte, leader_agent_id, action_agent_ids) |
| `GET` | `/teams/{id}` | Oui | Detail equipe |

#### Acces Public

| Methode | Route | Auth | Rate Limit | Description |
|---------|-------|------|------------|-------------|
| `GET` | `/public/agents/{id}` | Non | - | Profil agent public |
| `POST` | `/public/agents/{id}/chat` | Non | 60/h par IP | Chat avec agent public |

#### Integrations

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `POST` | `/slack/events` | Signature HMAC | Webhook Slack (mentions dans threads) |
| `POST` | `/api/emails/ingest` | X-API-Key header | Ingestion email depuis Cloud Function |
| `POST` | `/api/emails/upload-attachment` | X-API-Key header | Upload piece jointe email |

#### Utilisateur

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `GET` | `/api/user/export-data` | Oui | Export donnees RGPD (JSON) |
| `DELETE` | `/api/user/delete-account` | Oui | Suppression compte (?anonymize=false) |

#### Sante

| Methode | Route | Auth | Description |
|---------|-------|------|-------------|
| `GET` | `/` | Non | Health check racine |
| `GET` | `/health` | Non | Health check |
| `GET` | `/health-nltk` | Non | Health check NLTK/chunking |

### 3.3 Middleware & Configuration

```
Middleware Stack (ordre d'execution):
1. Security Headers middleware
   ├── Strict-Transport-Security: max-age=63072000; includeSubDomains
   ├── Content-Security-Policy (voir section Securite)
   ├── X-Frame-Options: DENY
   ├── X-Content-Type-Options: nosniff
   ├── X-XSS-Protection: 1; mode=block
   ├── Referrer-Policy: strict-origin-when-cross-origin
   └── Permissions-Policy: geolocation=(), microphone=(), camera=()

2. CORS middleware
   ├── Production: https://taic.ai, https://www.taic.ai, https://applydi-frontend-*.run.app
   ├── Development: http://localhost:3000, http://localhost:8080
   ├── Credentials: true
   ├── Methods: GET, POST, PUT, DELETE, OPTIONS, PATCH
   ├── Headers: Content-Type, Authorization, Accept, Origin, X-Requested-With
   └── Max-Age preflight: 600s (10 min)

3. Rate Limiting (Redis-backed)
   ├── Auth endpoints: 5 tentatives / 15 min par IP
   ├── Public chat: 60 messages / heure par IP
   └── Fallback: in-memory si Redis indisponible
```

---

## 4. FRONTEND (Next.js)

### 4.1 Structure des fichiers

```
frontend/
├── pages/
│   ├── _app.js                    # App wrapper (appWithTranslation)
│   ├── _document.js               # Document HTML structure
│   ├── index.js                   # Dashboard Q&A principal (~995 lignes)
│   ├── login.js                   # Login/Register (274 lignes)
│   ├── agent-login.js             # Login specifique agent
│   ├── agents.js                  # Gestion agents CRUD (~890 lignes)
│   ├── profile.js                 # Profil utilisateur (447 lignes)
│   ├── teams.js                   # Liste equipes
│   ├── forgot-password.js         # Demande reset password
│   ├── reset-password.js          # Reset password avec token
│   ├── teams/
│   │   ├── create.js              # Creation equipe (127 lignes)
│   │   └── [id].js                # Detail equipe
│   ├── chat/
│   │   ├── [agentId].js           # Chat avec agent (auth)
│   │   └── team/[id].js           # Chat equipe
│   ├── public/agents/[agentId].js # Chat agent public (sans auth)
│   └── api/ask.js                 # API route Next.js (proxy)
├── components/
│   ├── LanguageSwitcher.js        # Selecteur FR/EN (79 lignes)
│   └── ConversationComponents.js  # Placeholder composants chat
├── hooks/
│   └── useAuth.js                 # Hook verification auth (83 lignes)
├── lib/
│   └── api.js                     # Instance axios configuree (59 lignes)
├── utils/
│   └── navigation.js              # Navigation locale-aware (19 lignes)
├── styles/
│   └── globals.css                # Styles globaux + animations (142 lignes)
├── public/
│   ├── favicon.ico
│   ├── logo-and.png               # Logo TAIC
│   └── locales/
│       ├── fr/ (8 fichiers JSON)
│       └── en/ (8 fichiers JSON)
├── next.config.js                 # Config Next.js + security headers
├── tailwind.config.js             # Config Tailwind
├── next-i18next.config.js         # Config i18n (FR/EN)
├── package.json                   # Dependances
└── Dockerfile                     # Multi-stage build (node:18-alpine)
```

### 4.2 Pages & Routes

| Route | Fichier | Auth | Rendu | Description |
|-------|---------|------|-------|-------------|
| `/login` | login.js | Non | CSR | Login/Register dual-mode |
| `/agent-login` | agent-login.js | Non | CSR | Login agent |
| `/forgot-password` | forgot-password.js | Non | CSR | Demande reset |
| `/reset-password?token=X` | reset-password.js | Non | CSR | Reset password |
| `/` | index.js | **Oui** | CSR | Dashboard Q&A + documents |
| `/agents` | agents.js | **Oui** | CSR | Gestion agents CRUD |
| `/profile` | profile.js | **Oui** | CSR | Profil, stats, export RGPD |
| `/teams` | teams.js | **Oui** | CSR | Liste equipes |
| `/teams/create` | teams/create.js | **Oui** | CSR | Creation equipe |
| `/teams/[id]` | teams/[id].js | **Oui** | CSR | Detail equipe |
| `/chat/[agentId]` | chat/[agentId].js | **Oui** | CSR | Chat agent authentifie |
| `/chat/team/[id]` | chat/team/[id].js | **Oui** | CSR | Chat equipe |
| `/public/agents/[agentId]` | public/agents/[agentId].js | Non | CSR | Chat agent public |

> **IMPORTANT:** Toutes les pages protegees utilisent l'auth **cote client uniquement** (useEffect + localStorage). Pas de `getServerSideProps` car les cookies cross-domain ne fonctionnent pas entre les domaines Cloud Run.

### 4.3 Gestion d'etat

**Approche:** `useState` distribue par page (pas de Redux/Zustand/Context global)

```
pages/index.js    → 22+ variables useState (question, answer, documents, selectedDocs, darkMode...)
pages/agents.js   → 19+ variables useState (agents, editingAgent, form, agentDocuments...)
pages/profile.js  → Variables useState pour stats, modals
pages/chat/*.js   → Variables useState pour conversations, messages, input
```

**Implications:**
- Pas de state partage entre pages
- Chaque page fetch ses donnees independamment
- Simule pour petite equipe, mais limitant a l'echelle

### 4.4 Appels API

**URL Backend auto-detectee:**
```javascript
const getApiUrl = () => {
  if (process.env.NEXT_PUBLIC_API_URL) return it;
  if (window.location.hostname.includes("run.app"))
    return window.location.origin.replace("frontend", "backend");
  return "http://localhost:8080";
};
```

**Headers standards:**
```javascript
{
  Authorization: `Bearer ${localStorage.getItem("token")}`,
  "Content-Type": "application/json"
  // withCredentials: true (cookies HttpOnly en backup)
}
```

### 4.5 Fonctionnalites cles

- **Dark mode** avec persistance localStorage
- **Drag & Drop** upload fichiers (react-dropzone)
- **Reconnaissance vocale** (Web Speech API / webkitSpeechRecognition)
- **Rendu Markdown** avec sanitization DOMPurify
- **Internationalisation** FR/EN (next-i18next, 8 namespaces)
- **Raccourcis clavier** : Ctrl+K (focus recherche), Esc (effacer)
- **Animations** : blob, fade-in, scale-in avec delais staggers

---

## 5. BASE DE DONNEES (PostgreSQL)

### 5.1 Schema des modeles

```
┌─────────────────────────────────────────────────────────────────┐
│                         USERS                                    │
├─────────────────────────────────────────────────────────────────┤
│ id          │ Integer    │ PK, autoincrement                     │
│ username    │ String(50) │ UNIQUE, INDEX                         │
│ email       │ String(100)│ UNIQUE, INDEX                         │
│ hashed_pass │ String(255)│ bcrypt hash                           │
│ created_at  │ DateTime   │ default=utcnow                        │
├─────────────┴────────────┴───────────────────────────────────────┤
│ Relations: documents (1:N), agents (1:N)                         │
│ Cascade: all, delete-orphan                                      │
└─────────────────────────────────────────────────────────────────┘
         │                          │
         │ user_id (FK)             │ user_id (FK)
         ▼                          ▼
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│          AGENTS                  │  │         TEAMS                    │
├─────────────────────────────────┤  ├─────────────────────────────────┤
│ id             │ Integer PK      │  │ id               │ Integer PK   │
│ name           │ String(100)     │  │ name             │ String(200)  │
│ contexte       │ Text (nullable) │  │ contexte         │ Text         │
│ biographie     │ Text (nullable) │  │ leader_agent_id  │ Integer      │
│ profile_photo  │ String(255)     │  │ action_agent_ids │ Text (JSON)  │
│ statut         │ String(10)      │  │ user_id          │ Integer FK   │
│                │ "public/private"│  │ created_at       │ DateTime     │
│ type           │ String(32)      │  └─────────────────────────────────┘
│                │ conversationnel │
│                │ actionnable     │
│                │ recherche_live  │
│ llm_provider   │ String(32)      │
│                │ openai/mistral  │
│                │ /gemini         │
│ user_id        │ Integer FK      │
│ embedding      │ Text (JSON arr) │
│ created_at     │ DateTime        │
│ finetuned_model│ String(255)     │
│ _slack_bot_tok │ Text (encrypted)│
│ slack_team_id  │ String(64)      │
│ slack_bot_uid  │ String(64)      │
│ _slack_sign_sec│ Text (encrypted)│
│ email_tags     │ Text (JSON arr) │
├───────────────┴──────────────────┤
│ Relations: documents (1:N)       │
│ Properties: slack_bot_token,     │
│   slack_signing_secret (encrypt) │
└─────────────────────────────────┘
         │
         │ agent_id (FK)
         ▼
┌─────────────────────────────────┐
│        DOCUMENTS                 │
├─────────────────────────────────┤
│ id          │ Integer PK         │
│ filename    │ String(255)        │
│ content     │ Text               │
│ user_id     │ Integer FK         │
│ agent_id    │ Integer FK (null)  │
│ created_at  │ DateTime           │
│ gcs_url     │ String(512)        │
├─────────────┴────────────────────┤
│ Relations: chunks (1:N)          │
│ Cascade: all, delete-orphan      │
└─────────────────────────────────┘
         │
         │ document_id (FK)
         ▼
┌─────────────────────────────────┐
│      DOCUMENT_CHUNKS             │
├─────────────────────────────────┤
│ id          │ Integer PK         │
│ document_id │ Integer FK         │
│ chunk_text  │ Text               │
│ embedding   │ Text (JSON, 1536f) │
│ chunk_index │ Integer            │
│ created_at  │ DateTime           │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│      CONVERSATIONS               │
├─────────────────────────────────┤
│ id          │ Integer PK         │
│ agent_id    │ Integer FK (null)  │
│ team_id     │ Integer FK (null)  │
│ title       │ String(255)        │
│ created_at  │ DateTime           │
├─────────────┴────────────────────┤
│ Relations: messages (1:N)        │
│ Cascade: all, delete-orphan      │
└─────────────────────────────────┘
         │
         │ conversation_id (FK)
         ▼
┌─────────────────────────────────┐
│         MESSAGES                 │
├─────────────────────────────────┤
│ id              │ Integer PK     │
│ conversation_id │ Integer FK     │
│ role            │ String(20)     │
│                 │ "user"/"agent" │
│ content         │ Text           │
│ timestamp       │ DateTime       │
│ feedback        │ String(10)     │
│                 │ "like"/"dislike│
│ buffered        │ Integer (0/1)  │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│   PASSWORD_RESET_TOKENS          │
├─────────────────────────────────┤
│ id         │ Integer PK          │
│ user_id    │ Integer FK          │
│ token      │ String(128) UNIQUE  │
│            │ (SHA-256 hash)      │
│ expires_at │ DateTime (15 min)   │
│ used       │ Boolean             │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│       AGENT_ACTIONS              │
├─────────────────────────────────┤
│ id          │ Integer PK         │
│ user_id     │ Integer FK         │
│ agent_id    │ Integer FK         │
│ action_type │ String(100)        │
│             │ create_google_doc  │
│             │ create_google_sheet│
│ params      │ Text (JSON)        │
│ result      │ Text (JSON)        │
│ status      │ String(32)         │
│             │ pending/completed  │
│             │ /failed            │
│ created_at  │ DateTime           │
└─────────────────────────────────┘
```

### 5.2 Configuration connexion

```
Engine PostgreSQL:
├── Pool size: 5 connexions
├── Max overflow: 10 connexions additionnelles
├── Pool pre-ping: True (validation connexion avant utilisation)
├── Pool recycle: 300s (renouvellement toutes les 5 min)
├── Echo: False (pas de logs SQL)
├── Indexes: username, email, user_id, agent_id, document_id
└── Fallback local: postgresql://raguser:ragpassword@localhost:5432/ragdb
```

---

## 6. PIPELINE RAG

### 6.1 Flux d'ingestion de documents

```
Document Upload (PDF/DOCX/PPTX/XLSX/TXT/CSV/ICS)
        │
        ▼
┌─ Validation ──────────────────────┐
│ 1. Extension whitelist            │
│ 2. Magic bytes verification       │
│ 3. Taille max: 10 MB             │
│ 4. PDF max: 500 pages            │
│ 5. URL max: 200 KB               │
└──────────┬────────────────────────┘
           ▼
┌─ Upload GCS ──────────────────────┐
│ Bucket: applydi-documents         │
│ Nom: {timestamp}_{sanitized_name} │
└──────────┬────────────────────────┘
           ▼
┌─ Extraction Texte ────────────────┐
│ PDF  → pdfplumber (text)          │
│        pytesseract (OCR si vide)  │
│ DOCX → python-docx               │
│ PPTX → python-pptx               │
│ XLSX → openpyxl                   │
│ URL  → readability-lxml + BS4    │
│ TXT/CSV → lecture directe         │
└──────────┬────────────────────────┘
           ▼
┌─ Chunking ────────────────────────┐
│ Taille chunk: 2000 caracteres     │
│ Overlap: 200 caracteres           │
│ Mode auto:                        │
│   >10 newlines → paragraphe mode  │
│   sinon → sentence mode (NLTK)    │
│ Tokenizer: punkt (NLTK)          │
└──────────┬────────────────────────┘
           ▼
┌─ Embedding ───────────────────────┐
│ Modele: text-embedding-3-small    │
│ Dimensions: 1536                  │
│ Si chunk > 8192 tokens:           │
│   split + moyenne des embeddings  │
│ Retry: 5x avec backoff exponentiel│
│ Fallback: vecteur zero [0.0]*1536 │
└──────────┬────────────────────────┘
           ▼
┌─ Stockage ────────────────────────┐
│ Document → table documents        │
│ Chunks → table document_chunks    │
│   (chunk_text + embedding JSON)   │
└───────────────────────────────────┘
```

### 6.2 Flux de requete RAG

```
Question Utilisateur
        │
        ├── agent_id OU team_id
        ├── selected_documents (optionnel)
        ├── conversation_id (optionnel)
        └── history (optionnel)
        │
        ▼
┌─ Cache Check ─────────────────────┐
│ Cle: user_id + hash(question)     │
│      + hash(doc_ids) + agent_type │
│ TTL: 5 minutes                    │
│ Max entries: 10 (in-memory)       │
└──────────┬────────────────────────┘
           │ (cache miss)
           ▼
┌─ Team Routing (si team_id) ──────┐
│ 1. Embedding de la question       │
│ 2. Cosine similarity vs agents    │
│ 3. Route vers agent le plus       │
│    semantiquement proche          │
│ 4. Fallback: leader agent         │
└──────────┬────────────────────────┘
           ▼
┌─ Recherche Similaire ────────────┐
│ 1. Embedding question             │
│    (text-embedding-3-small)       │
│ 2. Query DocumentChunk + Document │
│ 3. Filtre: user/agent/selected    │
│ 4. Cosine similarity (numpy)     │
│ 5. Top-K:                         │
│    - Standard: 8 chunks           │
│    - Si doc mentionne: 20 chunks  │
│ 6. Chunks voisins (avant/apres)   │
│ 7. Tri par similarite descendant  │
└──────────┬────────────────────────┘
           ▼
┌─ Construction Prompt ────────────┐
│ System Message:                   │
│   ├── Agent contexte (personnalite│
│   ├── Liste docs disponibles      │
│   └── Extraits RAG par document   │
│                                   │
│ Historique: 10 derniers echanges  │
│                                   │
│ User Message: question originale  │
└──────────┬────────────────────────┘
           ▼
┌─ Appel LLM ──────────────────────┐
│ Selection provider (priorite):    │
│   1. finetuned_model_id (si set)  │
│   2. agent.llm_provider           │
│   3. agent.type:                  │
│      conversationnel → OpenAI     │
│      actionnable → Gemini         │
│      recherche_live → Perplexity  │
│   4. Fallback: OpenAI gpt-4.1    │
│                                   │
│ Temperature: 0.7                  │
│ Timeout: 120s                     │
│ Retry: 5x backoff exponentiel    │
└──────────┬────────────────────────┘
           ▼
┌─ Post-traitement ────────────────┐
│ Si "actionnable":                 │
│   → Parse function_call           │
│   → Execute action (Google Docs)  │
│ Sinon:                            │
│   → Retour texte brut             │
│                                   │
│ Cache resultat (5 min)            │
│ Sauvegarde message en DB          │
└───────────────────────────────────┘
```

---

## 7. INTEGRATIONS LLM

### 7.1 OpenAI

```
Configuration:
├── API Key: OPENAI_API_KEY (Secret Manager)
├── Modele par defaut: gpt-4.1 (production)
├── Max tokens: 32768 (production)
├── Embedding: text-embedding-3-small (1536 dim)
├── Timeout: 120s
├── Max retries: 3 (client) + 5 (application)
├── HTTP Client: httpx
│   ├── Max connections: 5
│   ├── Max keepalive: 2
│   └── HTTP/1.1 force
└── Temperature: 0.7

Fonctions:
├── get_embedding_fast(text) → List[float] (1536)
├── get_chat_response(messages, model_id) → str
└── get_chat_response_structured(messages, functions) → Message
    └── Support function calling (agents actionnables)
```

### 7.2 Mistral

```
Configuration:
├── API Key: MISTRAL_API_KEY (Secret Manager)
├── Modele par defaut: mistral-small-latest
├── Aliases: small, medium, large, default
├── Max tokens: 16000
└── Temperature: 0.7

Fonction:
└── generate_text(prompt, model_name) → str
```

### 7.3 Google Gemini (Vertex AI)

```
Configuration:
├── Auth: Application Default Credentials (ADC)
│   └── Pas d'API Key, utilise Service Account
├── Projet: GOOGLE_CLOUD_PROJECT (applydi)
├── Region: europe-west1
├── Modele: gemini-2.0-flash-001
├── Max tokens: 16000
├── Temperature: 0.0
└── API: Vertex AI REST (pas SDK Python)
    └── https://{location}-aiplatform.googleapis.com/v1/...

Fonction:
└── generate_text(prompt, model_name) → str
```

### 7.4 Matrice de routage LLM

```
┌───────────────────┬────────────────┬───────────────────────┐
│ Agent Type        │ Provider       │ Modele                │
├───────────────────┼────────────────┼───────────────────────┤
│ conversationnel   │ OpenAI         │ gpt-4.1               │
│ actionnable       │ Gemini         │ gemini-2.0-flash-001  │
│ recherche_live    │ Perplexity*    │ (fallback OpenAI)     │
│ (llm_provider=X)  │ Prioritaire    │ Modele du provider X  │
│ (finetuned_model) │ Top priorite   │ Le modele fine-tune   │
└───────────────────┴────────────────┴───────────────────────┘
* Perplexity mentionne dans le code mais fallback vers OpenAI en pratique
```

---

## 8. SECURITE

### 8.1 Authentification

```
┌─ Authentification ────────────────────────────────────────────┐
│                                                                │
│  Password Hashing                                              │
│  ├── Algorithme: bcrypt                                        │
│  ├── Rounds: 12 (salt auto-genere)                            │
│  └── Verification: constant-time comparison                    │
│                                                                │
│  JWT Tokens                                                    │
│  ├── Algorithme: HS256                                         │
│  ├── Secret: JWT_SECRET_KEY (Secret Manager)                   │
│  ├── Expiration: 24 heures                                     │
│  ├── Payload: {"sub": user_id, "exp": timestamp}              │
│  └── Transport: Authorization header + Cookie HttpOnly         │
│                                                                │
│  Cookie Configuration                                          │
│  ├── HttpOnly: True (pas accessible en JS)                     │
│  ├── Secure: True (HTTPS uniquement)                           │
│  ├── SameSite: None (cross-domain Cloud Run)                   │
│  ├── Max-Age: 86400s (24h)                                     │
│  └── ⚠️ Cross-domain: PAS FIABLE entre Cloud Run services     │
│                                                                │
│  Approche Hybride (Production)                                 │
│  ├── 1. localStorage + Authorization header (PRINCIPAL)        │
│  ├── 2. Cookie HttpOnly (BACKUP)                               │
│  └── 3. Auth check CLIENT-SIDE uniquement (useEffect)          │
│                                                                │
│  Password Reset                                                │
│  ├── Token: UUID → SHA-256 hash stocke en DB                  │
│  ├── Expiration: 15 minutes                                    │
│  ├── Usage unique: flag "used"                                 │
│  └── Envoi par email (SMTP)                                    │
│                                                                │
│  Rate Limiting                                                 │
│  ├── Auth: 5 tentatives / 15 min par IP                        │
│  ├── Public chat: 60 messages / heure par IP                   │
│  ├── Backend: Redis distribue (cross-instances)                │
│  └── Fallback: in-memory si Redis down                         │
└────────────────────────────────────────────────────────────────┘
```

### 8.2 Protection des donnees

```
┌─ Chiffrement ─────────────────────────────────────────────────┐
│                                                                │
│  En transit                                                    │
│  ├── HTTPS enforced (HSTS header)                              │
│  ├── TLS 1.2+ (Cloud Run managed)                             │
│  └── Cookies Secure=True                                       │
│                                                                │
│  Au repos                                                      │
│  ├── PostgreSQL (Cloud SQL): chiffrement disque Google         │
│  ├── GCS: chiffrement par defaut Google                        │
│  └── Donnees sensibles: Fernet (AES-128-CBC)                  │
│      ├── Slack bot tokens                                      │
│      ├── Slack signing secrets                                 │
│      ├── Format: "enc:{ciphertext}"                            │
│      └── Cle: ENCRYPTION_KEY (base64, Secret Manager)          │
│                                                                │
│  Secrets                                                       │
│  ├── Toutes les API keys dans Google Secret Manager            │
│  ├── Pas de secrets en dur dans le code                        │
│  └── Injection via --set-secrets dans Cloud Build              │
└────────────────────────────────────────────────────────────────┘
```

### 8.3 Headers de securite

```
Backend (main.py middleware):
├── Strict-Transport-Security: max-age=63072000; includeSubDomains
├── X-Frame-Options: DENY
├── X-Content-Type-Options: nosniff
├── X-XSS-Protection: 1; mode=block
├── Referrer-Policy: strict-origin-when-cross-origin
├── Permissions-Policy: geolocation=(), microphone=(), camera=()
└── Content-Security-Policy:
    ├── default-src 'none'
    ├── script-src 'self' https://cdn.jsdelivr.net
    ├── style-src 'self' https://fonts.googleapis.com
    ├── font-src 'self' https://fonts.gstatic.com
    ├── img-src 'self' data: https:
    ├── connect-src 'self' https://api.openai.com https://api.mistral.ai
    │                      https://generativelanguage.googleapis.com
    └── frame-ancestors 'none'

Frontend (next.config.js headers):
├── X-Frame-Options: DENY
├── X-Content-Type-Options: nosniff
├── X-XSS-Protection: 1; mode=block
├── Referrer-Policy: strict-origin-when-cross-origin
├── Permissions-Policy: geolocation=(), microphone=(), camera=()
├── Strict-Transport-Security: max-age=31536000; includeSubDomains
└── Content-Security-Policy:
    ├── default-src 'self'
    ├── script-src 'self' 'unsafe-inline' (requis pour Next.js hydration)
    ├── style-src 'self' 'unsafe-inline' https://fonts.googleapis.com
    ├── font-src 'self' https://fonts.gstatic.com
    ├── img-src 'self' data: https:
    ├── connect-src 'self' https://*.run.app https://api.openai.com
    └── frame-ancestors 'none'
```

### 8.4 Validation des entrees

```
Fichiers uploads:
├── Whitelist extensions: pdf, txt, docx, doc, pptx, xlsx, ics, csv
├── Magic bytes verification (contenu reel du fichier)
├── Taille max: 10 MB
├── Sanitization nom fichier (prevention path traversal)
└── PDF max pages: 500

Slack webhooks:
├── Signature HMAC-SHA256 par agent
├── Verification timestamp (max 5 min, anti-replay)
├── Comparaison constant-time (anti-timing attack)
└── Cache 500 event IDs (deduplication)

Email API:
├── Verification X-API-Key header
├── Comparaison constant-time
└── Deduplication par source_id

Sanitization HTML (Frontend):
├── DOMPurify sur tous les messages chat
├── Whitelist tags: strong, em, code, ul, li, br, p, div, span
└── Pas de dangerouslySetInnerHTML sans sanitization
```

### 8.5 Endpoints de debug supprimes

```
✅ SUPPRIMES (securite):
├── /test-jwt (exposait longueur secret JWT)
├── /test-auth (exposait credentials ADC)
├── /test-openai (exposait connectivite API)
├── /debug/whoami (exposait infos utilisateur)
└── /debug/test-openai-embeddings (exposait connectivite)
```

---

## 9. INFRASTRUCTURE & DEPLOIEMENT

### 9.1 Architecture Cloud (Google Cloud Platform)

```
┌─────────────────────────────────────────────────────────────┐
│                    Google Cloud - Projet: applydi            │
│                    Region: europe-west1                       │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                    Cloud Build                           │ │
│  │  Machine: E2_HIGHCPU_8                                   │ │
│  │  Timeout: 1800s (30 min)                                 │ │
│  │  Logging: CLOUD_LOGGING_ONLY                             │ │
│  │                                                          │ │
│  │  Pipeline:                                               │ │
│  │  1. Build backend Docker → gcr.io/applydi/applydi-backend│ │
│  │  2. Push to Container Registry                           │ │
│  │  3. Deploy backend to Cloud Run                          │ │
│  │  4. Get backend URL                                      │ │
│  │  5. Build frontend Docker (with NEXT_PUBLIC_API_URL)     │ │
│  │  6. Push frontend to Container Registry                  │ │
│  │  7. Deploy frontend to Cloud Run                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──── Cloud Run Services ────────────────────────────────┐  │
│  │                                                         │  │
│  │  Backend (applydi-backend / dev-taic-backend)           │  │
│  │  ├── Image: gcr.io/applydi/applydi-backend              │  │
│  │  ├── Port: 8080                                          │  │
│  │  ├── Memory: 4Gi                                         │  │
│  │  ├── CPU: 1                                              │  │
│  │  ├── Min instances: 0 (scale to zero)                    │  │
│  │  ├── Max instances: 10                                   │  │
│  │  ├── Timeout: 300s                                       │  │
│  │  ├── VPC Connector: redis-connector                      │  │
│  │  ├── Allow unauthenticated: true                         │  │
│  │  └── Secrets: 9 secrets depuis Secret Manager            │  │
│  │                                                          │  │
│  │  Frontend (applydi-frontend / dev-taic-frontend)         │  │
│  │  ├── Image: gcr.io/applydi/applydi-frontend              │  │
│  │  ├── Port: 3000                                          │  │
│  │  ├── Memory: 512Mi                                       │  │
│  │  ├── CPU: 1                                              │  │
│  │  ├── Min instances: 0 (scale to zero)                    │  │
│  │  ├── Max instances: 5                                    │  │
│  │  ├── Allow unauthenticated: true                         │  │
│  │  └── Env: NEXT_PUBLIC_API_URL=backend_url                │  │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌──── Managed Services ──────────────────────────────────┐  │
│  │                                                         │  │
│  │  Cloud SQL (PostgreSQL 15)                              │  │
│  │  ├── Connexion via DATABASE_URL (Secret Manager)         │  │
│  │  ├── Pool: 5 connexions + 10 overflow                    │  │
│  │  └── Recycle: 300s                                       │  │
│  │                                                          │  │
│  │  Redis (Memorystore)                                     │  │
│  │  ├── IP: 10.170.82.115:6379                              │  │
│  │  ├── Acces via VPC Connector (redis-connector)           │  │
│  │  └── Usage: rate limiting distribue                       │  │
│  │                                                          │  │
│  │  Cloud Storage                                           │  │
│  │  ├── Bucket documents: applydi-documents                  │  │
│  │  ├── Bucket photos agents: applydi-agent-photos           │  │
│  │  └── URLs signees (5 min expiry) pour download            │  │
│  │                                                          │  │
│  │  Secret Manager (9 secrets)                              │  │
│  │  ├── OPENAI_API_KEY                                       │  │
│  │  ├── GEMINI_API_KEY                                       │  │
│  │  ├── MISTRAL_API_KEY                                      │  │
│  │  ├── DATABASE_URL / DATABASE_URL_DEV                      │  │
│  │  ├── JWT_SECRET_KEY                                       │  │
│  │  ├── EMAIL_INGEST_API_KEY                                 │  │
│  │  ├── SMTP_EMAIL / SMTP_PASSWORD                           │  │
│  │  └── ENCRYPTION_KEY                                       │  │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 Environnements

| | **Production** | **Development** |
|---|---|---|
| **Config** | `cloudbuild.yaml` | `cloudbuild_dev.yaml` |
| **Backend** | `applydi-backend` | `dev-taic-backend` |
| **Frontend** | `applydi-frontend` | `dev-taic-frontend` |
| **ENVIRONMENT** | `production` | `development` |
| **DB Secret** | `DATABASE_URL_DEV` | `DATABASE_URL` |
| **CORS Origins** | `applydi-frontend-*.run.app` | `dev-taic-frontend-*.run.app` |
| **OpenAI Model** | `gpt-4.1` | `gpt-4.1` |
| **Gemini Model** | `gemini-2.0-flash-001` | `gemini-2.0-flash-001` |

### 9.3 Docker Builds

**Backend (python:3.11-slim):**
```
Dependances systeme: gcc, g++, libpq-dev, curl, tesseract-ocr
Python: pip install requirements.txt + NLTK punkt
User: appuser (uid 1000, non-root)
Port: 8080
CMD: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
```

**Frontend (node:18-alpine, multi-stage):**
```
Stage 1 (dependencies): npm ci --only=production
Stage 2 (builder): npm ci + npm run build
  └── Build arg: NEXT_PUBLIC_API_URL (injecte a build time)
Stage 3 (runner): copie artefacts, user nextjs (uid 1001)
Port: 3000
CMD: npm start
```

### 9.4 Developpement local (docker-compose)

```yaml
Services:
  database:  PostgreSQL 15 (port 5432)
  redis:     Redis 7-alpine (port 6379)
  backend:   FastAPI (port 8080, depends: db+redis)
  frontend:  Next.js (port 3000, depends: backend)

Volumes:
  postgres_data: persistance BDD locale
```

### 9.5 Variables d'environnement

```
PRODUCTION (injectees via Cloud Build):
├── GOOGLE_CLOUD_PROJECT=applydi
├── ENVIRONMENT=production
├── GCS_BUCKET_NAME=applydi-documents
├── GEMINI_MODEL=gemini:gemini-2.0-flash-001
├── GEMINI_DEFAULT_MODEL=gemini-2.0-flash-001
├── GEMINI_LOCATION=europe-west1
├── OPENAI_MODEL=gpt-4.1
├── OPENAI_MAX_TOKENS=32768
├── ALLOWED_ORIGINS=https://applydi-frontend-817946451913.europe-west1.run.app
├── REDIS_HOST=10.170.82.115
├── REDIS_PORT=6379
└── NEXT_PUBLIC_API_URL=(auto-detected from backend deploy)

SECRETS (Secret Manager → env vars):
├── OPENAI_API_KEY
├── GEMINI_API_KEY
├── MISTRAL_API_KEY
├── DATABASE_URL (ou DATABASE_URL_DEV)
├── JWT_SECRET_KEY
├── EMAIL_INGEST_API_KEY
├── SMTP_EMAIL
├── SMTP_PASSWORD
└── ENCRYPTION_KEY
```

---

## 10. FLUX DE DONNEES CRITIQUES

### 10.1 Inscription & Connexion

```
┌──────────┐     POST /register          ┌──────────┐
│  Client  │ ──────────────────────────→  │ Backend  │
│ (Browser)│ {username, email, password}  │ (FastAPI)│
│          │                              │          │
│          │     POST /login              │          │
│          │ ──────────────────────────→  │          │
│          │ {username, password}          │          │
│          │                              │          │
│          │  ◀──────────────────────────  │          │
│          │  {access_token: JWT}          │          │
│          │  + Set-Cookie: token=JWT      │          │
│          │    (HttpOnly, Secure,         │          │
│          │     SameSite=None)            │          │
│          │                              │          │
│          │  localStorage.setItem(       │          │
│          │    "token", JWT)              │          │
└──────────┘                              └──────────┘
```

### 10.2 Question-Reponse RAG

```
Client                    Backend                   Services Externes
  │                          │                            │
  │  POST /ask               │                            │
  │  {question, agent_id,    │                            │
  │   selected_documents}    │                            │
  │ ────────────────────────>│                            │
  │                          │                            │
  │                          │─ Check cache (in-memory)   │
  │                          │                            │
  │                          │─ Get agent from DB         │
  │                          │  (PostgreSQL)              │
  │                          │                            │
  │                          │─ Get query embedding ─────>│ OpenAI API
  │                          │<──── [1536 floats] ────────│
  │                          │                            │
  │                          │─ Search similar chunks     │
  │                          │  (cosine similarity,       │
  │                          │   top-8, numpy)            │
  │                          │                            │
  │                          │─ Build prompt:             │
  │                          │  system + context + RAG    │
  │                          │  + history (10 derniers)   │
  │                          │                            │
  │                          │─ Call LLM ────────────────>│ OpenAI/Mistral/Gemini
  │                          │<──── response text ────────│
  │                          │                            │
  │                          │─ Save message to DB        │
  │                          │─ Cache result (5 min)      │
  │                          │                            │
  │  <────────────────────── │                            │
  │  {answer: "..."}         │                            │
```

### 10.3 Upload & Traitement Document

```
Client                    Backend                   Services Externes
  │                          │                            │
  │  POST /upload-agent      │                            │
  │  FormData: file +        │                            │
  │  agent_id                │                            │
  │ ────────────────────────>│                            │
  │                          │─ Validate file             │
  │                          │  (extension, magic bytes,  │
  │                          │   size < 10MB)             │
  │                          │                            │
  │                          │─ Upload to GCS ───────────>│ Cloud Storage
  │                          │  bucket: applydi-documents │
  │                          │                            │
  │                          │─ Extract text              │
  │                          │  (pdfplumber/docx/...)     │
  │                          │                            │
  │                          │─ Chunk text                │
  │                          │  (2000 chars, 200 overlap) │
  │                          │                            │
  │                          │─ For each chunk:           │
  │                          │  ├─ Get embedding ────────>│ OpenAI API
  │                          │  │<── [1536 floats] ──────│
  │                          │  └─ Save DocumentChunk     │
  │                          │     to PostgreSQL          │
  │                          │                            │
  │                          │─ Save Document to DB       │
  │                          │                            │
  │  <────────────────────── │                            │
  │  {document_id: 42}       │                            │
```

### 10.4 Flux Slack

```
Slack                     Backend                   Services
  │                          │                        │
  │  POST /slack/events      │                        │
  │  (app_mention event)     │                        │
  │ ────────────────────────>│                        │
  │                          │                        │
  │                          │─ Verify HMAC-SHA256    │
  │                          │  signature             │
  │                          │─ Check timestamp       │
  │                          │  (< 5 min)             │
  │                          │─ Dedup event ID        │
  │                          │  (cache 500 IDs)       │
  │                          │                        │
  │                          │─ Match bot_user_id     │
  │                          │  → find Agent in DB    │
  │                          │                        │
  │                          │─ Fetch thread history  │
  │                          │  via Slack API ───────>│ Slack API
  │                          │<──────────────────────│
  │                          │                        │
  │                          │─ Call get_answer()     │
  │                          │  (full RAG pipeline)   │
  │                          │                        │
  │                          │─ Post response ───────>│ Slack API
  │  <──────────────────────────────────────────────│ (thread reply)
```

### 10.5 Flux Email

```
Email                  Cloud Function           Backend
  │                          │                      │
  │  Email entrant           │                      │
  │ ────────────────────────>│                      │
  │                          │  POST /api/emails/   │
  │                          │  ingest               │
  │                          │  X-API-Key: xxx       │
  │                          │ ────────────────────>│
  │                          │                      │─ Verify API key
  │                          │                      │─ Extract @tags
  │                          │                      │  from subject
  │                          │                      │─ Match agents by
  │                          │                      │  email_tags field
  │                          │                      │─ Deduplicate
  │                          │                      │  (source_id)
  │                          │                      │─ Chunk + embed
  │                          │                      │─ Create Document
  │                          │                      │  + chunks per agent
```

---

## 11. INTEGRATIONS EXTERNES

### 11.1 Google Workspace (Agents Actionnables)

```
Actions disponibles:
├── create_google_doc
│   ├── Input: title, content (opt), folder_id (opt)
│   ├── Si pas de content: generation par LLM
│   ├── API: Google Docs API + Drive API
│   └── Output: {url: webViewLink, document_id: docId}
│
└── create_google_sheet
    ├── Input: title, sheets[] (title, headers, rows, formulas, conditional_formats)
    ├── API: Google Sheets API + Drive API
    └── Output: {url: webViewLink, spreadsheetId: id}

Credentials (priorite):
1. Secret Manager: DEFAULT_GOOGLE_SECRET_NAME
2. Per-agent Secret: agent-{id}-google-sa
3. Per-agent env: AGENT_{id}_GOOGLE_SA
4. DB Agent fields
5. Global: GOOGLE_APPLICATION_CREDENTIALS

Scopes:
├── https://www.googleapis.com/auth/documents
├── https://www.googleapis.com/auth/drive
└── https://www.googleapis.com/auth/spreadsheets
```

### 11.2 Slack

```
Configuration par agent:
├── slack_bot_token (chiffre Fernet)
├── slack_signing_secret (chiffre Fernet)
├── slack_team_id (workspace ID)
└── slack_bot_user_id (bot user dans le workspace)

Flux:
├── Webhook: POST /slack/events (app_mention)
├── Verification: HMAC-SHA256 signature
├── Historique: Fetch via Slack API (conversations.history)
├── Reponse: Post via Slack API (chat.postMessage)
└── Multi-workspace: Matching par bot_user_id + team_id
```

### 11.3 Email (Cloud Function)

```
Architecture:
├── Cloud Function recoit les emails
├── Appelle /api/emails/ingest (X-API-Key auth)
├── Routing par @tags dans le sujet
│   Ex: "Question @finance @rh" → agents avec tags matching
├── Deduplication par source_id
└── Piece jointes: /api/emails/upload-attachment
```

---

## 12. POINTS D'ATTENTION & DETTE TECHNIQUE

### 12.1 Problemes architecturaux

| Priorite | Probleme | Impact | Recommandation |
|----------|----------|--------|----------------|
| **HAUTE** | Recherche vectorielle in-memory (numpy cosine) au lieu de FAISS/pgvector | Performance degradee a l'echelle, O(n) par requete | Migrer vers pgvector ou FAISS index persistant |
| **HAUTE** | Cache RAG in-memory (pas distribue) | Chaque instance Cloud Run a son propre cache, max 10 entries | Migrer vers Redis pour cache distribue |
| **HAUTE** | Pas de tests automatises visibles | Risque de regression, pas de CI/CD quality gate | Ajouter pytest (backend) + Jest (frontend) |
| **MOYENNE** | main.py monolithique (~120KB, 80+ endpoints) | Difficile a maintenir, risque de conflits git | Decomposer en routers FastAPI (agents/, docs/, auth/, etc.) |
| **MOYENNE** | Embeddings stockes en JSON string dans Text columns | Parsing JSON a chaque recherche, pas d'index vectoriel | Migrer vers pgvector ou colonne native |
| **MOYENNE** | State management frontend distribue (22+ useState par page) | Pas de partage d'etat entre pages, duplication logique | Evaluer Zustand ou React Context pour auth/user |
| **BASSE** | NLTK telecharge a runtime (Dockerfile) | Fragilite au demarrage si echec download | Pre-installer dans image Docker |
| **BASSE** | Deduplication email via gcs_url (hack) | Pas de table dediee, fragile | Creer table email_dedup |

### 12.2 Securite - Points d'amelioration

| Point | Status | Recommandation |
|-------|--------|----------------|
| Token JWT dans localStorage | ⚠️ Vulnerable XSS | Migration progressive vers HttpOnly-only |
| Endpoints conversations sans auth | ⚠️ Pas d'auth | Ajouter verification token |
| CORS wildcard dev | ✅ Dev only | Verifier qu'il ne passe pas en prod |
| CSP unsafe-inline frontend | ⚠️ Requis Next.js | Evaluer nonce-based CSP |
| Rate limiting email API | ❌ Manquant | Ajouter rate limit sur /api/emails/* |
| Audit log | ❌ Manquant | Logger actions critiques (delete, export) |

### 12.3 Scalabilite

```
Limites actuelles:
├── Backend: 0-10 instances (Cloud Run auto-scale)
├── Frontend: 0-5 instances
├── DB Pool: 5+10 = 15 connexions max par instance
│   └── Avec 10 instances: 150 connexions max → OK pour Cloud SQL
├── Redis: IP fixe (single instance Memorystore)
├── Recherche vectorielle: O(n) par requete
│   └── Limite estimee: ~10K chunks avant degradation
├── Embedding calls: 1 par chunk upload + 1 par requete
│   └── Rate limit OpenAI a surveiller
└── LLM calls: 120s timeout
    └── Cold start Cloud Run + LLM latence
```

### 12.4 Metriques manquantes

```
Non implemente:
├── APM (Application Performance Monitoring)
├── Error tracking (Sentry ou equivalent)
├── Metriques business (usage par agent, tokens consommes)
├── Health check avec readiness/liveness (commente dans Dockerfile)
├── Logging structure (JSON structured logging)
└── Alerting (pas de monitoring Cloud Monitoring configure)
```

---

## ANNEXE: DEPENDANCES COMPLETES

### Backend (requirements.txt ~40 packages)

```
Framework:        fastapi, uvicorn[standard]
Database:         sqlalchemy, psycopg2-binary
Documents:        pdfplumber, python-docx, python-pptx, openpyxl,
                  pytesseract, readability-lxml
AI/NLP:           openai, mistralai, nltk, tiktoken, faiss-cpu
Cloud:            google-cloud-storage, google-cloud-secret-manager,
                  google-cloud-logging, google-cloud-monitoring,
                  google-api-python-client, google-auth
Security:         bcrypt, pyjwt, python-jose[cryptography],
                  python-multipart, cryptography
HTTP:             requests, httpx, beautifulsoup4
Utils:            pandas, tabulate, Pillow, reportlab,
                  python-dotenv, redis
```

### Frontend (package.json)

```
Core:             next@14.0.0, react@18.2.0, react-dom@18.2.0
i18n:             next-i18next@15.4.3, react-i18next@16.5.4, i18next@25.8.0
HTTP:             axios@1.6.0
UI:               tailwindcss@3.3.5, lucide-react@0.290.0
Markdown:         react-markdown@9.0.0, dompurify@3.3.1
Upload:           react-dropzone@14.2.3
Notifications:    react-hot-toast@2.4.1
CSS:              postcss@8.4.31, autoprefixer@10.4.16
```

---

> **Document genere automatiquement par Claude Code le 11/02/2026**
> **Pour toute question, contacter l'equipe technique.**
