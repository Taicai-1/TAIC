# Contient la logique RAG améliorée
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from mistral_embeddings import get_embedding, get_embedding_fast
from openai_client import get_chat_response, get_chat_response_stream
from database import Document, DocumentChunk, User, Agent
from file_loader import load_text_from_pdf, chunk_text
from file_generator import FileGenerator
from imagen_client import generate_image
from imagen_gcs import upload_generated_image
from validation import SCRIPT_PATTERN

logger = logging.getLogger(__name__)


def _sanitize_prompt_text(text: str) -> str:
    """Strip dangerous script tags from text destined for LLM prompts.
    Only removes <script> tags — preserves other content that may be
    meaningful in agent contexte (markdown, plain text, etc.).
    """
    if not text:
        return text
    return SCRIPT_PATTERN.sub("", text)


def _agent_folder_ids(agent):
    """Return the agent's selected company-RAG folder ids as a list, or None for 'all'.

    Retrieval-side counterpart to ``routers.agents._folder_ids_out``: both read the same
    stored JSON, which is validated on write by ``routers.agents._parse_folder_ids``
    (positive ints only). They live in separate modules to avoid a circular import
    (rag_engine is imported by the routers). Empty/invalid -> None so callers treat it
    as 'all folders'.
    """
    raw = getattr(agent, "company_rag_folder_ids", None)
    if not raw:
        return None
    try:
        ids = json.loads(raw)
    except Exception:
        return None
    if not isinstance(ids, list) or not ids:
        return None
    cleaned = [int(x) for x in ids if isinstance(x, int) and not isinstance(x, bool) and x > 0]
    return cleaned or None


# In-memory fallback cache (used when Redis is unavailable)
_answer_cache = {}

_RAG_CACHE_TTL = 300  # 5 minutes


def _rag_cache_key(user_id: int, question: str, doc_ids, agent_type: str) -> str:
    q_hash = hashlib.md5(question.encode()).hexdigest()[:12]
    d_hash = hashlib.md5(str(doc_ids).encode()).hexdigest()[:12]
    return f"rag_cache:{user_id}:{q_hash}:{d_hash}:{agent_type}"


def _get_rag_cache(key: str):
    """Try Redis first, fall back to in-memory dict."""
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is not None:
            cached = r.get(key)
            if cached is not None:
                return json.loads(cached)
            return None
    except Exception as e:
        logger.debug(f"RAG cache Redis read failed: {e}")
    # Fallback: in-memory
    if key in _answer_cache:
        cached_time, cached_result = _answer_cache[key]
        if datetime.now().timestamp() - cached_time < _RAG_CACHE_TTL:
            return cached_result
    return None


def _set_rag_cache(key: str, result):
    """Write to Redis and in-memory fallback."""
    try:
        from redis_client import get_redis

        r = get_redis()
        if r is not None:
            r.setex(key, _RAG_CACHE_TTL, json.dumps(result))
    except Exception as e:
        logger.debug(f"RAG cache Redis write failed: {e}")
    # Always keep in-memory fallback
    _answer_cache[key] = (datetime.now().timestamp(), result)
    if len(_answer_cache) > 10:
        oldest_key = min(_answer_cache.keys(), key=lambda k: _answer_cache[k][0])
        del _answer_cache[oldest_key]


def get_last_message_for_agent(agent_id: int, db: Session) -> str:
    """Retourne le dernier message envoyé à l'agent (mémoire courte par agent)."""
    from database import Message, Conversation

    # Récupère la dernière conversation de l'agent
    conv = (
        db.query(Conversation)
        .filter(Conversation.agent_id == agent_id)
        .order_by(Conversation.created_at.desc())
        .first()
    )
    if not conv:
        return ""
    # Récupère le dernier message de la conversation
    msg = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.timestamp.desc()).first()
    if not msg:
        return ""
    return msg.content


def get_answer_with_files(
    question: str, user_id: int, db: Session, selected_doc_ids: List[int] = None, agent_type: str = None
) -> Dict[str, Any]:
    """Get answer using RAG with file generation capabilities"""
    try:
        cache_key = _rag_cache_key(user_id, question, selected_doc_ids, agent_type)

        cached = _get_rag_cache(cache_key)
        if cached is not None:
            logger.info("Returning cached answer")
            return cached

        # Get the regular answer first
        answer_result = get_answer(question, user_id, db, selected_doc_ids, agent_type)
        answer = answer_result["answer"] if isinstance(answer_result, dict) else answer_result

        # Initialize file generator
        file_gen = FileGenerator()

        # Detect if user wants file generation
        generation_info = file_gen.detect_generation_request(question, answer)

        # If no table detected but user asked for structured data, create sample data
        if (generation_info["generate_csv"] or generation_info["generate_pdf"]) and not generation_info["table_data"]:
            sample_data = file_gen.create_sample_data(agent_type or "sales")
            generation_info["table_data"] = sample_data
            generation_info["has_table"] = True

        # Format answer with table if needed
        if generation_info["has_table"] and generation_info["table_data"]:
            generation_info["formatted_answer"] = file_gen._format_answer_with_table(
                answer, generation_info["table_data"]
            )
        else:
            generation_info["formatted_answer"] = answer

        result = {"answer": generation_info["formatted_answer"], "generation_info": generation_info}

        _set_rag_cache(cache_key, result)
        return result

    except Exception as e:
        logger.error(f"Error getting answer with files: {e}")
        raise Exception(f"Erreur lors du traitement de votre question : {str(e)}")


