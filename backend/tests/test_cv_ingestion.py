import rag_engine
import routers.company_rag as company_rag
from sqlalchemy import text
from database import Document, DocumentChunk, CandidateProfile, CompanyFolder
from cv_extraction import upsert_candidate_profile
from routers.company_rag import resolve_import_file_cap, MAX_IMPORT_FILES, MAX_CV_IMPORT_FILES


def test_ingest_text_content_batches_embeddings(db_session, test_user, test_agent, monkeypatch):
    batch_calls = {"n": 0}

    def fake_batch(texts, batch_size=64):
        batch_calls["n"] += 1
        return [[0.1] * 1024 for _ in texts]

    # rag_engine does `from mistral_embeddings import get_embeddings_batch` (early binding),
    # so only the module-level attribute patch takes effect.
    monkeypatch.setattr(rag_engine, "get_embeddings_batch", fake_batch, raising=False)

    # chunk_size default = 512 tokens (cl100k_base). Each sentence below is ~20 tokens;
    # 120 sentences ≈ 2 400 tokens → reliably produces ≥ 3 chunks, well above 1.
    text = " ".join(
        f"Candidate {i} has expertise in Python, machine learning, and data pipelines "
        f"with {i + 3} years of industry experience."
        for i in range(120)
    )
    doc_id = rag_engine.ingest_text_content(
        text_content=text, filename="cv.txt", user_id=test_user.id,
        agent_id=test_agent.id, db=db_session, company_id=test_user.company_id,
    )

    doc = db_session.query(Document).filter(Document.id == doc_id).first()
    assert doc is not None
    chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert len(chunks) >= 2                 # input spans multiple chunks
    assert all(c.embedding_vec is not None for c in chunks)
    assert batch_calls["n"] == 1            # ALL chunks embedded in a single batch call


def test_candidate_profile_crud(db_session, test_user, test_agent):
    doc = Document(filename="cv.pdf", content="x", user_id=test_user.id,
                   agent_id=test_agent.id, company_id=test_user.company_id, is_company_rag=True)
    db_session.add(doc)
    db_session.flush()

    profile = CandidateProfile(
        document_id=doc.id, company_id=test_user.company_id,
        full_name="Jean Dupont", seniority="senior", years_experience=8,
        skills=["python", "react"], languages=["french"],
        raw_extraction={"summary": "x"}, extraction_status="done", extraction_model="gpt-4o-mini",
    )
    db_session.add(profile)
    db_session.flush()

    fetched = db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).first()
    assert fetched.full_name == "Jean Dupont"
    assert fetched.skills == ["python", "react"]
    assert fetched.years_experience == 8


def test_company_folder_is_cv_base_defaults_false(db_session, test_user):
    folder = CompanyFolder(company_id=test_user.company_id, name="CVs")
    db_session.add(folder)
    db_session.flush()
    db_session.refresh(folder)
    assert folder.is_cv_base is False

    folder.is_cv_base = True
    db_session.flush()
    db_session.refresh(folder)
    assert folder.is_cv_base is True


def _make_cv_doc(db_session, test_user, test_agent):
    doc = Document(filename="cv.pdf", content="x", user_id=test_user.id,
                   agent_id=test_agent.id, company_id=test_user.company_id, is_company_rag=True)
    db_session.add(doc)
    db_session.flush()
    return doc


def test_upsert_candidate_profile_creates_then_skips(db_session, test_user, test_agent):
    doc = _make_cv_doc(db_session, test_user, test_agent)
    profile = {"full_name": "Jane", "years_experience": 5, "skills": ["python"],
               "languages": [], "raw_extraction": {"summary": "x"}}

    created = upsert_candidate_profile(
        db_session, document_id=doc.id, company_id=test_user.company_id,
        folder_id=None, profile=profile, model_id="gpt-4o-mini",
    )
    assert created is True
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 1

    # Second call is idempotent: skipped, no duplicate.
    again = upsert_candidate_profile(
        db_session, document_id=doc.id, company_id=test_user.company_id,
        folder_id=None, profile=profile, model_id="gpt-4o-mini",
    )
    assert again is False
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 1


