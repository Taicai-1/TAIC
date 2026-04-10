
# Contient la logique RAG améliorée
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from mistral_embeddings import get_embedding, get_embedding_fast
from openai_client import get_chat_response
from database import Document, DocumentChunk, User, Agent
from file_loader import load_text_from_pdf, chunk_text
from file_generator import FileGenerator
from imagen_client import generate_image
from imagen_gcs import upload_generated_image

logger = logging.getLogger(__name__)

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
    conv = db.query(Conversation).filter(Conversation.agent_id == agent_id).order_by(Conversation.created_at.desc()).first()
    if not conv:
        return ""
    # Récupère le dernier message de la conversation
    msg = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.timestamp.desc()).first()
    if not msg:
        return ""
    return msg.content

def get_answer_with_files(question: str, user_id: int, db: Session, selected_doc_ids: List[int] = None, agent_type: str = None) -> Dict[str, Any]:
    """Get answer using RAG with file generation capabilities"""
    try:
        cache_key = _rag_cache_key(user_id, question, selected_doc_ids, agent_type)

        cached = _get_rag_cache(cache_key)
        if cached is not None:
            logger.info("Returning cached answer")
            return cached

        # Get the regular answer first
        answer = get_answer(question, user_id, db, selected_doc_ids, agent_type)

        # Initialize file generator
        file_gen = FileGenerator()

        # Detect if user wants file generation
        generation_info = file_gen.detect_generation_request(question, answer)

        # If no table detected but user asked for structured data, create sample data
        if (generation_info['generate_csv'] or generation_info['generate_pdf']) and not generation_info['table_data']:
            sample_data = file_gen.create_sample_data(agent_type or 'sales')
            generation_info['table_data'] = sample_data
            generation_info['has_table'] = True

        # Format answer with table if needed
        if generation_info['has_table'] and generation_info['table_data']:
            generation_info['formatted_answer'] = file_gen._format_answer_with_table(answer, generation_info['table_data'])
        else:
            generation_info['formatted_answer'] = answer

        result = {
            'answer': generation_info['formatted_answer'],
            'generation_info': generation_info
        }

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
            contexte_agent = agent.contexte or ""
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
        text = ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')
        # Remove punctuation and extra spaces
        text = text.replace('-', ' ').replace('_', ' ')
        return ' '.join(text.split())

    question_normalized = normalize_text(question_lower)

    # Check each document with multiple matching strategies
    best_match = None
    best_score = 0

    for doc in available_docs:
        doc_name_lower = doc.filename.lower()
        # Remove file extensions for better matching
        doc_name_base = doc_name_lower.replace('.pdf', '').replace('.txt', '').replace('.doc', '').replace('.docx', '')
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
) -> str:
    """Get answer using RAG for specific user with OpenAI - always using embeddings, memory, and custom model if provided.

    Tier 1: company_id is the tenant boundary used by RAG search. If not supplied,
    it is resolved from agent_id or user_id inside search_similar_texts_for_user.
    """
    try:
        # Get documents to consider for RAG
        # If selected_doc_ids provided, use those (and respect agent_id if present)
        if selected_doc_ids:
            q = db.query(Document).filter(Document.id.in_(selected_doc_ids))
            if agent_id:
                q = q.filter(Document.agent_id == agent_id)
            else:
                q = q.filter(Document.user_id == user_id)
            q = q.filter(Document.document_type != "traceability")
            user_docs = q.all()
            logger.info(f"Using {len(user_docs)} selected documents: {selected_doc_ids}")
        else:
            # If we're in an agent context, prefer documents attached to that agent only
            if agent_id:
                user_docs = db.query(Document).filter(Document.agent_id == agent_id, Document.document_type != "traceability").all()
                logger.info(f"Using {len(user_docs)} documents attached to agent {agent_id}")
            else:
                user_docs = db.query(Document).filter(Document.user_id == user_id, Document.document_type != "traceability").all()
                logger.info(f"Using all {len(user_docs)} user documents")

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
        agent = None
        contexte_agent = ""
        if agent_id:
            agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            agent = db.query(Agent).filter(Agent.user_id == user_id).first()
        contexte_agent = agent.contexte if agent and agent.contexte else ""

        # Visuel agent: bypass RAG, generate image via Imagen 3
        if agent and getattr(agent, 'type', '') == 'visuel':
            style_prefix = f"{agent.contexte.strip()}. " if (agent.contexte or "").strip() else ""
            image_bytes = generate_image(style_prefix + question)
            image_url = upload_generated_image(image_bytes, agent.id)
            return f"![Image générée]({image_url})"

        # Neo4j Knowledge Graph context injection
        if agent and getattr(agent, 'neo4j_enabled', False) and getattr(agent, 'neo4j_person_name', None):
            try:
                from neo4j_client import get_person_context_cached
                owner = db.query(User).filter(User.id == agent.user_id).first()
                if owner and owner.company_id:
                    neo4j_context = get_person_context_cached(
                        owner.company_id,
                        agent.neo4j_person_name,
                        agent.neo4j_depth or 1
                    )
                    if neo4j_context:
                        contexte_agent += f"\n\n--- Graphe de connaissances entreprise ---\n{neo4j_context}"
                        logger.info(f"Neo4j context injected for agent {agent_id}, person '{agent.neo4j_person_name}'")
            except Exception as e:
                logger.warning(f"Neo4j context retrieval failed (continuing without): {e}")

        # Build list of available documents for context
        available_docs_list = ""
        if user_docs:
            available_docs_list = "\n\nDocuments disponibles dans ma base de connaissances:\n"
            for doc in user_docs:
                doc_name = doc.filename.replace('.pdf', '').replace('.txt', '').replace('.doc', '').replace('.docx', '')
                available_docs_list += f"- {doc_name}\n"

        # Si pas de documents, fallback sur le contexte + mémoire
        if not user_docs:
            if selected_doc_ids:
                return "Aucun des documents sélectionnés n'a été trouvé. Veuillez vérifier votre sélection."
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
                        role = msg.get('role', 'user')
                        if role == 'agent':
                            role = 'assistant'
                        elif role == 'system':
                            # Skip system messages from history, or add as user context
                            continue
                        messages.append({"role": role, "content": msg.get('content', '')})

                # Ajoute la question actuelle si elle n'est pas déjà dans l'historique
                # (vérifie si le dernier message de l'historique est différent de la question)
                if not history or history[-1].get('content', '') != question:
                    messages.append({"role": "user", "content": question})

                logger.info("[PROMPT OPENAI] %s", json.dumps(messages, ensure_ascii=False, indent=2))
                # If this request is for an actionnable agent, enforce Gemini-only (no OpenAI fallback)
                response = get_chat_response(messages, model_id=model_id)
                return response

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
        )

        # Préparer le contexte RAG
        context_by_document = {}
        for result in context_results:
            doc_name = result['document_name']
            if doc_name not in context_by_document:
                context_by_document[doc_name] = []
            context_by_document[doc_name].append(result['text'])

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
                role = msg.get('role', 'user')
                if role == 'agent':
                    role = 'assistant'
                elif role == 'system':
                    # Skip system messages from history
                    continue
                messages.append({"role": role, "content": msg.get('content', '')})

        # Ajoute la question actuelle si elle n'est pas déjà dans l'historique
        if not history or history[-1].get('content', '') != question:
            messages.append({"role": "user", "content": question})

        logger.info("[PROMPT OPENAI] %s", json.dumps(messages, ensure_ascii=False, indent=2))
        logger.info("Getting response from OpenAI with structured messages (system + RAG context, full history, current question)")
        gemini_only_flag = False
        try:
            gemini_only_flag = bool(agent and getattr(agent, 'type', '') == 'actionnable')
        except Exception:
            gemini_only_flag = False
        response = get_chat_response(messages, model_id=model_id, gemini_only=gemini_only_flag)
        logger.info("Successfully got response from OpenAI")
        return response
    except Exception as e:
        logger.error(f"Error getting answer: {e}")
        raise Exception(f"Erreur lors du traitement de votre question avec l'API OpenAI : {str(e)}")
