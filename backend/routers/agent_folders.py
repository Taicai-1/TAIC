"""Companion RAG folders: per-agent document folders with an active/inactive switch.

Agent documents are normal Document rows with agent_id set and agent_folder_id
pointing to an AgentFolder (NULL = "no folder"). An inactive folder's documents
are excluded from the agent's RAG retrieval (see rag_engine.search_similar_texts_for_user).
Edit permission on the agent is required for every mutation.
"""

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, AgentFolder, Document
from helpers.agent_helpers import _user_can_access_agent, _user_can_edit_agent

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FOLDER_NAME_LENGTH = 100


def _folder_or_404(folder_id: int, agent_id: int, db: Session) -> AgentFolder:
    folder = (
        db.query(AgentFolder).filter(AgentFolder.id == folder_id, AgentFolder.agent_id == agent_id).first()
    )
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
    folders = (
        db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id).order_by(AgentFolder.name.asc()).all()
    )
    return {
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "is_active": f.is_active,
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
    # Pre-check for a friendlier 409; the DB UniqueConstraint is the real guard against races.
    exists = (
        db.query(AgentFolder).filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name).first()
    )
    if exists:
        raise HTTPException(status_code=409, detail="A folder with this name already exists")
    folder = AgentFolder(agent_id=agent_id, company_id=agent.company_id, name=name, is_active=True)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active, "document_count": 0}


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
        collision = (
            db.query(AgentFolder)
            .filter(AgentFolder.agent_id == agent_id, AgentFolder.name == name, AgentFolder.id != folder_id)
            .first()
        )
        if collision:
            raise HTTPException(status_code=409, detail="A folder with this name already exists")
        folder.name = name

    if "is_active" in payload:
        folder.is_active = bool(payload.get("is_active"))

    db.commit()
    db.refresh(folder)
    return {"id": folder.id, "name": folder.name, "is_active": folder.is_active}


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
    if doc_count:
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