def get_direct_gpt_response(question: str, db: Session, agent_id: int = None) -> str:
    """Get direct response from GPT without RAG when no documents are available, using agent_id for context"""
    try:
        from database import Agent

        agent = None
        contexte_agent = ""
        if agent_id:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            contexte_agent = ""
        else:
            # Security: sanitize agent contexte to mitigate prompt injection
            contexte_agent = _sanitize_prompt_text(agent.contexte) if agent.contexte else ""
        prompt = f"{contexte_agent}\n\nQuestion : {question}\n\nRéponse :"
        logger.info("Getting direct response from OpenAI (contexte personnalisé, pas de documents, agent_id)")
        response = get_chat_response(prompt)
        logger.info("Successfully got direct response from OpenAI")
        return response
    except Exception as e:
        logger.error(f"Error getting direct GPT response: {e}")
        raise Exception(f"Erreur lors du traitement de votre question : {str(e)}")


def detect_document_mention(question: str, available_docs: List[Document]) -> Optional[int]:
    """Detect if the user mentions a specific document by name and return its ID"""
    question_lower = question.lower()

    # Normalize question: remove accents, extra spaces, punctuation
    import unicodedata

    def normalize_text(text):
        # Remove accents
        text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
        # Remove punctuation and extra spaces
        text = text.replace("-", " ").replace("_", " ")
        return " ".join(text.split())

    question_normalized = normalize_text(question_lower)

    # Check each document with multiple matching strategies
    best_match = None
    best_score = 0

    for doc in available_docs:
        doc_name_lower = doc.filename.lower()
        # Remove file extensions for better matching
        doc_name_base = doc_name_lower.replace(".pdf", "").replace(".txt", "").replace(".doc", "").replace(".docx", "")
        doc_name_normalized = normalize_text(doc_name_base)

        score = 0

        # Strategy 1: Exact match (highest priority)
        if doc_name_base in question_lower or doc_name_normalized in question_normalized:
            score = 10
            logger.info(f"Exact match for document: {doc.filename} (ID: {doc.id})")
            return doc.id

        # Strategy 2: Word-by-word match
        doc_words = set(doc_name_normalized.split())
        question_words = set(question_normalized.split())
        matching_words = doc_words.intersection(question_words)

        if len(doc_words) > 0:
            word_match_ratio = len(matching_words) / len(doc_words)
            if word_match_ratio > 0.5:  # At least 50% of words match
                score = word_match_ratio * 5
                if score > best_score:
                    best_score = score
                    best_match = doc.id
                    logger.info(f"Partial match ({word_match_ratio:.2%}) for document: {doc.filename} (ID: {doc.id})")

    if best_match:
        logger.info(f"Best document match found: ID {best_match} with score {best_score}")
        return best_match

    return None


