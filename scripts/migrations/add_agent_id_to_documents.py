"""
Migration: Add agent_id column to documents table

This migration adds the agent_id foreign key column to the documents table
if it doesn't already exist.

Run this script manually or ensure it runs during deployment:
    python scripts/migrations/add_agent_id_to_documents.py
"""
import sys
import os
import logging

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from sqlalchemy import text
from database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_migration():
    """Run the migration to add agent_id column to documents table"""
    try:
        with engine.connect() as conn:
            # Check if agent_id column exists in documents table
            result = conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'documents' AND column_name = 'agent_id'
            """))

            if not result.fetchone():
                logger.info("Adding agent_id column to documents table...")
                conn.execute(text("""
                    ALTER TABLE documents
                    ADD COLUMN agent_id INTEGER REFERENCES agents(id)
                """))
                conn.commit()
                logger.info("✅ agent_id column added successfully")
            else:
                logger.info("✅ agent_id column already exists - no migration needed")

    except Exception as e:
        logger.error(f"❌ Migration failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Starting migration: add_agent_id_to_documents")
    run_migration()
    logger.info("Migration completed")
