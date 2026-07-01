"""Company RAG endpoints: shared organization documents (list / upload / delete).

Company documents are normal Document rows flagged is_company_rag=True with
agent_id=NULL. Any company member may list them (download is served by the
existing documents download endpoint); only owners/admins may upload or delete.
Tenant boundary is the caller's company_id.
"""

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

import redis_client
from auth import verify_token
from database import get_db, Document, CompanyFolder, SessionLocal
from folder_import import (
    MAX_IMPORT_FILES,
    MAX_IMPORT_TOTAL_SIZE,
    get_import_status,
    run_folder_import,
    set_import_status,
)
from helpers.tenant import _get_caller_company_id
from permissions import require_role
from rag_engine import process_document_for_user
from redis_client import get_redis
from routers.documents import _process_document_background
from utils import event_tracker
from validation import MAX_FILE_SIZE, validate_file_content, validate_file_extension
from cv_extraction import extract_cv_metadata, upsert_candidate_profile

logger = logging.getLogger(__name__)

# Default small model for CV metadata extraction (Phase 1; tune via POC, see spec section 8).
CV_EXTRACTION_MODEL = "gpt-4o-mini"

# CV bases legitimately contain far more files than an interactive folder import.
MAX_CV_IMPORT_FILES = 5000


def resolve_import_file_cap(is_cv_base: bool) -> int:
    """Per-destination file cap: CV-base folders allow a much larger bulk import."""
    return MAX_CV_IMPORT_FILES if is_cv_base else MAX_IMPORT_FILES


router = APIRouter()

ALLOWED_TYPES = [".pdf", ".txt", ".docx", ".ics", ".json"]
MAX_FOLDER_NAME_LENGTH = 100


def _require_company_id(user_id: str, db: Session) -> int:
    """Resolve the caller's company_id (cache-aware) or raise 400 if they have none."""
    company_id = _get_caller_company_id(user_id, db)
    if company_id is None:
        raise HTTPException(status_code=400, detail="You are not part of an organization")
    return company_id


