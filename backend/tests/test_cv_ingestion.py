import rag_engine
from database import Document, DocumentChunk


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