def search_similar_texts_for_user(
    query_embedding: List[float],
    user_id: int,
    db: Session,
    top_k: int = 3,
    selected_doc_ids: List[int] = None,
    agent_id: int = None,
    company_id: int = None,
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
        query = db.query(
            DocumentChunk.id,
            DocumentChunk.chunk_text,
            DocumentChunk.chunk_index,
            DocumentChunk.document_id,
            Document.filename,
            Document.created_at,
            (1 - DocumentChunk.embedding_vec.cosine_distance(query_embedding)).label('similarity')
        ).join(Document, DocumentChunk.document_id == Document.id).filter(
            DocumentChunk.embedding_vec.isnot(None),
            Document.document_type != "traceability",
            # Hard tenant filter — applied on BOTH tables to survive RLS double-check
            Document.company_id == company_id,
            DocumentChunk.company_id == company_id,
        )

        if agent_id:
            query = query.filter(Document.agent_id == agent_id)
        else:
            query = query.filter(Document.user_id == user_id)

        if selected_doc_ids:
            query = query.filter(Document.id.in_(selected_doc_ids))

        query = query.order_by(
            DocumentChunk.embedding_vec.cosine_distance(query_embedding)
        ).limit(top_k)

        rows = query.all()

        if not rows:
            return []

        # Fetch neighbor chunks for context
        doc_ids = list({r.document_id for r in rows})
        neighbor_rows = db.query(
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_text
        ).filter(
            DocumentChunk.document_id.in_(doc_ids)
        ).order_by(
            DocumentChunk.document_id,
            DocumentChunk.chunk_index
        ).all()

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

            context_results.append({
                'similarity': float(row.similarity),
                'text': "\n".join(neighbors) if neighbors else row.chunk_text,
                'document_id': row.document_id,
                'document_name': row.filename,
                'created_at': row.created_at.isoformat()
            })

        return context_results
    except Exception as e:
        logger.error(f"Error searching similar texts: {e}")
        return []

def get_documents_summary(user_id: int, db: Session, selected_doc_ids: List[int] = None) -> List[dict]:
    """Get complete information about user's documents"""
    try:
        if selected_doc_ids:
            documents = db.query(Document).filter(
                Document.user_id == user_id,
                Document.id.in_(selected_doc_ids)
            ).all()
        else:
            documents = db.query(Document).filter(Document.user_id == user_id).all()
        
        doc_info = []
        for doc in documents:
            # Get all chunks for this document
            chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
            content = " ".join([chunk.chunk_text for chunk in chunks])
            
            doc_info.append({
                'id': doc.id,
                'filename': doc.filename,
                'created_at': doc.created_at.isoformat(),
                'content': content[:2000] + "..." if len(content) > 2000 else content,  # Limit content
                'chunk_count': len(chunks)
            })
        
        return doc_info
    
    except Exception as e:
        logger.error(f"Error getting documents summary: {e}")
        return []

def search_text_fallback(question: str, user_id: int, db: Session, top_k: int = 3) -> List[str]:
    """Fallback text search when embeddings are not available"""
    try:
        # Get all chunks for user's documents
        chunks = db.query(DocumentChunk).join(Document).filter(
            Document.user_id == user_id
        ).all()
        
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

def ingest_text_content(text_content: str, filename: str, user_id: int, agent_id: int, db: Session, gcs_url: str = None, notion_link_id: int = None, company_id: int = None) -> int:
    """Chunk text, create Document + DocumentChunks with Mistral embeddings via pgvector. Returns document.id."""
    import numpy as np
    from mistral_embeddings import EMBEDDING_DIM

    # Resolve company_id if not provided (defense in depth)
    if company_id is None:
        if agent_id:
            _agent = db.query(Agent.company_id).filter(Agent.id == agent_id).first()
            if _agent:
                company_id = _agent[0]
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
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        logger.info(f"Document saved with ID: {document.id}")

        def split_for_embedding(chunk, max_tokens=8192):
            chunk = chunk.replace('\x00', '')
            max_chars = max_tokens * 4
            return [chunk[i:i+max_chars] for i in range(0, len(chunk), max_chars)]

        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)} with Mistral embedding")
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
                chunk_index=i
            )
            db.add(doc_chunk)
        db.commit()
        logger.info(f"ingest_text_content completed: {filename}, {len(chunks)} chunks")
        return document.id
    except Exception as e:
        logger.error(f"ingest_text_content error: {e}")
        db.rollback()
        raise e


def process_document_for_user(filename: str, content: bytes, user_id: int, db: Session, agent_id: int = None, company_id: int = None) -> int:
    import tempfile
    import os
    try:
        logger.info(f"Starting to process document: {filename} for user {user_id}, agent {agent_id}")

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

        # Extraction du texte
        if filename.endswith('.pdf'):
            tmp_file = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
                    tmp_file = tmp.name
                    tmp.write(content)
                logger.info(f"Processing PDF file: {tmp_file}")
                text_content = load_text_from_pdf(tmp_file)
            finally:
                if tmp_file and os.path.exists(tmp_file):
                    os.unlink(tmp_file)
        else:
            try:
                text_content = content.decode('utf-8')
            except Exception as e:
                logger.warning(f"Could not decode content as utf-8: {e}")
                text_content = ''
        if text_content is None:
            text_content = ''
        logger.info(f"Extracted text length: {len(text_content)} characters")

        return ingest_text_content(text_content, filename, user_id, agent_id, db, gcs_url=gcs_url, company_id=company_id)
    except Exception as e:
        logger.error(f"Error processing document: {e}")
        db.rollback()
        raise e