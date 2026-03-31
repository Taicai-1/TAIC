"""
Migration: Add Neo4j Knowledge Graph fields

- CREATE TABLE companies (id, name, neo4j_enabled, created_at)
- ALTER TABLE users ADD company_id FK
- ALTER TABLE agents ADD neo4j_enabled, neo4j_person_name, neo4j_depth

Run: python scripts/migrations/add_neo4j_fields.py
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


def column_exists(conn, table, column):
    result = conn.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = :table AND column_name = :column
    """), {"table": table, "column": column})
    return result.fetchone() is not None


def table_exists(conn, table):
    result = conn.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_name = :table AND table_schema = 'public'
    """), {"table": table})
    return result.fetchone() is not None


def run_migration():
    try:
        with engine.connect() as conn:
            # 1. Create companies table
            if not table_exists(conn, "companies"):
                logger.info("Creating companies table...")
                conn.execute(text("""
                    CREATE TABLE companies (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(200) UNIQUE NOT NULL,
                        neo4j_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                conn.commit()
                logger.info("companies table created")
            else:
                logger.info("companies table already exists")

            # 2. Add company_id to users
            if not column_exists(conn, "users", "company_id"):
                logger.info("Adding company_id to users...")
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN company_id INTEGER REFERENCES companies(id)
                """))
                conn.commit()
                logger.info("company_id added to users")
            else:
                logger.info("users.company_id already exists")

            # 3. Add neo4j fields to agents
            if not column_exists(conn, "agents", "neo4j_enabled"):
                logger.info("Adding neo4j_enabled to agents...")
                conn.execute(text("""
                    ALTER TABLE agents
                    ADD COLUMN neo4j_enabled BOOLEAN NOT NULL DEFAULT FALSE
                """))
                conn.commit()
                logger.info("neo4j_enabled added to agents")
            else:
                logger.info("agents.neo4j_enabled already exists")

            if not column_exists(conn, "agents", "neo4j_person_name"):
                logger.info("Adding neo4j_person_name to agents...")
                conn.execute(text("""
                    ALTER TABLE agents
                    ADD COLUMN neo4j_person_name VARCHAR(200)
                """))
                conn.commit()
                logger.info("neo4j_person_name added to agents")
            else:
                logger.info("agents.neo4j_person_name already exists")

            if not column_exists(conn, "agents", "neo4j_depth"):
                logger.info("Adding neo4j_depth to agents...")
                conn.execute(text("""
                    ALTER TABLE agents
                    ADD COLUMN neo4j_depth INTEGER NOT NULL DEFAULT 1
                """))
                conn.commit()
                logger.info("neo4j_depth added to agents")
            else:
                logger.info("agents.neo4j_depth already exists")

            logger.info("All Neo4j migrations completed successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Starting migration: add_neo4j_fields")
    run_migration()
    logger.info("Migration completed")
