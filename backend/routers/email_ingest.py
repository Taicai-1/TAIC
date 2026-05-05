"""Email ingestion endpoints: extractText, email ingest, attachment upload."""

import json
import hmac
import os
import logging
import traceback

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from typing import List

from auth import verify_token
from database import get_db, Agent, Document, DocumentChunk
from helpers.rate_limiting import _check_api_rate_limit, _API_EXTRACT_LIMIT
from schemas.email_ingest import EmailIngestRequest

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def extract_email_tags_from_title(title: str) -> List[str]:
    """Extrait les @tags du titre de l'email (case-insensitive)"""
    import re

    pattern = r"@([a-zA-Z0-9_-]+)"
    matches = re.findall(pattern, title)
    # Normaliser en lowercase avec @
    return [f"@{tag.lower()}" for tag in matches]


def find_agents_by_email_tags(db: Session, tags: List[str]) -> List[Agent]:
    """Trouve tous les agents dont email_tags contient au moins un des tags.

    Loads agents with email_tags set, then filters in Python to avoid
    PostgreSQL jsonb cast issues with the Text column type.
    """
    if not tags:
        return []

    lower_tags = [t.lower() for t in tags]

    agents_with_tags = db.query(Agent).filter(Agent.email_tags.isnot(None)).all()
    matching = []
    for agent in agents_with_tags:
        try:
            agent_tags = json.loads(agent.email_tags) if isinstance(agent.email_tags, str) else (agent.email_tags or [])
            agent_tags_lower = [t.lower() for t in agent_tags if isinstance(t, str)]
            if any(tag in agent_tags_lower for tag in lower_tags):
                matching.append(agent)
        except (json.JSONDecodeError, TypeError):
            continue
    return matching


def verify_email_api_key(request: Request) -> bool:
    """Vérifie l'API Key pour l'ingestion d'emails

    Security: Uses constant-time comparison (hmac.compare_digest) to prevent
    timing attacks that could be used to guess the API key character by character.
    """
    api_key = request.headers.get("X-API-Key", "")
    expected_key = os.getenv("EMAIL_INGEST_API_KEY", "")

    if not expected_key:
        logger.error("EMAIL_INGEST_API_KEY not configured in environment")
        raise HTTPException(status_code=500, detail="API Key not configured on server")

    if not api_key:
        logger.warning("Missing API Key for email ingestion")
        raise HTTPException(status_code=401, detail="Invalid API Key")

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(api_key, expected_key):
        logger.warning("Invalid API Key attempt for email ingestion")
        raise HTTPException(status_code=401, detail="Invalid API Key")

    return True


# ============================================================================
# ENDPOINTS
# ============================================================================


# Endpoint pour extraire le texte des fichiers uploadés (PDF, TXT, DOCX, XLSX, PPTX, etc.)


# Nouvelle version : accepte un seul fichier UploadFile
@router.post("/api/agent/extractText")
async def extract_text_from_file(file: UploadFile = File(...), user_id: str = Depends(verify_token)):
    """Extrait le texte d'un fichier uploadé et renvoie le texte extrait.

    Security: Requires authentication to prevent unauthorized file processing.
    """
    if not _check_api_rate_limit(user_id, "extract", _API_EXTRACT_LIMIT):
        raise HTTPException(status_code=429, detail="Too many extraction requests. Please try again later.")
    logger = logging.getLogger("extractText")
    ext = file.filename.lower().split(".")[-1]
    logger.info(
        f"Appel reçu sur /api/agent/extractText : filename={file.filename}, ext={ext}, content_type={getattr(file, 'content_type', 'unknown')}"
    )
    text = ""
    try:
        if ext == "pdf":
            MAX_PDF_PAGES = 500
            logger.info(f"Tentative extraction PDF: {file.filename}")
            try:
                import pdfplumber

                with pdfplumber.open(file.file) as pdf:
                    if len(pdf.pages) > MAX_PDF_PAGES:
                        raise HTTPException(
                            status_code=400, detail=f"PDF too large ({len(pdf.pages)} pages, max {MAX_PDF_PAGES})"
                        )
                    for i, page in enumerate(pdf.pages):
                        page_text = page.extract_text()
                        logger.info(
                            f"Page {i + 1} PDF: longueur={len(page_text) if page_text else 0}, aperçu='{page_text[:100] if page_text else ''}'"
                        )
                        if page_text:
                            text += page_text + "\n"
            except Exception as e:
                logger.error(f"Erreur extraction PDF {file.filename}: {e}")
        elif ext in ["txt", "md", "json", "xml", "csv"]:
            logger.info(f"Tentative extraction texte: {file.filename}")
            try:
                raw = await file.read()
                text = raw.decode(errors="ignore")
                logger.info(f"Texte extrait: longueur={len(text)}, aperçu='{text[:200]}'")
            except Exception as e:
                logger.error(f"Erreur extraction texte {file.filename}: {e}")
        elif ext in ["doc", "docx"]:
            logger.info(f"Tentative extraction DOCX: {file.filename}")
            try:
                from docx import Document as DocxDocument

                doc = DocxDocument(file.file)
                text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                logger.info(f"Texte DOCX extrait: longueur={len(text)}, aperçu='{text[:200]}'")
            except Exception as e:
                logger.error(f"Erreur extraction DOCX {file.filename}: {e}")
        elif ext in ["xls", "xlsx"]:
            logger.info(f"Tentative extraction XLSX: {file.filename}")
            try:
                import openpyxl

                wb = openpyxl.load_workbook(file.file, read_only=True)
                for sheet in wb.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        row_text = "\t".join([str(cell) if cell is not None else "" for cell in row])
                        text += row_text + "\n"
                logger.info(f"Texte XLSX extrait: longueur={len(text)}, aperçu='{text[:200]}'")
            except Exception as e:
                logger.error(f"Erreur extraction XLSX {file.filename}: {e}")
        elif ext in ["ppt", "pptx"]:
            logger.info(f"Tentative extraction PPTX: {file.filename}")
            try:
                from pptx import Presentation

                pres = Presentation(file.file)
                for slide in pres.slides:
                    for shape in slide.shapes:
                        if hasattr(shape, "text"):
                            text += shape.text + "\n"
                logger.info(f"Texte PPTX extrait: longueur={len(text)}, aperçu='{text[:200]}'")
            except Exception as e:
                logger.error(f"Erreur extraction PPTX {file.filename}: {e}")
        else:
            logger.warning(f"Type de fichier non supporté: {file.filename}")
            text = f"[Type de fichier non supporté: {file.filename}]"
    except Exception as e:
        logger.error(f"Erreur extraction {file.filename}: {e}")
        text = f"[Erreur extraction {file.filename}: {e}]"
    logger.info(f"Résultat extraction {file.filename}: longueur={len(text.strip())}, aperçu='{text.strip()[:200]}'")
    return {"text": text.strip()}


