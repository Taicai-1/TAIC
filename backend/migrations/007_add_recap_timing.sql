-- Add recap timing customization columns to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_frequency VARCHAR(20) NOT NULL DEFAULT 'weekly';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_hour INTEGER NOT NULL DEFAULT 9;
