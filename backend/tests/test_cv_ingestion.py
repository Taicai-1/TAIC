import rag_engine
from database import Document, DocumentChunk


def test_ingest_text_content_batches_embeddings(db_session, test_user, test_agent, monkeypatch):
    batch_calls = {"n": 0}

    def fake_batch(texts, batch_size=64):
        batch_calls["n"] += 1
        return [[0.1] * 1024 for _ in texts]

    # ingest_text_content imports get_embeddings_batch from mistral_embeddings.
    monkeypatch.setattr(rag_engine, "get_embeddings_batch", fake_batch, raising=False)
    monkeypatch.setattr("mistral_embeddings.get_embeddings_batch", fake_batch, raising=False)

    text = "Paragraph one. " * 50
    doc_id = rag_engine.ingest_text_content(
        text_content=text, filename="cv.txt", user_id=test_user.id,
        agent_id=test_agent.id, db=db_session, company_id=test_user.company_id,
    )

    doc = db_session.query(Document).filter(Document.id == doc_id).first()
    assert doc is not None
    chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert len(chunks) >= 1
    assert all(c.embedding_vec is not None for c in chunks)
    assert batch_calls["n"] >= 1            # used the batch path, not per-chunk