# ============================================================================
# EMAIL INGESTION API - Cloud Function Integration
# ============================================================================


@router.post("/api/emails/ingest")
async def ingest_email(payload: EmailIngestRequest, request: Request, db: Session = Depends(get_db)):
    """
    Ingère un email depuis la Cloud Function Gmail.

    Authentification via X-API-Key header.
    Route l'email vers les agents basé sur les @tags dans le titre.
    Si aucun tag trouvé ou aucun agent matché, ne rien faire.
    """
    # Vérifier l'API Key
    verify_email_api_key(request)

    try:
        logger.info(f"Ingesting email: {payload.title} (source_id: {payload.source_id})")

        # 1. Extraire les @tags du titre
        extracted_tags = extract_email_tags_from_title(payload.title)
        logger.info(f"Extracted tags from title: {extracted_tags}")

        # 2. Trouver les agents correspondants
        if extracted_tags:
            target_agents = find_agents_by_email_tags(db, extracted_tags)
            logger.info(f"Found {len(target_agents)} agents matching tags: {[a.name for a in target_agents]}")
        else:
            target_agents = []
            logger.info("No tags found in email title")

        # 3. Si aucun tag ou aucun agent matché, ne rien faire
        if not target_agents:
            logger.info(f"No matching agents for email: {payload.title} - skipping ingestion")
            return {
                "success": True,
                "document_ids": [],
                "agents_matched": 0,
                "message": "Aucun tag trouvé ou aucun companion correspondant - email ignoré",
            }

        # 4. Construire le contenu enrichi avec les métadonnées
        enriched_content = f"Sujet: {payload.title}\n"
        if payload.metadata:
            if payload.metadata.from_email:
                enriched_content += f"De: {payload.metadata.from_email}\n"
            if payload.metadata.date:
                enriched_content += f"Date: {payload.metadata.date}\n"
        enriched_content += f"\n{payload.content}"

        # Importer les fonctions nécessaires
        from file_loader import chunk_text
        from mistral_embeddings import get_embedding_fast
        import numpy as np

        # Fonction pour découper les gros chunks
        def split_for_embedding(chunk, max_tokens=8192):
            chunk = chunk.replace("\x00", "")
            max_chars = max_tokens * 4
            return [chunk[i : i + max_chars] for i in range(0, len(chunk), max_chars)]

        # Préparer les chunks une seule fois (réutilisés pour chaque agent)
        chunks = chunk_text(enriched_content)
        logger.info(f"Created {len(chunks)} chunks for email")

        # Calculer les embeddings une seule fois avec Mistral
        chunk_embeddings = []
        max_immediate_chunks = 20
        for i, chunk in enumerate(chunks):
            if i < max_immediate_chunks:
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
            else:
                avg_embedding = None
            chunk_embeddings.append(avg_embedding)

        # 5. Créer un document pour CHAQUE agent trouvé
        document_ids = []
        for agent in target_agents:
            # Vérifier les doublons pour cet agent spécifique
            # L'identifiant unique est stocké dans gcs_url pour la déduplication
            unique_id = f"email_{payload.source_id}_agent_{agent.id}"
            existing_doc = db.query(Document).filter(Document.gcs_url == unique_id).first()

            if existing_doc:
                logger.info(f"Email already ingested for agent {agent.name}: {payload.source_id}")
                document_ids.append(existing_doc.id)
                continue

            # Créer le document pour cet agent
            # Le filename affiche le titre de l'email (sujet) pour une meilleure lisibilité
            # On garde unique_id dans gcs_url pour la déduplication
            document = Document(
                filename=payload.title,  # Titre de l'email comme nom du document
                content=enriched_content,
                user_id=agent.user_id,
                agent_id=agent.id,
                company_id=agent.company_id,
                gcs_url=unique_id,  # Identifiant unique pour la déduplication
            )
            db.add(document)
            db.commit()
            db.refresh(document)

            logger.info(f"Document created for agent {agent.name} with ID: {document.id}")

            # Créer les chunks avec les embeddings pré-calculés (pgvector)
            for i, chunk in enumerate(chunks):
                doc_chunk = DocumentChunk(
                    document_id=document.id,
                    company_id=agent.company_id,
                    chunk_text=chunk,
                    embedding_vec=chunk_embeddings[i] if chunk_embeddings[i] else None,
                    chunk_index=i,
                )
                db.add(doc_chunk)

            db.commit()
            document_ids.append(document.id)

        logger.info(f"Email ingested successfully to {len(document_ids)} agents: {payload.title}")

        return {
            "success": True,
            "document_ids": document_ids,
            "agents_matched": len(target_agents),
            "agents": [{"id": a.id, "name": a.name} for a in target_agents],
            "tags_extracted": extracted_tags,
            "message": f"Email ingéré avec succès vers {len(target_agents)} companion(s)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ingesting email: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Erreur lors de l'ingestion de l'email")