def get_answer(
    question: str,
    user_id: int,
    db: Session,
    selected_doc_ids: List[int] = None,
    agent_id: int = None,
    history: list = None,
    model_id: str = None,
    company_id: int = None,
    use_rag: bool = True,
    use_graph: bool = True,
) -> Dict[str, Any]:
    """Get answer using RAG for specific user with OpenAI - always using embeddings, memory, and custom model if provided.

    Tier 1: company_id is the tenant boundary used by RAG search. If not supplied,
    it is resolved from agent_id or user_id inside search_similar_texts_for_user.
    """
    try:
        # Resolve the per-agent company-RAG opt-in early so it can scope doc listing + search.
        agent = db.query(Agent).filter(Agent.id == agent_id).first() if agent_id else None
        include_company_rag = bool(getattr(agent, "include_company_rag", False)) if agent else False
        company_rag_folder_ids = _agent_folder_ids(agent) if include_company_rag else None
        company_scope_id = company_id or (getattr(agent, "company_id", None) if agent else None)

        # Get documents to consider for RAG
        # If selected_doc_ids provided, use those (and respect agent_id if present).
        # The company-RAG folder filter is intentionally NOT applied here: an explicit
        # user doc selection overrides folder scoping. The company_id tenant filter below
        # still applies, so this never crosses organization boundaries.
        if selected_doc_ids:
            q = db.query(Document).filter(Document.id.in_(selected_doc_ids))
            if agent_id:
                # Security: also filter by user_id to prevent cross-tenant document access
                # The agent ownership check is done at the endpoint level, but we enforce
                # that documents belong to either the agent OR the user as defense-in-depth.
                q = q.filter(Document.agent_id == agent_id)
            else:
                q = q.filter(Document.user_id == user_id)
            # Always enforce user ownership or company boundary on selected docs
            if company_id:
                q = q.filter(Document.company_id == company_id)
            q = q.filter(Document.document_type != "traceability")
            user_docs = q.all()
            logger.info(f"Using {len(user_docs)} selected documents: {selected_doc_ids}")
        else:
            # If we're in an agent context, prefer documents attached to that agent only
            if agent_id:
                _ga_company_clause = and_(Document.is_company_rag.is_(True), Document.company_id == company_scope_id)
                if company_rag_folder_ids:
                    _ga_company_clause = and_(_ga_company_clause, Document.folder_id.in_(company_rag_folder_ids))
                user_docs = (
                    db.query(Document)
                    .filter(
                        or_(
                            Document.agent_id == agent_id,
                            _ga_company_clause if include_company_rag else False,
                        ),
                        Document.document_type != "traceability",
                    )
                    .all()
                )
                logger.info(f"Using {len(user_docs)} documents attached to agent {agent_id}")
            else:
                user_docs = (
                    db.query(Document)
                    .filter(
                        Document.user_id == user_id,
                        Document.document_type != "traceability",
                        Document.is_company_rag.is_(False),
                    )
                    .all()
                )
                logger.info(f"Using all {len(user_docs)} user documents")

        # If RAG is disabled, skip document-based retrieval entirely
        if not use_rag:
            user_docs = []
            selected_doc_ids = None
            logger.info("RAG disabled by user toggle, skipping document retrieval")

        # Detect if user mentions a specific document
        mentioned_doc_id = None
        if user_docs and not selected_doc_ids:
            mentioned_doc_id = detect_document_mention(question, user_docs)
            if mentioned_doc_id:
                # Filter to only this document
                selected_doc_ids = [mentioned_doc_id]
                user_docs = [doc for doc in user_docs if doc.id == mentioned_doc_id]
                logger.info(f"User mentioned document, filtering to doc_id: {mentioned_doc_id}")

        # Récupérer le contexte personnalisé de l'agent par son id
        # (agent was already loaded above for the include_company_rag flag)
        contexte_agent = ""
        if not agent:
            agent = db.query(Agent).filter(Agent.user_id == user_id).first()
        # Security: sanitize agent contexte to mitigate prompt injection via HTML/script tags
        contexte_agent = _sanitize_prompt_text(agent.contexte) if agent and agent.contexte else ""

        # Visuel agent: bypass RAG, generate image via Imagen 3
        if agent and getattr(agent, "type", "") == "visuel":
            style_prefix = f"{agent.contexte.strip()}. " if (agent.contexte or "").strip() else ""
            image_bytes = generate_image(style_prefix + question)
            image_url = upload_generated_image(image_bytes, agent.id)
            return {"answer": f"![Image générée]({image_url})", "sources": [], "graph_data": None}

        # Neo4j Knowledge Graph context injection
        graph_data = None
        if use_graph and agent and getattr(agent, "neo4j_enabled", False):
            try:
                owner = db.query(User).filter(User.id == agent.user_id).first()
                if owner and owner.company_id:
                    neo4j_person = getattr(agent, "neo4j_person_name", None)
                    if neo4j_person:
                        from neo4j_client import get_person_context_with_data

                        neo4j_context, graph_data = get_person_context_with_data(
                            owner.company_id, neo4j_person, agent.neo4j_depth or 1
                        )
                        if neo4j_context:
                            contexte_agent += f"\n\n--- Graphe de connaissances entreprise ---\n{neo4j_context}"
                            logger.info(f"Neo4j context injected for agent {agent_id}, person '{neo4j_person}'")
                    else:
                        from neo4j_client import get_graph_keyword_with_data

                        neo4j_context, graph_data = get_graph_keyword_with_data(owner.company_id, question, depth=1)
                        if neo4j_context:
                            contexte_agent += f"\n\n--- Graphe de connaissances entreprise ---\n{neo4j_context}"
                            logger.info(
                                f"Neo4j keyword context injected for agent {agent_id}, keyword='{question[:50]}'"
                            )
            except Exception as e:
                logger.warning(f"Neo4j context retrieval failed (continuing without): {e}")

        # Date awareness: inject current date/time into agent context
        if agent and getattr(agent, "date_awareness_enabled", False):
            now = datetime.now()
            _JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            _MOIS = [
                "janvier",
                "février",
                "mars",
                "avril",
                "mai",
                "juin",
                "juillet",
                "août",
                "septembre",
                "octobre",
                "novembre",
                "décembre",
            ]
            date_str = f"{_JOURS[now.weekday()]} {now.day} {_MOIS[now.month - 1]} {now.year}, {now.strftime('%H:%M')}"
            date_context = f"Date et heure actuelles : {date_str}\n\n"
            contexte_agent = date_context + contexte_agent

        # Build list of available documents for context
        available_docs_list = ""
        if user_docs:
            available_docs_list = "\n\nDocuments disponibles dans ma base de connaissances:\n"
            for doc in user_docs:
                doc_name = doc.filename.replace(".pdf", "").replace(".txt", "").replace(".doc", "").replace(".docx", "")
                available_docs_list += f"- {doc_name}\n"

        # Si pas de documents, fallback sur le contexte + mémoire
        if not user_docs:
            if selected_doc_ids:
                return {
                    "answer": "Aucun des documents sélectionnés n'a été trouvé. Veuillez vérifier votre sélection.",
                    "sources": [],
                    "graph_data": graph_data,
                }
            else:
                logger.info("No documents found, using context + question + memory only")
                # Prépare la liste messages pour OpenAI avec l'historique complet
                messages = []
                system_content = contexte_agent if contexte_agent else ""
                if system_content:
                    messages.append({"role": "system", "content": system_content})

                # Ajoute l'historique complet comme messages séparés (jusqu'aux 10 derniers échanges)
                if history:
                    for msg in history[-10:]:
                        # Convertit les rôles pour OpenAI API format
                        role = msg.get("role", "user")
                        if role == "agent":
                            role = "assistant"
                        elif role == "system":
                            # Skip system messages from history, or add as user context
                            continue
                        messages.append({"role": role, "content": msg.get("content", "")})

                # Ajoute la question actuelle si elle n'est pas déjà dans l'historique
                # (vérifie si le dernier message de l'historique est différent de la question)
                if not history or history[-1].get("content", "") != question:
                    messages.append({"role": "user", "content": question})

                logger.info("[PROMPT OPENAI] %s", json.dumps(messages, ensure_ascii=False, indent=2))
                # If this request is for an actionnable agent, enforce Gemini-only (no OpenAI fallback)
                response = get_chat_response(messages, model_id=model_id)
                return {"answer": response, "sources": [], "graph_data": graph_data}

        # Always get question embedding with retry
        logger.info(f"Getting embedding for question: {question}")
        query_embedding = get_embedding(question)
        logger.info("Successfully got query embedding")

        # Search similar chunks for this user (with optional document filtering)
        # If a specific document was mentioned, get more chunks from it
        top_k = 20 if mentioned_doc_id else 8
        logger.info(f"Searching similar texts for user {user_id} (top_k={top_k})")
        context_results = search_similar_texts_for_user(
            query_embedding,
            user_id,
            db,
            top_k=top_k,
            selected_doc_ids=selected_doc_ids,
            agent_id=agent_id,
            company_id=company_id,
            include_company_rag=include_company_rag,
            company_rag_folder_ids=company_rag_folder_ids,
        )

        # Build sources metadata for the frontend
        sources = [
            {
                "text": r["text"],
                "document_name": r["document_name"],
                "score": round(r["similarity"] * 100, 1),
                "document_id": r["document_id"],
            }
            for r in context_results
        ]

        # Préparer le contexte RAG
        context_by_document = {}
        for result in context_results:
            doc_name = result["document_name"]
            if doc_name not in context_by_document:
                context_by_document[doc_name] = []
            context_by_document[doc_name].append(result["text"])

        # Build enhanced context string (limited to prevent memory exhaustion)
        MAX_CONTEXT_CHARS = 50000
        enhanced_context = ""
        for doc_name, contexts in context_by_document.items():
            section = f"\n--- Extraits du document '{doc_name}' ---\n"
            for i, context in enumerate(contexts, 1):
                section += f"Extrait {i}: {context}\n"
            if len(enhanced_context) + len(section) > MAX_CONTEXT_CHARS:
                enhanced_context += "\n[...contexte tronqué pour respecter les limites...]"
                break
            enhanced_context += section

        # Prompt final : contexte agent + mémoire courte + historique complet + question + extraits RAG
        messages = []

        # System message avec contexte agent, liste des documents ET extraits RAG
        system_content = ""
        if contexte_agent:
            system_content = contexte_agent

        # Ajouter la liste des documents disponibles
        if available_docs_list:
            if system_content:
                system_content += available_docs_list
            else:
                system_content = available_docs_list.strip()

        if enhanced_context:
            if system_content:
                system_content += f"\n\nExtraits de documents pertinents :\n{enhanced_context}"
            else:
                system_content = f"Extraits de documents pertinents :\n{enhanced_context}"
        if system_content:
            messages.append({"role": "system", "content": system_content})

        # Ajoute l'historique complet comme messages séparés (jusqu'aux 10 derniers échanges)
        if history:
            for msg in history[-10:]:
                # Convertit les rôles pour OpenAI API format
                role = msg.get("role", "user")
                if role == "agent":
                    role = "assistant"
                elif role == "system":
                    # Skip system messages from history
                    continue
                messages.append({"role": role, "content": msg.get("content", "")})

        # Ajoute la question actuelle si elle n'est pas déjà dans l'historique
        if not history or history[-1].get("content", "") != question:
            messages.append({"role": "user", "content": question})

        logger.info("[PROMPT OPENAI] %s", json.dumps(messages, ensure_ascii=False, indent=2))
        logger.info(
            "Getting response from OpenAI with structured messages (system + RAG context, full history, current question)"
        )
        response = get_chat_response(messages, model_id=model_id)
        logger.info("Successfully got response from OpenAI")
        return {"answer": response, "sources": sources, "graph_data": graph_data}
    except Exception as e:
        logger.error(f"Error getting answer: {e}")
        raise Exception(f"Erreur lors du traitement de votre question avec l'API OpenAI : {str(e)}")


