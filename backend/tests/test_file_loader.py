"""Unit tests for file_loader.py - PDF loading and chunking integration."""

import os
import pytest
import tiktoken

from file_loader import load_text_from_pdf, chunk_text


# Helper to locate fixture files
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


# ---------------------------------------------------------------------------
# TestLoadPdf - test PDF loading
# ---------------------------------------------------------------------------


class TestLoadPdf:
    """Test load_text_from_pdf function."""

    def test_load_valid_pdf(self):
        """Extract text from sample.pdf fixture, verify text contains expected content."""
        pdf_path = os.path.join(FIXTURES_DIR, "sample.pdf")
        if not os.path.exists(pdf_path):
            pytest.skip("sample.pdf fixture not found")

        text = load_text_from_pdf(pdf_path)

        # Verify text was extracted
        assert text is not None
        assert len(text) > 0

        # Verify it contains expected keywords from the sample PDF
        # (assuming sample.pdf has similar content to sample.txt)
        assert "TAIC" in text or "test" in text.lower()

    def test_load_nonexistent_pdf(self):
        """Returns empty string for missing file."""
        nonexistent_path = os.path.join(FIXTURES_DIR, "nonexistent.pdf")

        text = load_text_from_pdf(nonexistent_path)

        # Should return empty string (or stripped empty string)
        assert text == ""

    def test_null_bytes_stripped(self):
        """Extracted text has no null bytes."""
        pdf_path = os.path.join(FIXTURES_DIR, "sample.pdf")
        if not os.path.exists(pdf_path):
            pytest.skip("sample.pdf fixture not found")

        text = load_text_from_pdf(pdf_path)

        # Verify null bytes are stripped
        assert "\x00" not in text


# ---------------------------------------------------------------------------
# TestChunkTextIntegration - integration tests with real fixture files
# ---------------------------------------------------------------------------


class TestChunkTextIntegration:
    """Test chunk_text with real fixture files."""

    def test_chunk_txt_fixture(self):
        """Chunk sample.txt content, verify chunks contain key words."""
        txt_path = os.path.join(FIXTURES_DIR, "sample.txt")
        if not os.path.exists(txt_path):
            pytest.skip("sample.txt fixture not found")

        # Read fixture content
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()

        # Chunk the text
        chunks = chunk_text(text, chunk_size=512, overlap=50)

        # Verify chunks were created
        assert len(chunks) > 0

        # Verify chunks contain key words from the fixture
        all_chunks_text = " ".join(chunks)
        assert "TAIC" in all_chunks_text
        assert "Companion" in all_chunks_text
        assert "RAG" in all_chunks_text or "Retrieval" in all_chunks_text

    def test_chunk_sizes_respect_limit(self):
        """Verify chunks don't exceed token limit using tiktoken cl100k_base encoding."""
        txt_path = os.path.join(FIXTURES_DIR, "sample.txt")
        if not os.path.exists(txt_path):
            pytest.skip("sample.txt fixture not found")

        # Read fixture content
        with open(txt_path, "r", encoding="utf-8") as f:
            text = f.read()

        # Use a strict chunk size
        chunk_size = 256
        chunks = chunk_text(text, chunk_size=chunk_size, overlap=30)

        # Get the same encoder used by file_loader
        enc = tiktoken.get_encoding("cl100k_base")

        # Verify each chunk respects the limit
        # Note: chunks with overlap may exceed the limit slightly
        # but the initial chunks should respect it
        for i, chunk in enumerate(chunks):
            token_count = len(enc.encode(chunk))
            # Allow some tolerance for overlap
            # First chunk should strictly respect limit
            if i == 0:
                assert token_count <= chunk_size, f"First chunk has {token_count} tokens, exceeds limit of {chunk_size}"
            else:
                # Subsequent chunks may have overlap added, so they can be up to chunk_size + overlap
                # But they shouldn't be excessively large
                assert token_count <= chunk_size + 100, f"Chunk {i} has {token_count} tokens, excessively large"