@router.post("/api/emails/upload-attachment")
async def upload_email_attachment(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Upload une pièce jointe d'email comme document séparé.
    Le fichier est stocké sur GCS et devient téléchargeable.
    Route vers les agents basé sur les @tags passés dans le form data.

    Authentification via X-API-Key header.
    """
    # Vérifier l'API Key
    verify_email_api_key(request)

    try:
        # Récupérer les données du formulaire
        form = await request.form()
        email_subject = form.get("email_subject", "")
        source_id = form.get("source_id", "")

        logger.info(f"Uploading attachment: {file.filename} for email: {email_subject}")

        # Extraire les @tags du sujet de l'email
        extracted_tags = extract_email_tags_from_title(email_subject) if email_subject else []
        logger.info(f"Extracted tags from email subject: {extracted_tags}")

        # Trouver les agents correspondants
        if extracted_tags:
            target_agents = find_agents_by_email_tags(db, extracted_tags)
            logger.info(f"Found {len(target_agents)} agents matching tags")
        else:
            target_agents = []

        # Si aucun agent matché, ignorer
        if not target_agents:
            logger.info(f"No matching agents for attachment: {file.filename} - skipping")
            return {
                "success": True,
                "document_ids": [],
                "agents_matched": 0,
                "message": "Aucun companion correspondant - pièce jointe ignorée",
            }

        # Vérifier le type de fichier
        allowed_types = [".pdf", ".txt", ".docx"]
        if not any(file.filename.lower().endswith(ext) for ext in allowed_types):
            logger.warning(f"Unsupported file type: {file.filename}")
            return {"success": False, "message": f"Type de fichier non supporté: {file.filename}"}

        # Lire le contenu du fichier
        content = await file.read()

        # Vérifier la taille (10MB max)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 10MB)")

        # Importer les fonctions nécessaires
        from rag_engine import process_document_for_user

        # Créer un document pour CHAQUE agent trouvé
        document_ids = []
        for agent in target_agents:
            # Vérifier les doublons
            unique_id = f"attachment_{source_id}_{file.filename}_agent_{agent.id}"
            existing_doc = (
                db.query(Document)
                .filter(Document.gcs_url.contains(file.filename), Document.agent_id == agent.id)
                .first()
            )

            if existing_doc and source_id:
                # Vérification plus stricte avec source_id si disponible
                logger.info(f"Attachment may already exist for agent {agent.name}: {file.filename}")

            try:
                # Utiliser process_document_for_user qui gère l'upload GCS
                doc_id = process_document_for_user(
                    filename=file.filename, content=content, user_id=agent.user_id, db=db, agent_id=agent.id
                )
                document_ids.append(doc_id)
                logger.info(f"Attachment uploaded for agent {agent.name}: {file.filename} (doc_id: {doc_id})")

            except Exception as e:
                logger.error(f"Failed to upload attachment for agent {agent.name}: {e}")
                continue

        return {
            "success": True,
            "document_ids": document_ids,
            "agents_matched": len(target_agents),
            "agents": [{"id": a.id, "name": a.name} for a in target_agents],
            "filename": file.filename,
            "message": f"Pièce jointe uploadée vers {len(document_ids)} companion(s)",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading attachment: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'upload de la pièce jointe: {e}")