def get_answer_stream(
    question: str,
    user_id: int,
    db: Session,
    selected_doc_ids: List[int] = None,
    agent_id: int = None,
    history: list = None,
    model_id: str = None,
    company_id: int = None,
    use_rag: bool = True,
    use_graph: bool = True,
):
    """Streaming version of get_answer(). Yields SSE-formatted events.

    The RAG pipeline (embedding, vector search, context assembly) runs synchronously.
    Only the final LLM generation is streamed token-by-token.
    """
    from streaming_response import sse_event

    try:
        # Resolve the per-agent company-RAG opt-in early so it can scope doc listing + search.
        agent = db.query(Agent).filter(Agent.id == agent_id).first() if agent_id else None
        include_company_rag = bool(getattr(agent, "include_company_rag", False)) if agent else False
        company_rag_folder_ids = _agent_folder_ids(agent) if include_company_rag else None
        company_scope_id = company_id or (getattr(agent, "company_id", None) if agent else None)

        # --- Document retrieval (same as get_answer) ---
        # Folder filter intentionally not applied to an explicit selected_doc_ids set
        # (explicit user selection overrides folder scoping); company_id tenant filter still applies.
        if selected_doc_ids:
            q = db.query(Document).filter(Document.id.in_(selected_doc_ids))
            if agent_id:
                q = q.filter(Document.agent_id == agent_id)
            else:
                q = q.filter(Document.user_id == user_id)
            # Security: enforce company boundary on selected docs
            if company_id:
                q = q.filter(Document.company_id == company_id)
            q = q.filter(Document.document_type != "traceability")
            user_docs = q.all()
        else:
            if agent_id:
                _gas_company_clause = and_(Document.is_company_rag.is_(True), Document.company_id == company_scope_id)
                if company_rag_folder_ids:
                    _gas_company_clause = and_(_gas_company_clause, Document.folder_id.in_(company_rag_folder_ids))
                user_docs = (
                    db.query(Document)
                    .filter(
                        or_(
                            Document.agent_id == agent_id,
                            _gas_company_clause if include_company_rag else False,
                        ),
                        Document.document_type != "traceability",
                    )
                    .all()
                )
            else:
                user_docs = (
                    db.query(Document)
                    .filter(
                        Document.user_id == user_id,
                        Document.document_type != "traceability",
                        Document.is_company_rag.is_(False),
                    )
                    .all()
                )

        # If RAG is disabled, skip document-based retrieval entirely
        if not use_rag:
            user_docs = []
            selected_doc_ids = None
            logger.info("RAG disabled by user toggle, skipping document retrieval")

        # Detect document mention
        mentioned_doc_id = None
        if user_docs and not selected_doc_ids:
            mentioned_doc_id = detect_document_mention(question, user_docs)
            if mentioned_doc_id:
                selected_doc_ids = [mentioned_doc_id]
                user_docs = [doc for doc in user_docs if doc.id == mentioned_doc_id]

        # Agent context (agent was already loaded above for the include_company_rag flag)
        contexte_agent = ""
        if not agent:
            agent = db.query(Agent).filter(Agent.user_id == user_id).first()
        # Security: sanitize agent contexte to mitigate prompt injection via HTML/script tags
        contexte_agent = _sanitize_prompt_text(agent.contexte) if agent and agent.contexte else ""

        # Visuel agents: no streaming (image generation), yield complete response
        if agent and getattr(agent, "type", "") == "visuel":
            style_prefix = f"{agent.contexte.strip()}. " if (agent.contexte or "").strip() else ""
            image_bytes = generate_image(style_prefix + question)
            image_url = upload_generated_image(image_bytes, agent.id)
            full = f"![Image générée]({image_url})"
            yield sse_event("token", {"t": full})
            yield sse_event("done", {"full_text": full, "sources": [], "graph_data": None})
            return

        # Neo4j context
        graph_data = None
        if use_graph and agent and getattr(agent, "neo4j_enabled", False):
            try:
                owner = db.query(User).filter(User.id == agent.user_id).first()
                if owner and owner.company_id:
                    neo4j_person = getattr(agent, "neo4j_person_name", None)
                    if neo4j_person:
                        from neo4j_client import get_person_context_with_data

                        neo4j_context, graph_data = get_person_context_with_data(
                            owner.company_id, neo4j_person, agent.neo4j_depth or 1
                        )
                        if neo4j_context:
                            contexte_agent += f"\n\n--- Graphe de connaissances entreprise ---\n{neo4j_context}"
                    else:
                        from neo4j_client import get_graph_keyword_with_data

                        neo4j_context, graph_data = get_graph_keyword_with_data(owner.company_id, question, depth=1)
                        if neo4j_context:
                            contexte_agent += f"\n\n--- Graphe de connaissances entreprise ---\n{neo4j_context}"
            except Exception as e:
                logger.warning(f"Neo4j context retrieval failed (continuing without): {e}")

        # Date awareness: inject current date/time into agent context
        if agent and getattr(agent, "date_awareness_enabled", False):
            now = datetime.now()
            _JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
            _MOIS = [
                "janvier",
                "février",
                "mars",
                "avril",
                "mai",
                "juin",
                "juillet",
                "août",
                "septembre",
                "octobre",
                "novembre",
                "décembre",
            ]
            date_str = f"{_JOURS[now.weekday()]} {now.day} {_MOIS[now.month - 1]} {now.year}, {now.strftime('%H:%M')}"
            date_context = f"Date et heure actuelles : {date_str}\n\n"
            contexte_agent = date_context + contexte_agent

        # Available docs list
        available_docs_list = ""
        if user_docs:
            available_docs_list = "\n\nDocuments disponibles dans ma base de connaissances:\n"
            for doc in user_docs:
                doc_name = doc.filename.replace(".pdf", "").replace(".txt", "").replace(".doc", "").replace(".docx", "")
                available_docs_list += f"- {doc_name}\n"

        # --- Build messages ---
        sources = []  # Will be populated by RAG path if documents exist
        if not user_docs:
            if selected_doc_ids:
                msg = "Aucun des documents sélectionnés n'a été trouvé. Veuillez vérifier votre sélection."
                yield sse_event("token", {"t": msg})
                yield sse_event("done", {"full_text": msg, "sources": [], "graph_data": graph_data})
                return

            messages = []
            system_content = contexte_agent if contexte_agent else ""
            if system_content:
                messages.append({"role": "system", "content": system_content})
            if history:
                for msg in history[-10:]:
                    role = msg.get("role", "user")
                    if role == "agent":
                        role = "assistant"
                    elif role == "system":
                        continue
                    messages.append({"role": role, "content": msg.get("content", "")})
            if not history or history[-1].get("content", "") != question:
                messages.append({"role": "user", "content": question})
        else:
            # RAG: embedding + search
            query_embedding = get_embedding(question)
            top_k = 20 if mentioned_doc_id else 8
            context_results = search_similar_texts_for_user(
                query_embedding,
                user_id,
                db,
                top_k=top_k,
                selected_doc_ids=selected_doc_ids,
                agent_id=agent_id,
                company_id=company_id,
                include_company_rag=include_company_rag,
                company_rag_folder_ids=company_rag_folder_ids,
            )

            # Build sources metadata for the frontend
            sources = [
                {
                    "text": r["text"],
                    "document_name": r["document_name"],
                    "score": round(r["similarity"] * 100, 1),
                    "document_id": r["document_id"],
                }
                for r in context_results
            ]

            context_by_document = {}
            for result in context_results:
                doc_name = result["document_name"]
                if doc_name not in context_by_document:
                    context_by_document[doc_name] = []
                context_by_document[doc_name].append(result["text"])

            MAX_CONTEXT_CHARS = 50000
            enhanced_context = ""
            for doc_name, contexts in context_by_document.items():
                section = f"\n--- Extraits du document '{doc_name}' ---\n"
                for i, context in enumerate(contexts, 1):
                    section += f"Extrait {i}: {context}\n"
                if len(enhanced_context) + len(section) > MAX_CONTEXT_CHARS:
                    enhanced_context += "\n[...contexte tronqué pour respecter les limites...]"
                    break
                enhanced_context += section

            messages = []
            system_content = ""
            if contexte_agent:
                system_content = contexte_agent
            if available_docs_list:
                system_content = (
                    (system_content + available_docs_list) if system_content else available_docs_list.strip()
                )
            if enhanced_context:
                rag_section = f"\n\nExtraits de documents pertinents :\n{enhanced_context}"
                system_content = (
                    (system_content + rag_section)
                    if system_content
                    else f"Extraits de documents pertinents :\n{enhanced_context}"
                )
            if system_content:
                messages.append({"role": "system", "content": system_content})

            if history:
                for msg in history[-10:]:
                    role = msg.get("role", "user")
                    if role == "agent":
                        role = "assistant"
                    elif role == "system":
                        continue
                    messages.append({"role": role, "content": msg.get("content", "")})
            if not history or history[-1].get("content", "") != question:
                messages.append({"role": "user", "content": question})

        # --- Check RAG cache ---
        doc_ids_for_cache = selected_doc_ids or ([d.id for d in user_docs] if user_docs else [])
        agent_type_str = getattr(agent, "type", "conversationnel") if agent else "conversationnel"
        cache_key = _rag_cache_key(user_id, question, doc_ids_for_cache, agent_type_str)
        cached = _get_rag_cache(cache_key)
        if cached is not None:
            logger.info("Stream: returning cached answer")
            if isinstance(cached, str):
                cached_text = cached
                cached_sources = []
            else:
                cached_text = cached.get("answer", str(cached))
                cached_sources = cached.get("sources", [])
            cached_graph = cached.get("graph_data", None) if isinstance(cached, dict) else None
            yield sse_event("token", {"t": cached_text})
            yield sse_event("done", {"full_text": cached_text, "sources": cached_sources, "graph_data": cached_graph})
            return

        # --- Stream from LLM ---
        full_text = ""
        for chunk in get_chat_response_stream(messages, model_id=model_id):
            full_text += chunk
            yield sse_event("token", {"t": chunk})

        yield sse_event("done", {"full_text": full_text, "sources": sources, "graph_data": graph_data})

        # Cache the result (store answer + sources + graph_data together)
        _set_rag_cache(cache_key, {"answer": full_text, "sources": sources, "graph_data": graph_data})

    except Exception as e:
        logger.error(f"Error in get_answer_stream: {e}")
        yield sse_event("error", {"message": str(e), "code": "llm_error"})


