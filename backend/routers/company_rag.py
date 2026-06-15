"""Company RAG endpoints: shared organization documents (list / upload / delete).

Company documents are normal Document rows flagged is_company_rag=True with
agent_id=NULL. Any company member may list them (download is served by the
existing documents download endpoint); only owners/admins may upload or delete.
Tenant boundary is the caller's company_id.
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Document
from helpers.tenant import _get_caller_company_id
from permissions import require_role
from rag_engine import process_document_for_user
from redis_client import get_redis
from routers.documents import _process_document_background
from utils import event_tracker
from validation import MAX_FILE_SIZE

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_TYPES = [".pdf", ".txt", ".docx", ".ics", ".json"]


def _require_company_id(user_id: str, db: Session) -> int:
    """Resolve the caller's company_id (cache-aware) or raise 400 if they have none."""
    company_id = _get_caller_company_id(user_id, db)
    if company_id is None:
        raise HTTPException(status_code=400, detail="You are not part of an organization")
    return company_id


@router.get("/api/company-rag/documents")
async def list_company_documents(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's shared RAG documents (any member)."""
    company_id = _require_company_id(user_id, db)
    docs = (
        db.query(Document)
        .filter(Document.company_id == company_id, Document.is_company_rag.is_(True))
        .order_by(Document.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "source_url": d.source_url,
                "document_type": d.document_type,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]
    }


@router.post("/api/company-rag/documents")
async def upload_company_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Upload a shared company RAG document (owner/admin only)."""
    try:
        require_role(int(user_id), db, "admin")
        company_id = _require_company_id(user_id, db)

        if file.size and file.size > MAX_FILE_SIZE:
            max_mb = MAX_FILE_SIZE / (1024 * 1024)
            raise HTTPException(status_code=413, detail=f"File too large (max {max_mb:.0f}MB)")
        if not any(file.filename.lower().endswith(ext) for ext in ALLOWED_TYPES):
            raise HTTPException(status_code=400, detail="File type not supported")

        content = await file.read()

        r = get_redis()
        if r is not None:
            task_id = str(uuid4())
            r.setex(
                f"doc_task:{task_id}",
                3600,
                json.dumps({
                    "task_id": task_id, "status": "processing",
                    "filename": file.filename, "document_id": None, "error": None,
                }),
            )
            background_tasks.add_task(
                _process_document_background,
                task_id, file.filename, content, int(user_id), None, company_id, None, True,
            )
            logger.info(f"Company document queued for async processing: {file.filename} (task_id={task_id})")
            return {"filename": file.filename, "task_id": task_id, "status": "processing"}

        doc_id = process_document_for_user(
            file.filename, content, int(user_id), db,
            agent_id=None, company_id=company_id, is_company_rag=True,
        )
        logger.info(f"Company document uploaded (sync) by user {user_id}: {file.filename}")
        event_tracker.track_document_upload(int(user_id), file.filename, len(content))
        return {"filename": file.filename, "document_id": doc_id, "status": "uploaded"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading company document: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/api/company-rag/documents/{document_id}")
async def delete_company_document(
    document_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a shared company RAG document (owner/admin only). Chunks cascade."""
    try:
        require_role(int(user_id), db, "admin")
        company_id = _require_company_id(user_id, db)

        doc = (
            db.query(Document)
            .filter(
                Document.id == document_id,
                Document.company_id == company_id,
                Document.is_company_rag.is_(True),
            )
            .first()
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Company document not found")

        db.delete(doc)
        db.commit()
        logger.info(f"Company document {document_id} deleted by user {user_id}")
        return {"status": "deleted", "id": document_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company document {document_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
