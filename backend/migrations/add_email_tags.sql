-- Migration: Add email_tags column to agents table
-- Date: 2025-01-16
-- Description: Permet de configurer des tags email pour le routage automatique des emails vers les companions

-- Ajouter la colonne email_tags à la table agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS email_tags TEXT;

-- Exemple de mise à jour pour un agent existant:
-- UPDATE agents SET email_tags = '["@finance", "@comptabilite"]' WHERE id = 1;

-- Index pour améliorer les recherches sur les tags (optionnel)
-- CREATE INDEX IF NOT EXISTS idx_agents_email_tags ON agents USING gin (email_tags);
