"""Companion RAG folders: per-agent document folders with an active/inactive switch.

Agent documents are normal Document rows with agent_id set and agent_folder_id
pointing to an AgentFolder (NULL = "no folder"). An inactive folder's documents
are excluded from the agent's RAG retrieval (see rag_engine.search_similar_texts_for_user).
Edit permission on the agent is required for every mutation.
"""

import logging
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

import redis_client
from auth import verify_token
from database import get_db, AgentFolder, Document, SessionLocal
from folder_import import (
    MAX_IMPORT_FILES,
    MAX_IMPORT_TOTAL_SIZE,
    get_import_status,
    run_folder_import,
    set_import_status,
)
from helpers.agent_helpers import _user_can_access_agent, _user_can_edit_agent
from rag_engine import process_document_for_user
from validation import validate_file_content, validate_file_extension

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FOLDER_NAME_LENGTH = 100


def _folder_or_404(folder_id: int, agent_id: int, db: Session) -> AgentFolder:
    folder = db.query(AgentFolder).filter(AgentFolder.id == folder_id, AgentFolder.agent_id == agent_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.get("/api/agents/{agent_id}/folders")
async def list_agent_folders(agent_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List a companion's folders with document counts (read access required)."""
    _user_can_access_agent(int(user_id), agent_id, db)
    counts = dict(
        db.query(Document.agent_folder_id, func.count(Document.id))
        .filter(Document.agent_id == agent_id, Document.document_type == "rag", Document.mission_id.is_(None))
        .group_by(Document.agent_folder_id)
        .all()
    )
    folders = db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id).order_by(AgentFolder.name.asc()).all()
    return {
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "is_active": f.is_active,
                "parent_id": f.parent_id,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "document_count": int(counts.get(f.id, 0)),
            }
            for f in folders
        ],
        "uncategorized_count": int(counts.get(None, 0)),
    }


