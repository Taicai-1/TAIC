"""
Migration: Add 2FA (TOTP) fields to users table

- ALTER TABLE users ADD totp_secret (Text, nullable) - encrypted TOTP secret
- ALTER TABLE users ADD totp_enabled (Boolean, default FALSE)
- ALTER TABLE users ADD totp_backup_codes (Text, nullable) - JSON array of hashed backup codes
- ALTER TABLE users ADD totp_setup_completed_at (DateTime, nullable)

Run: python scripts/migrations/add_2fa_fields.py
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


def run_migration():
    try:
        with engine.connect() as conn:
            # 1. Add totp_secret to users
            if not column_exists(conn, "users", "totp_secret"):
                logger.info("Adding totp_secret to users...")
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN totp_secret TEXT
                """))
                conn.commit()
                logger.info("totp_secret added to users")
            else:
                logger.info("users.totp_secret already exists")

            # 2. Add totp_enabled to users
            if not column_exists(conn, "users", "totp_enabled"):
                logger.info("Adding totp_enabled to users...")
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT FALSE
                """))
                conn.commit()
                logger.info("totp_enabled added to users")
            else:
                logger.info("users.totp_enabled already exists")

            # 3. Add totp_backup_codes to users
            if not column_exists(conn, "users", "totp_backup_codes"):
                logger.info("Adding totp_backup_codes to users...")
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN totp_backup_codes TEXT
                """))
                conn.commit()
                logger.info("totp_backup_codes added to users")
            else:
                logger.info("users.totp_backup_codes already exists")

            # 4. Add totp_setup_completed_at to users
            if not column_exists(conn, "users", "totp_setup_completed_at"):
                logger.info("Adding totp_setup_completed_at to users...")
                conn.execute(text("""
                    ALTER TABLE users
                    ADD COLUMN totp_setup_completed_at TIMESTAMP
                """))
                conn.commit()
                logger.info("totp_setup_completed_at added to users")
            else:
                logger.info("users.totp_setup_completed_at already exists")

            logger.info("All 2FA migrations completed successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


if __name__ == "__main__":
    logger.info("Starting migration: add_2fa_fields")
    run_migration()
    logger.info("Migration completed")