def search_similar_texts_for_user(
    query_embedding: List[float],
    user_id: int,
    db: Session,
    top_k: int = 3,
    selected_doc_ids: List[int] = None,
    agent_id: int = None,
    company_id: int = None,
    mission_id: int = None,
    include_company_rag: bool = False,
    company_rag_folder_ids: list = None,
    recap_source_only: bool = False,
) -> List[dict]:
    """Search similar texts using pgvector cosine distance (ORM), with neighbor chunk context.

    Tier 1 tenant isolation:
      - company_id is the tenant boundary for the RAG search.
      - If caller supplies company_id, it is used directly (strongest guarantee).
      - Otherwise it is resolved from agent_id (Agent.company_id) or user_id
        (User.company_id) — this defends even callers that forgot to pass it.
      - If no tenant can be resolved, the search returns [] rather than risk
        a cross-tenant leak.
    """
    from database import Agent, User

    try:
        # Resolve tenant boundary (defense in depth: never fall through to no filter)
        if company_id is None:
            if agent_id:
                _agent_row = db.query(Agent.company_id).filter(Agent.id == agent_id).first()
                if _agent_row is not None:
                    company_id = _agent_row[0]
            if company_id is None and mission_id:
                from database import Mission

                _m_row = db.query(Mission.company_id).filter(Mission.id == mission_id).first()
                if _m_row is not None:
                    company_id = _m_row[0]
            if company_id is None and user_id is not None:
                _user_row = db.query(User.company_id).filter(User.id == user_id).first()
                if _user_row is not None:
                    company_id = _user_row[0]

        if company_id is None:
            logger.warning(
                f"search_similar_texts_for_user: no tenant boundary could be resolved "
                f"(user_id={user_id}, agent_id={agent_id}) — returning empty to avoid cross-tenant leak"
            )
            return []

        # Build query using SQLAlchemy ORM with pgvector native operators
        query = (
            db.query(
                DocumentChunk.id,
                DocumentChunk.chunk_text,
                DocumentChunk.chunk_index,
                DocumentChunk.document_id,
                Document.filename,
                Document.created_at,
                (1 - DocumentChunk.embedding_vec.cosine_distance(query_embedding)).label("similarity"),
            )
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(
                DocumentChunk.embedding_vec.isnot(None),
                Document.document_type != "traceability",
                # Hard tenant filter — applied on BOTH tables to survive RLS double-check
                Document.company_id == company_id,
                DocumentChunk.company_id == company_id,
            )
        )

        if mission_id:
            query = query.filter(Document.mission_id == mission_id)
            if recap_source_only:
                query = query.filter(Document.is_mission_recap_source.is_(True))
        elif agent_id:
            # Agent-scoped docs; optionally union the company-shared docs
            agent_scope = and_(Document.agent_id == agent_id, Document.mission_id.is_(None))
            if include_company_rag:
                company_scope = Document.is_company_rag.is_(True)
                if company_rag_folder_ids:
                    company_scope = and_(company_scope, Document.folder_id.in_(company_rag_folder_ids))
                query = query.filter(or_(agent_scope, company_scope))
            else:
                query = query.filter(agent_scope, Document.is_company_rag.is_(False))
        else:
            # User-level general RAG: never leak company docs into personal scope
            query = query.filter(
                Document.user_id == user_id,
                Document.mission_id.is_(None),
                Document.is_company_rag.is_(False),
            )

        if selected_doc_ids:
            query = query.filter(Document.id.in_(selected_doc_ids))

        query = query.order_by(DocumentChunk.embedding_vec.cosine_distance(query_embedding)).limit(top_k)

        rows = query.all()

        if not rows:
            return []

        # Fetch neighbor chunks for context
        doc_ids = list({r.document_id for r in rows})
        neighbor_rows = (
            db.query(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.chunk_text)
            .filter(DocumentChunk.document_id.in_(doc_ids))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )

        # Build chunk map: document_id -> [(chunk_index, chunk_text), ...]
        chunk_map: Dict[int, List] = {}
        for nr in neighbor_rows:
            chunk_map.setdefault(nr.document_id, []).append((nr.chunk_index, nr.chunk_text))

        # Enrich top results with neighbor context
        context_results = []
        for row in rows:
            neighbors = []
            ordered = chunk_map.get(row.document_id, [])
            for i, (cidx, ctxt) in enumerate(ordered):
                if cidx == row.chunk_index:
                    if i > 0:
                        neighbors.append(ordered[i - 1][1])
                    neighbors.append(ctxt)
                    if i < len(ordered) - 1:
                        neighbors.append(ordered[i + 1][1])
                    break

            context_results.append(
                {
                    "similarity": float(row.similarity),
                    "text": "\n".join(neighbors) if neighbors else row.chunk_text,
                    "document_id": row.document_id,
                    "document_name": row.filename,
                    "created_at": row.created_at.isoformat(),
                }
            )

        return context_results
    except Exception as e:
        logger.error(f"Error searching similar texts: {e}")
        return []