def test_ingest_file_extracts_when_cv_base(db_session, test_user, monkeypatch):
    folder = CompanyFolder(company_id=test_user.company_id, name="CVs", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()

    # Stub the heavy bits: document ingestion returns a doc id; extraction returns a profile.
    doc = Document(filename="a.pdf", content="x", user_id=test_user.id,
                   company_id=test_user.company_id, is_company_rag=True, folder_id=folder.id)
    db_session.add(doc)
    db_session.flush()

    # Accept the dummy bytes as a supported file (real validators reject non-PDF bytes).
    monkeypatch.setattr(company_rag, "validate_file_extension", lambda fn: True)
    monkeypatch.setattr(company_rag, "validate_file_content", lambda content, fn: True)
    monkeypatch.setattr(company_rag, "process_document_for_user", lambda *a, **k: doc.id)
    monkeypatch.setattr(
        company_rag, "extract_cv_metadata",
        lambda text, model_id=None: {"full_name": "Bob", "skills": ["python"], "languages": [],
                                     "years_experience": 3, "raw_extraction": {}},
    )

    summary = company_rag._company_folder_import_with_db(
        task_id="t1", company_id=test_user.company_id, user_id=test_user.id,
        destination_parent_id=folder.id,
        items=[("a.pdf", "a.pdf", b"PDFBYTES")], db=db_session,
    )

    assert summary["done"] == 1
    prof = db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).first()
    assert prof is not None and prof.full_name == "Bob"


def test_ingest_file_skips_extraction_when_not_cv_base(db_session, test_user, monkeypatch):
    folder = CompanyFolder(company_id=test_user.company_id, name="Docs", is_cv_base=False)
    db_session.add(folder)
    db_session.flush()
    doc = Document(filename="b.pdf", content="x", user_id=test_user.id,
                   company_id=test_user.company_id, is_company_rag=True, folder_id=folder.id)
    db_session.add(doc)
    db_session.flush()

    called = {"extract": 0}
    monkeypatch.setattr(company_rag, "validate_file_extension", lambda fn: True)
    monkeypatch.setattr(company_rag, "validate_file_content", lambda content, fn: True)
    monkeypatch.setattr(company_rag, "process_document_for_user", lambda *a, **k: doc.id)

    def _extract(*a, **k):
        called["extract"] += 1
        return {}

    monkeypatch.setattr(company_rag, "extract_cv_metadata", _extract)

    company_rag._company_folder_import_with_db(
        task_id="t2", company_id=test_user.company_id, user_id=test_user.id,
        destination_parent_id=folder.id, items=[("b.pdf", "b.pdf", b"X")], db=db_session,
    )
    assert called["extract"] == 0
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).count() == 0


def test_ingest_file_writes_failed_status_when_extraction_raises(db_session, test_user, monkeypatch):
    folder = CompanyFolder(company_id=test_user.company_id, name="CVs2", is_cv_base=True)
    db_session.add(folder)
    db_session.flush()
    doc = Document(filename="c.pdf", content="x", user_id=test_user.id,
                   company_id=test_user.company_id, is_company_rag=True, folder_id=folder.id)
    db_session.add(doc)
    db_session.flush()

    monkeypatch.setattr(company_rag, "validate_file_extension", lambda fn: True)
    monkeypatch.setattr(company_rag, "validate_file_content", lambda content, fn: True)
    monkeypatch.setattr(company_rag, "process_document_for_user", lambda *a, **k: doc.id)

    def _boom(*a, **k):
        raise RuntimeError("LLM rate limit")

    monkeypatch.setattr(company_rag, "extract_cv_metadata", _boom)

    summary = company_rag._company_folder_import_with_db(
        task_id="t3", company_id=test_user.company_id, user_id=test_user.id,
        destination_parent_id=folder.id, items=[("c.pdf", "c.pdf", b"PDFBYTES")], db=db_session,
    )

    # The file still counts as done (document was ingested); a failed-status profile is recorded.
    assert summary["done"] == 1
    prof = db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc.id).first()
    assert prof is not None and prof.extraction_status == "failed"


def test_resolve_import_file_cap():
    assert resolve_import_file_cap(is_cv_base=False) == MAX_IMPORT_FILES
    assert resolve_import_file_cap(is_cv_base=True) == MAX_CV_IMPORT_FILES
    assert MAX_CV_IMPORT_FILES > MAX_IMPORT_FILES


def test_deleting_document_cascades_candidate_profile(db_session, test_user, test_agent):
    doc = Document(filename="cv.pdf", content="x", user_id=test_user.id,
                   agent_id=test_agent.id, company_id=test_user.company_id, is_company_rag=True)
    db_session.add(doc)
    db_session.flush()
    doc_id = doc.id

    profile = CandidateProfile(document_id=doc_id, company_id=test_user.company_id,
                               full_name="Erasable Person", extraction_status="done")
    db_session.add(profile)
    db_session.flush()
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc_id).count() == 1

    # RGPD erasure: deleting the Document must cascade-remove its CandidateProfile.
    db_session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
    db_session.flush()
    db_session.expire_all()
    assert db_session.query(CandidateProfile).filter(CandidateProfile.document_id == doc_id).count() == 0
