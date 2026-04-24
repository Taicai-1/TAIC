-- Add source_url to documents for URL-based RAG sources
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2048);
