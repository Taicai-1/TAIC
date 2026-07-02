"""Conversational CV intelligence: intent router + three read-only tools
(sourcing / analytics / candidate Q&A) layered on top of the RAG answer path.

Activated only for companions whose company-RAG folders include a CV-base folder;
otherwise callers fall back to the normal RAG flow (answer_cv returns None)."""

import json
import logging

logger = logging.getLogger(__name__)


def folders_include_cv_base(db, company_id, folder_ids):
    """True if the company has a CV-base folder within ``folder_ids`` (or any, if None)."""
    if not company_id:
        return False
    from database import CompanyFolder

    q = db.query(CompanyFolder.id).filter(
        CompanyFolder.company_id == company_id,
        CompanyFolder.is_cv_base.is_(True),
    )
    if folder_ids:
        q = q.filter(CompanyFolder.id.in_(folder_ids))
    return bool(db.query(q.exists()).scalar())
