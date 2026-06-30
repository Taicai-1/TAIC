import rag_engine
from database import Document, DocumentChunk, CandidateProfile, CompanyFolder
from cv_extraction import upsert_candidate_profile


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
