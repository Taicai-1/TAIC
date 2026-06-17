"""Company RAG endpoints: shared organization documents (list / upload / delete).

Company documents are normal Document rows flagged is_company_rag=True with
agent_id=NULL. Any company member may list them (download is served by the
existing documents download endpoint); only owners/admins may upload or delete.
Tenant boundary is the caller's company_id.
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Document, CompanyFolder
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
    folder_id: int = None,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's shared RAG documents (any member).

    Pass ``folder_id`` as a query parameter to filter to a specific folder.
    """
    try:
        company_id = _require_company_id(user_id, db)
        q = db.query(Document).filter(
            Document.company_id == company_id, Document.is_company_rag.is_(True)
        )
        if folder_id is not None:
            q = q.filter(Document.folder_id == folder_id)
        docs = q.order_by(Document.created_at.desc()).all()
        return {
            "documents": [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "source_url": d.source_url,
                    "document_type": d.document_type,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "folder_id": d.folder_id,
                }
                for d in docs
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing company documents: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/api/company-rag/documents")
async def upload_company_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    folder_id: int = Form(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Upload a shared company RAG document into a folder (owner/admin only)."""
    try:
        require_role(int(user_id), db, "admin")
        company_id = _require_company_id(user_id, db)
        _folder_or_404(folder_id, company_id, db)

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
                task_id, file.filename, content, int(user_id), None, company_id, None, True, folder_id,
            )
            logger.info(f"Company document queued for async processing: {file.filename} (task_id={task_id})")
            return {"filename": file.filename, "task_id": task_id, "status": "processing"}

        doc_id = process_document_for_user(
            file.filename, content, int(user_id), db,
            agent_id=None, company_id=company_id, is_company_rag=True, folder_id=folder_id,
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


# ---------------------------------------------------------------------------
# Folder helpers + endpoints
# ---------------------------------------------------------------------------


def _folder_or_404(folder_id: int, company_id: int, db: Session) -> CompanyFolder:
    folder = (
        db.query(CompanyFolder)
        .filter(CompanyFolder.id == folder_id, CompanyFolder.company_id == company_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.get("/api/company-rag/folders")
async def list_company_folders(
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's company-RAG folders with document counts (any member)."""
    try:
        company_id = _require_company_id(user_id, db)
        counts = dict(
            db.query(Document.folder_id, func.count(Document.id))
            .filter(Document.company_id == company_id, Document.is_company_rag.is_(True))
            .group_by(Document.folder_id)
            .all()
        )
        folders = (
            db.query(CompanyFolder)
            .filter(CompanyFolder.company_id == company_id)
            .order_by(CompanyFolder.name.asc())
            .all()
        )
        return {
            "folders": [
                {
                    "id": f.id,
                    "name": f.name,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "document_count": int(counts.get(f.id, 0)),
                }
                for f in folders
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing company folders: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/api/company-rag/folders")
async def create_company_folder(
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Create a company-RAG folder (owner/admin only)."""
    try:
        company_id = require_role(int(user_id), db, "admin").company_id
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        # Pre-check for a friendlier 409; the DB UniqueConstraint is the real guard against races.
        exists = (
            db.query(CompanyFolder)
            .filter(CompanyFolder.company_id == company_id, CompanyFolder.name == name)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="A folder with this name already exists")
        folder = CompanyFolder(company_id=company_id, name=name)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return {"id": folder.id, "name": folder.name, "document_count": 0}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating company folder: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/api/company-rag/folders/{folder_id}")
async def rename_company_folder(
    folder_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Rename a company-RAG folder (owner/admin only)."""
    try:
        company_id = require_role(int(user_id), db, "admin").company_id
        folder = _folder_or_404(folder_id, company_id, db)
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        # Pre-check for a friendlier 409; the DB UniqueConstraint is the real guard against races.
        collision = (
            db.query(CompanyFolder)
            .filter(
                CompanyFolder.company_id == company_id,
                CompanyFolder.name == name,
                CompanyFolder.id != folder_id,
            )
            .first()
        )
        if collision:
            raise HTTPException(status_code=409, detail="A folder with this name already exists")
        folder.name = name
        db.commit()
        return {"id": folder.id, "name": folder.name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming company folder {folder_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/api/company-rag/folders/{folder_id}")
async def delete_company_folder(
    folder_id: int,
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Delete a company-RAG folder (owner/admin only). Blocked if the folder is not empty."""
    try:
        company_id = require_role(int(user_id), db, "admin").company_id
        folder = _folder_or_404(folder_id, company_id, db)
        doc_count = (
            db.query(func.count(Document.id))
            .filter(Document.folder_id == folder_id, Document.company_id == company_id)
            .scalar()
        )
        if doc_count:
            raise HTTPException(status_code=409, detail="Folder is not empty")
        db.delete(folder)
        db.commit()
        logger.info(f"Company folder {folder_id} deleted by user {user_id}")
        return {"status": "deleted", "id": folder_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting company folder {folder_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/api/company-rag/documents/{document_id}/folder")
async def move_company_document(
    document_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Move a company-RAG document to another folder (owner/admin only)."""
    try:
        company_id = require_role(int(user_id), db, "admin").company_id
        target_folder_id = payload.get("folder_id")
        if target_folder_id is None:
            raise HTTPException(status_code=400, detail="folder_id is required")
        try:
            target_folder_id = int(target_folder_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="folder_id must be an integer")
        _folder_or_404(target_folder_id, company_id, db)
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
        doc.folder_id = target_folder_id
        db.commit()
        return {"status": "moved", "id": document_id, "folder_id": doc.folder_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error moving company document {document_id}: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