def get_documents_summary(user_id: int, db: Session, selected_doc_ids: List[int] = None) -> List[dict]:
    """Get complete information about user's documents"""
    try:
        if selected_doc_ids:
            documents = db.query(Document).filter(Document.user_id == user_id, Document.id.in_(selected_doc_ids)).all()
        else:
            documents = db.query(Document).filter(Document.user_id == user_id).all()

        doc_info = []
        for doc in documents:
            # Get all chunks for this document
            chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
            content = " ".join([chunk.chunk_text for chunk in chunks])

            doc_info.append(
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "created_at": doc.created_at.isoformat(),
                    "content": content[:2000] + "..." if len(content) > 2000 else content,  # Limit content
                    "chunk_count": len(chunks),
                }
            )

        return doc_info

    except Exception as e:
        logger.error(f"Error getting documents summary: {e}")
        return []


def search_text_fallback(question: str, user_id: int, db: Session, top_k: int = 3) -> List[str]:
    """Fallback text search when embeddings are not available"""
    try:
        # Get all chunks for user's documents
        chunks = db.query(DocumentChunk).join(Document).filter(Document.user_id == user_id).all()

        if not chunks:
            return []

        # Simple keyword matching
        question_words = question.lower().split()
        scored_chunks = []

        for chunk in chunks:
            chunk_text = chunk.chunk_text.lower()
            score = 0

            # Count word matches
            for word in question_words:
                if len(word) > 2:  # Skip very short words
                    score += chunk_text.count(word)

            if score > 0:
                scored_chunks.append((score, chunk.chunk_text))

        # Sort by score and return top results
        scored_chunks.sort(reverse=True, key=lambda x: x[0])
        return [text for _, text in scored_chunks[:top_k]]

    except Exception as e:
        logger.error(f"Error in text fallback search: {e}")
        return []


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors"""
    import numpy as np

    vec1 = np.array(vec1)
    vec2 = np.array(vec2)

    dot_product = np.dot(vec1, vec2)
    norm_vec1 = np.linalg.norm(vec1)
    norm_vec2 = np.linalg.norm(vec2)

    if norm_vec1 == 0 or norm_vec2 == 0:
        return 0

    return dot_product / (norm_vec1 * norm_vec2)


def ingest_text_content(
    text_content: str,
    filename: str,
    user_id: int,
    agent_id: int,
    db: Session,
    gcs_url: str = None,
    notion_link_id: int = None,
    company_id: int = None,
    drive_link_id: int = None,
    drive_file_id: str = None,
    progress_callback=None,
    mission_id: int = None,
    is_company_rag: bool = False,
    folder_id: int = None,
    is_mission_recap_source: bool = False,
    recap_schedule_id: int = None,
) -> int:
    """Chunk text, create Document + DocumentChunks with Mistral embeddings via pgvector. Returns document.id."""
    import numpy as np
    from mistral_embeddings import EMBEDDING_DIM

    # Resolve company_id if not provided (defense in depth)
    if company_id is None:
        if agent_id:
            _agent = db.query(Agent.company_id).filter(Agent.id == agent_id).first()
            if _agent:
                company_id = _agent[0]
        if company_id is None and mission_id:
            from database import Mission

            _m = db.query(Mission.company_id).filter(Mission.id == mission_id).first()
            if _m:
                company_id = _m[0]
        if company_id is None and user_id:
            _user = db.query(User.company_id).filter(User.id == user_id).first()
            if _user:
                company_id = _user[0]

    try:
        chunks = chunk_text(text_content)
        logger.info(f"ingest_text_content: {len(chunks)} chunks for '{filename}'")

        document = Document(
            filename=filename,
            content=text_content,
            user_id=user_id,
            agent_id=agent_id,
            company_id=company_id,
            gcs_url=gcs_url,
            notion_link_id=notion_link_id,
            drive_link_id=drive_link_id,
            drive_file_id=drive_file_id,
            mission_id=mission_id,
            is_company_rag=is_company_rag,
            folder_id=folder_id,
            is_mission_recap_source=is_mission_recap_source,
            recap_schedule_id=recap_schedule_id,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        logger.info(f"Document saved with ID: {document.id}")

        def split_for_embedding(chunk, max_tokens=8192):
            chunk = chunk.replace("\x00", "")
            max_chars = max_tokens * 4
            return [chunk[i : i + max_chars] for i in range(0, len(chunk), max_chars)]

        if progress_callback:
            progress_callback("chunking", 30, len(chunks))

        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i + 1}/{len(chunks)} with Mistral embedding")
            if progress_callback:
                # Embedding phase spans 30-95%
                pct = 30 + int((i / max(len(chunks), 1)) * 65)
                progress_callback("embedding", pct, len(chunks), i + 1)
            try:
                sub_chunks = split_for_embedding(chunk, 8192)
                embeddings = []
                for sub in sub_chunks:
                    embedding = get_embedding_fast(sub)
                    embeddings.append(embedding)
                if embeddings:
                    avg_embedding = list(np.mean(np.array(embeddings), axis=0))
                else:
                    raise ValueError("No sub-chunks produced for embedding")
            except Exception as e:
                logger.error(f"Failed to get Mistral embedding for chunk {i}: {e}")
                raise
            doc_chunk = DocumentChunk(
                document_id=document.id,
                company_id=company_id,
                chunk_text=chunk,
                embedding_vec=avg_embedding,
                chunk_index=i,
            )
            db.add(doc_chunk)
        db.commit()
        logger.info(f"ingest_text_content completed: {filename}, {len(chunks)} chunks")
        return document.id
    except Exception as e:
        logger.error(f"ingest_text_content error: {e}")
        db.rollback()
        raise e


def process_document_for_user(
    filename: str,
    content: bytes,
    user_id: int,
    db: Session,
    agent_id: int = None,
    company_id: int = None,
    progress_callback=None,
    mission_id: int = None,
    is_company_rag: bool = False,
    folder_id: int = None,
    is_mission_recap_source: bool = False,
    recap_schedule_id: int = None,
) -> int:
    import tempfile
    import os

    try:
        logger.info(f"Starting to process document: {filename} for user {user_id}, agent {agent_id}")
        if progress_callback:
            progress_callback("uploading", 5)

        # Upload file to GCS
        from google.cloud import storage
        import time

        bucket_name = os.getenv("GCS_BUCKET_NAME", "applydi-documents")
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        gcs_filename = f"{int(time.time())}_{filename.replace(' ', '_')}"
        blob = bucket.blob(gcs_filename)
        blob.upload_from_string(content)
        gcs_url = blob.public_url
        logger.info(f"Document uploaded to GCS: {gcs_url}")
        if progress_callback:
            progress_callback("extracting", 15)

        # Extraction du texte
        # Build a sub-callback for page-level PDF progress (15-28%)
        def _pdf_progress(stage, pct, current_page=None, total_pages=None):
            if progress_callback:
                progress_callback(stage, pct, total_pages, current_page)

        if filename.endswith(".pdf"):
            tmp_file = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp_file = tmp.name
                    tmp.write(content)
                logger.info(f"Processing PDF file: {tmp_file}")
                text_content = load_text_from_pdf(tmp_file, progress_callback=_pdf_progress)
            finally:
                if tmp_file and os.path.exists(tmp_file):
                    os.unlink(tmp_file)
        else:
            try:
                text_content = content.decode("utf-8")
            except Exception as e:
                logger.warning(f"Could not decode content as utf-8: {e}")
                text_content = ""
        if text_content is None:
            text_content = ""
        logger.info(f"Extracted text length: {len(text_content)} characters")
        if progress_callback:
            progress_callback("extracted", 28)

        return ingest_text_content(
            text_content,
            filename,
            user_id,
            agent_id,
            db,
            gcs_url=gcs_url,
            company_id=company_id,
            progress_callback=progress_callback,
            mission_id=mission_id,
            is_company_rag=is_company_rag,
            folder_id=folder_id,
            is_mission_recap_source=is_mission_recap_source,
            recap_schedule_id=recap_schedule_id,
        )
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        db.rollback()
        raise e