@router.get("/api/company-rag/documents")
async def list_company_documents(
    folder_id: int = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List the organization's shared RAG documents (any member).

    Pass ``folder_id`` as a query parameter to filter to a specific folder.
    """
    try:
        company_id = _require_company_id(user_id, db)
        q = db.query(Document).filter(Document.company_id == company_id, Document.is_company_rag.is_(True))
        if folder_id is not None:
            _folder_or_404(folder_id, company_id, db)  # 404 on foreign/unknown folder (no id-probing)
            q = q.filter(Document.folder_id == folder_id)
        docs = q.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
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

        # WS5: validate real content (magic bytes) + cap PDF pages, mirroring the /upload path.
        from validation import validate_file_content

        if not validate_file_content(content, file.filename):
            raise HTTPException(status_code=400, detail="File content does not match its type")
        if file.filename.lower().endswith(".pdf"):
            import io
            import pdfplumber

            try:
                with pdfplumber.open(io.BytesIO(content)) as _pdf:
                    if len(_pdf.pages) > 500:
                        raise HTTPException(status_code=400, detail=f"PDF too large ({len(_pdf.pages)} pages, max 500)")
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(status_code=400, detail="Unable to read PDF")

        r = get_redis()
        if r is not None:
            task_id = str(uuid4())
            r.setex(
                f"doc_task:{task_id}",
                3600,
                json.dumps(
                    {
                        "task_id": task_id,
                        "status": "processing",
                        "filename": file.filename,
                        "document_id": None,
                        "error": None,
                    }
                ),
            )
            background_tasks.add_task(
                _process_document_background,
                task_id,
                file.filename,
                content,
                int(user_id),
                None,
                company_id,
                None,
                True,
                folder_id,
            )
            logger.info(f"Company document queued for async processing: {file.filename} (task_id={task_id})")
            return {"filename": file.filename, "task_id": task_id, "status": "processing"}

        doc_id = process_document_for_user(
            file.filename,
            content,
            int(user_id),
            db,
            agent_id=None,
            company_id=company_id,
            is_company_rag=True,
            folder_id=folder_id,
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
        db.query(CompanyFolder).filter(CompanyFolder.id == folder_id, CompanyFolder.company_id == company_id).first()
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
                    "parent_id": f.parent_id,
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
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
        parent_id = payload.get("parent_id")
        if parent_id is not None:
            try:
                parent_id = int(parent_id)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
            _folder_or_404(parent_id, company_id, db)  # parent must belong to this company
        sibling_q = db.query(CompanyFolder).filter(CompanyFolder.company_id == company_id, CompanyFolder.name == name)
        sibling_q = (
            sibling_q.filter(CompanyFolder.parent_id.is_(None))
            if parent_id is None
            else sibling_q.filter(CompanyFolder.parent_id == parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
        folder = CompanyFolder(company_id=company_id, name=name, parent_id=parent_id)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return {"id": folder.id, "name": folder.name, "parent_id": folder.parent_id, "document_count": 0}
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
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
        # Pre-check for a friendlier 409; the DB UniqueConstraint is the real guard against races.
        sibling_q = db.query(CompanyFolder).filter(
            CompanyFolder.company_id == company_id, CompanyFolder.name == name, CompanyFolder.id != folder_id
        )
        sibling_q = (
            sibling_q.filter(CompanyFolder.parent_id.is_(None))
            if folder.parent_id is None
            else sibling_q.filter(CompanyFolder.parent_id == folder.parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
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
        child_count = db.query(func.count(CompanyFolder.id)).filter(CompanyFolder.parent_id == folder_id).scalar()
        if doc_count or child_count:
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


def _company_folder_import_with_db(task_id, company_id, user_id, destination_parent_id, items, db):
    """Run a company folder import using the provided DB session."""

    def find_child(parent_id, name):
        q = db.query(CompanyFolder.id).filter(CompanyFolder.company_id == company_id, CompanyFolder.name == name)
        q = (
            q.filter(CompanyFolder.parent_id.is_(None))
            if parent_id is None
            else q.filter(CompanyFolder.parent_id == parent_id)
        )
        row = q.first()
        return row[0] if row else None

    def create_child(parent_id, name):
        folder = CompanyFolder(company_id=company_id, name=name, parent_id=parent_id)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return folder.id

    def is_supported(filename, content):
        return validate_file_extension(filename) and validate_file_content(content, filename)

    _cv_base_cache = {}

    def _folder_is_cv_base(folder_id):
        # Phase 1: only the immediate destination folder is checked, not ancestors —
        # CVs imported into a subfolder of a cv_base folder are not profiled.
        if folder_id is None:
            return False
        if folder_id not in _cv_base_cache:
            row = db.query(CompanyFolder.is_cv_base).filter(CompanyFolder.id == folder_id).first()
            _cv_base_cache[folder_id] = bool(row[0]) if row else False
        return _cv_base_cache[folder_id]

    def ingest_file(filename, content, folder_id):
        document_id = process_document_for_user(
            filename, content, user_id, db, company_id=company_id, is_company_rag=True, folder_id=folder_id
        )
        if document_id and _folder_is_cv_base(folder_id):
            text_content = (
                db.query(Document.content).filter(Document.id == document_id).scalar() or ""
            )
            try:
                profile = extract_cv_metadata(text_content, model_id=CV_EXTRACTION_MODEL)
                upsert_candidate_profile(
                    db, document_id=document_id, company_id=company_id, folder_id=folder_id,
                    profile=profile, model_id=CV_EXTRACTION_MODEL, status="done",
                )
            except Exception as e:
                logger.warning(f"CV extraction failed for {filename}: {e}")
                try:
                    upsert_candidate_profile(
                        db, document_id=document_id, company_id=company_id, folder_id=folder_id,
                        profile={"raw_extraction": {}}, model_id=CV_EXTRACTION_MODEL, status="failed",
                    )
                except Exception as e2:
                    logger.warning(f"CV failed-status upsert also failed for {filename}: {e2}")
            db.commit()

    def set_status(total, done, skipped, failed, root_folder_id, status):
        set_import_status(task_id, total, done, skipped, failed, root_folder_id, status)

    return run_folder_import(
        items,
        destination_parent_id,
        find_child,
        create_child,
        ingest_file,
        is_supported,
        set_status,
        rollback=db.rollback,
        max_name_len=MAX_FOLDER_NAME_LENGTH,
    )


def _run_company_folder_import(task_id, company_id, user_id, destination_parent_id, items):
    """Background job: owns its own DB session (the request session is gone by then)."""
    db = SessionLocal()
    try:
        return _company_folder_import_with_db(task_id, company_id, user_id, destination_parent_id, items, db)
    except Exception as e:
        set_import_status(task_id, 0, 0, 0, 0, None, "failed", error=str(e))
        raise
    finally:
        db.close()


@router.post("/api/company-rag/folders/import")
async def import_company_folder(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    parent_id: str | None = Form(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Import a whole directory tree of documents into the company RAG folders (admin)."""
    require_role(int(user_id), db, "admin")
    company_id = _require_company_id(user_id, db)
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files and paths length mismatch")
    dest_parent_id = None
    if parent_id not in (None, ""):
        try:
            dest_parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
        _folder_or_404(dest_parent_id, company_id, db)
    dest_is_cv_base = False
    if dest_parent_id is not None:
        row = db.query(CompanyFolder.is_cv_base).filter(
            CompanyFolder.id == dest_parent_id, CompanyFolder.company_id == company_id
        ).first()
        dest_is_cv_base = bool(row[0]) if row else False
    file_cap = resolve_import_file_cap(dest_is_cv_base)
    if len(files) > file_cap:
        raise HTTPException(status_code=413, detail=f"Too many files (max {file_cap})")

    items = []
    total_size = 0
    max_mb = MAX_FILE_SIZE // (1024 * 1024)
    for f, rel in zip(files, paths):
        # Reject by declared size BEFORE buffering the file into memory (OOM/DoS guard).
        if f.size and f.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"A file exceeds the {max_mb}MB limit")
        if f.size and total_size + f.size > MAX_IMPORT_TOTAL_SIZE:
            raise HTTPException(status_code=413, detail="Import too large")
        content = await f.read()
        if len(content) > MAX_FILE_SIZE:  # fallback when Content-Length is absent
            raise HTTPException(status_code=413, detail=f"A file exceeds the {max_mb}MB limit")
        total_size += len(content)
        if total_size > MAX_IMPORT_TOTAL_SIZE:
            raise HTTPException(status_code=413, detail="Import too large")
        items.append((f.filename, rel, content))

    task_id = str(uuid4())
    if redis_client.get_redis() is not None:
        set_import_status(task_id, len(items), 0, 0, 0, None, "processing")
        background_tasks.add_task(_run_company_folder_import, task_id, company_id, int(user_id), dest_parent_id, items)
        return {"import_task_id": task_id, "status": "processing"}
    summary = _company_folder_import_with_db(task_id, company_id, int(user_id), dest_parent_id, items, db)
    return {**summary, "status": "completed"}


@router.get("/api/company-rag/folders/import-status/{task_id}")
async def company_folder_import_status(
    task_id: str, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Poll the status of a company folder-import task."""
    require_role(int(user_id), db, "member")
    status = get_import_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    return status
