# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TAIC Companion is a SaaS platform for creating enterprise AI chatbots using Retrieval-Augmented Generation (RAG). Users upload documents (PDF, TXT, DOCX) and create personalized AI agents that answer questions based on that content.

## Tech Stack

- **Backend:** FastAPI (Python 3.11), SQLAlchemy ORM, PostgreSQL 15, Redis 7
- **Frontend:** Next.js 14 (Pages Router), React 18, Tailwind CSS
- **AI Providers:** OpenAI, Mistral, Google Gemini (configurable per agent via `llm_provider` field)
- **Vector Search:** FAISS (CPU) with text-embedding-3-small
- **Deployment:** Google Cloud Run, Cloud SQL, Cloud Build

## Commands

### Local Development
```bash
# Full stack with Docker
docker-compose up --build

# Frontend only (port 3000)
cd frontend && npm run dev

# Backend only (port 8080)
cd backend && python -m uvicorn main:app --reload --port 8080

# Frontend lint
cd frontend && npm run lint
```

### Deployment
```bash
gcloud builds submit --config cloudbuild.yaml       # Production
gcloud builds submit --config cloudbuild_dev.yaml   # Development
```

## Architecture

### Backend (`backend/`)
- `main.py` - FastAPI app with 80+ REST endpoints (large file, ~120KB)
- `rag_engine.py` - Core RAG logic: document chunking, embedding, retrieval, response generation with 5-min caching
- `auth.py` - JWT authentication with bcrypt password hashing
- `database.py` - SQLAlchemy models (User, Agent, Document, DocumentChunk, Conversation, Message, Team)
- `openai_client.py`, `mistral_client.py`, `gemini_client.py` - LLM provider integrations
- `file_loader.py` - Multi-format document processing (PDF via pdfplumber, DOCX, PPTX, web content)
- `actions.py` - Business logic actions (~43KB)

### Frontend (`frontend/`)
- `pages/index.js` - Main Q&A dashboard
- `pages/agents.js` - Agent management (~43KB, handles CRUD, document upload, settings)
- `pages/login.js` - Authentication (login/signup)
- `pages/teams.js` - Team collaboration features
- `components/ConversationComponents.js` - Chat UI components

### Key Data Flow
1. Documents uploaded → processed by `file_loader.py` → chunked in `rag_engine.py` → embeddings stored
2. User query → relevant chunks retrieved via FAISS → combined with agent context → sent to LLM provider
3. Agent settings determine: personality (contexte, biographie), LLM provider, response style

## Database Models

- **Agent:** Has `llm_provider` (openai/mistral/gemini), `type` (conversationnel/actionnable/recherche_live), `statut` (public/private)
- **Document/DocumentChunk:** Documents split into chunks with overlap for context preservation
- **Conversation/Message:** Chat history with role-based messages (user/assistant)

## Environment Variables

Critical variables (see `.env.example`):
- `OPENAI_API_KEY`, `MISTRAL_API_KEY`, `GEMINI_API_KEY` - LLM credentials
- `DATABASE_URL` - PostgreSQL connection string
- `JWT_SECRET_KEY` - Auth token signing
- `NEXT_PUBLIC_API_URL` - Backend URL for frontend
- `GCS_BUCKET_NAME` - Document storage bucket

## Deployment Architecture

- **Cloud Run:** Backend (4Gi memory, 0-10 instances), Frontend (512Mi memory, 0-5 instances)
- **Cloud SQL:** PostgreSQL 15 managed instance
- **Cloud Storage:** Document file storage
- **Secret Manager:** All API keys and credentials