@router.post("/api/agents/{agent_id}/folders")
async def create_agent_folder(
    agent_id: int, payload: dict = Body(...), user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Create a folder for a companion (edit permission required)."""
    agent = _user_can_edit_agent(int(user_id), agent_id, db)
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
        _folder_or_404(parent_id, agent_id, db)  # parent must belong to this agent
    # Pre-check for a friendlier 409 (sibling uniqueness); DB constraint is the real race guard.
    sibling_q = db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name)
    sibling_q = (
        sibling_q.filter(AgentFolder.parent_id.is_(None))
        if parent_id is None
        else sibling_q.filter(AgentFolder.parent_id == parent_id)
    )
    if sibling_q.first():
        raise HTTPException(status_code=409, detail="A folder with this name already exists here")
    folder = AgentFolder(agent_id=agent_id, company_id=agent.company_id, name=name, is_active=True, parent_id=parent_id)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {
        "id": folder.id,
        "name": folder.name,
        "is_active": folder.is_active,
        "parent_id": folder.parent_id,
        "document_count": 0,
    }


@router.put("/api/agents/{agent_id}/folders/{folder_id}")
async def update_agent_folder(
    agent_id: int,
    folder_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Rename and/or toggle the active state of a folder (edit permission required)."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    folder = _folder_or_404(folder_id, agent_id, db)

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Folder name is required")
        if len(name) > MAX_FOLDER_NAME_LENGTH:
            raise HTTPException(status_code=400, detail=f"Folder name too long (max {MAX_FOLDER_NAME_LENGTH})")
        sibling_q = db.query(AgentFolder).filter(
            AgentFolder.agent_id == agent_id, AgentFolder.name == name, AgentFolder.id != folder_id
        )
        sibling_q = (
            sibling_q.filter(AgentFolder.parent_id.is_(None))
            if folder.parent_id is None
            else sibling_q.filter(AgentFolder.parent_id == folder.parent_id)
        )
        if sibling_q.first():
            raise HTTPException(status_code=409, detail="A folder with this name already exists here")
        folder.name = name

    if "is_active" in payload:
        folder.is_active = bool(payload.get("is_active"))

    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active, "parent_id": folder.parent_id}


@router.delete("/api/agents/{agent_id}/folders/{folder_id}")
async def delete_agent_folder(
    agent_id: int, folder_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Delete a folder (edit permission required). Blocked if the folder is not empty."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    folder = _folder_or_404(folder_id, agent_id, db)
    doc_count = (
        db.query(func.count(Document.id))
        .filter(
            Document.agent_folder_id == folder_id,
            Document.agent_id == agent_id,
            Document.document_type == "rag",
            Document.mission_id.is_(None),
        )
        .scalar()
    )
    child_count = db.query(func.count(AgentFolder.id)).filter(AgentFolder.parent_id == folder_id).scalar()
    if doc_count or child_count:
        raise HTTPException(status_code=409, detail="Folder is not empty")
    db.delete(folder)
    db.commit()
    return {"status": "deleted", "id": folder_id}


@router.put("/api/agents/{agent_id}/documents/{document_id}/folder")
async def move_agent_document(
    agent_id: int,
    document_id: int,
    payload: dict = Body(...),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Move a companion document to another folder, or to "no folder" (folder_id=None)."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    if "folder_id" not in payload:
        raise HTTPException(status_code=400, detail="folder_id is required (use null for no folder)")
    target_folder_id = payload.get("folder_id")
    if target_folder_id is not None:
        try:
            target_folder_id = int(target_folder_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="folder_id must be an integer or null")
        _folder_or_404(target_folder_id, agent_id, db)
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.agent_id == agent_id,
            Document.document_type == "rag",
            Document.mission_id.is_(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc.agent_folder_id = target_folder_id
    db.commit()
    return {"status": "moved", "id": document_id, "folder_id": doc.agent_folder_id}


def _agent_folder_import_with_db(task_id, agent_id, company_id, user_id, destination_parent_id, items, db):
    """Run a companion folder import using the provided DB session."""

    def find_child(parent_id, name):
        q = db.query(AgentFolder.id).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name)
        q = (
            q.filter(AgentFolder.parent_id.is_(None))
            if parent_id is None
            else q.filter(AgentFolder.parent_id == parent_id)
        )
        row = q.first()
        return row[0] if row else None

    def create_child(parent_id, name):
        folder = AgentFolder(agent_id=agent_id, company_id=company_id, name=name, is_active=True, parent_id=parent_id)
        db.add(folder)
        db.commit()
        db.refresh(folder)
        return folder.id

    def is_supported(filename, content):
        return validate_file_extension(filename) and validate_file_content(content, filename)

    def ingest_file(filename, content, folder_id):
        process_document_for_user(
            filename, content, user_id, db, agent_id=agent_id, company_id=company_id, agent_folder_id=folder_id
        )

    def set_status(total, done, skipped, failed, root_folder_id, status):
        set_import_status(task_id, total, done, skipped, failed, root_folder_id, status)

    return run_folder_import(
        items, destination_parent_id, find_child, create_child, ingest_file, is_supported, set_status
    )


def _run_agent_folder_import(task_id, agent_id, company_id, user_id, destination_parent_id, items):
    """Background job: owns its own DB session (the request session is gone by then)."""
    db = SessionLocal()
    try:
        return _agent_folder_import_with_db(task_id, agent_id, company_id, user_id, destination_parent_id, items, db)
    except Exception as e:
        set_import_status(task_id, 0, 0, 0, 0, None, "failed", error=str(e))
        raise
    finally:
        db.close()


@router.post("/api/agents/{agent_id}/folders/import")
async def import_agent_folder(
    agent_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(...),
    parent_id: str | None = Form(None),
    user_id: str = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Import a whole directory tree of documents into a companion's folders."""
    agent = _user_can_edit_agent(int(user_id), agent_id, db)
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files and paths length mismatch")
    if len(files) > MAX_IMPORT_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files (max {MAX_IMPORT_FILES})")
    dest_parent_id = None
    if parent_id not in (None, ""):
        try:
            dest_parent_id = int(parent_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="parent_id must be an integer or null")
        _folder_or_404(dest_parent_id, agent_id, db)

    items = []
    total_size = 0
    for f, rel in zip(files, paths):
        content = await f.read()
        total_size += len(content)
        if total_size > MAX_IMPORT_TOTAL_SIZE:
            raise HTTPException(status_code=413, detail="Import too large")
        items.append((f.filename, rel, content))

    task_id = str(uuid4())
    if redis_client.get_redis() is not None:
        set_import_status(task_id, len(items), 0, 0, 0, None, "processing")
        background_tasks.add_task(
            _run_agent_folder_import, task_id, agent_id, agent.company_id, int(user_id), dest_parent_id, items
        )
        return {"import_task_id": task_id, "status": "processing"}
    # Synchronous fallback: reuse the request session and return the summary now.
    summary = _agent_folder_import_with_db(task_id, agent_id, agent.company_id, int(user_id), dest_parent_id, items, db)
    return {**summary, "status": "completed"}


@router.get("/api/agents/{agent_id}/folders/import-status/{task_id}")
async def agent_folder_import_status(
    agent_id: int, task_id: str, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Poll the status of a folder-import task."""
    _user_can_edit_agent(int(user_id), agent_id, db)
    status = get_import_status(task_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    return status
