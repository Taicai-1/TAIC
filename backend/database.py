import os
import logging
import secrets
import contextvars
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Boolean, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy import UniqueConstraint
from pgvector.sqlalchemy import Vector
from datetime import datetime, timedelta

# Tenant context variable — set by middleware, read by get_db
_current_company_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar('company_id', default=None)

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
def get_database_url():
    """Get database URL from environment or use default"""
    # First check if DATABASE_URL is explicitly provided
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Otherwise, build from components
    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        # Production: Cloud SQL — all DB credentials must come from env vars
        db_host = os.getenv("DB_HOST")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME")
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")

        if not all([db_host, db_name, db_user, db_password]):
            raise RuntimeError(
                "Production database credentials missing. "
                "Set DATABASE_URL or DB_HOST/DB_NAME/DB_USER/DB_PASSWORD environment variables."
            )

        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?sslmode=require"
    else:
        # Development: Local database (no SSL needed locally)
        logger.warning("DATABASE_URL not set — using local dev default. Do NOT use in production.")
        return "postgresql://raguser:ragpassword@localhost:5432/ragdb"

DATABASE_URL = get_database_url()

Base = declarative_base()

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), unique=True, nullable=False)
    neo4j_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Invite code for shareable join link
    invite_code = Column(String(32), unique=True, nullable=True)
    invite_code_enabled = Column(Boolean, default=True, nullable=False)

    # Encrypted org-level integration credentials
    _neo4j_uri = Column("neo4j_uri", Text, nullable=True)
    _neo4j_user = Column("neo4j_user", Text, nullable=True)
    _neo4j_password = Column("neo4j_password", Text, nullable=True)
    _notion_api_key = Column("notion_api_key", Text, nullable=True)
    _slack_bot_token = Column("slack_bot_token", Text, nullable=True)
    _slack_signing_secret = Column("slack_signing_secret", Text, nullable=True)
    slack_team_id = Column(String(64), nullable=True)

    # Encrypted property accessors
    @property
    def org_neo4j_uri(self):
        from encryption import decrypt_value
        return decrypt_value(self._neo4j_uri)

    @org_neo4j_uri.setter
    def org_neo4j_uri(self, value):
        from encryption import encrypt_value
        self._neo4j_uri = encrypt_value(value)

    @property
    def org_neo4j_user(self):
        from encryption import decrypt_value
        return decrypt_value(self._neo4j_user)

    @org_neo4j_user.setter
    def org_neo4j_user(self, value):
        from encryption import encrypt_value
        self._neo4j_user = encrypt_value(value)

    @property
    def org_neo4j_password(self):
        from encryption import decrypt_value
        return decrypt_value(self._neo4j_password)

    @org_neo4j_password.setter
    def org_neo4j_password(self, value):
        from encryption import encrypt_value
        self._neo4j_password = encrypt_value(value)

    @property
    def org_notion_api_key(self):
        from encryption import decrypt_value
        return decrypt_value(self._notion_api_key)

    @org_notion_api_key.setter
    def org_notion_api_key(self, value):
        from encryption import encrypt_value
        self._notion_api_key = encrypt_value(value)

    @property
    def org_slack_bot_token(self):
        from encryption import decrypt_value
        return decrypt_value(self._slack_bot_token)

    @org_slack_bot_token.setter
    def org_slack_bot_token(self, value):
        from encryption import encrypt_value
        self._slack_bot_token = encrypt_value(value)

    @property
    def org_slack_signing_secret(self):
        from encryption import decrypt_value
        return decrypt_value(self._slack_signing_secret)

    @org_slack_signing_secret.setter
    def org_slack_signing_secret(self, value):
        from encryption import encrypt_value
        self._slack_signing_secret = encrypt_value(value)

    users = relationship("User", back_populates="company")
    memberships = relationship("CompanyMembership", back_populates="company", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=True)  # nullable for OAuth users
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Email verification & OAuth
    email_verified = Column(Boolean, default=False, nullable=False)
    oauth_provider = Column(String(20), nullable=True)  # "google" or None

    # 2FA (TOTP) fields
    _totp_secret = Column("totp_secret", Text, nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    totp_backup_codes = Column(Text, nullable=True)  # JSON array of bcrypt-hashed backup codes
    totp_setup_completed_at = Column(DateTime, nullable=True)

    @property
    def totp_secret(self):
        from encryption import decrypt_value
        return decrypt_value(self._totp_secret)

    @totp_secret.setter
    def totp_secret(self, value):
        from encryption import encrypt_value
        self._totp_secret = encrypt_value(value)

    # Relations avec les documents et les agents
    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="owner", cascade="all, delete-orphan")
    company = relationship("Company", back_populates="users")
    memberships = relationship("CompanyMembership", back_populates="user", cascade="all, delete-orphan")

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(128), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)

    user = relationship("User")

class CompanyMembership(Base):
    __tablename__ = "company_memberships"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_user_company"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False, default="member")  # 'owner', 'admin', 'member'
    joined_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="memberships")
    company = relationship("Company", back_populates="memberships")


class CompanyInvitation(Base):
    __tablename__ = "company_invitations"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    email = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="member")
    token = Column(String(128), unique=True, nullable=False)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # 'pending', 'accepted', 'expired'
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    company = relationship("Company")
    invited_by = relationship("User")


class Agent(Base):
    __tablename__ = "agents"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    contexte = Column(Text, nullable=True)  # contexte pour ChatGPT
    biographie = Column(Text, nullable=True)  # biographie visible côté users
    profile_photo = Column(String(255), nullable=True)  # chemin ou URL de la photo de profil
    statut = Column(String(10), nullable=False, default="privé")  # 'public' ou 'privé'
    # type: 'conversationnel' | 'recherche_live'
    type = Column(String(32), nullable=False, default="conversationnel")
    # LLM provider: auto-calculated from type (mistral for conversationnel, perplexity for recherche_live)
    llm_provider = Column(String(32), nullable=True, default=None)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    embedding = Column(Text, nullable=True)  # Embedding du contexte (JSON ou array)

    created_at = Column(DateTime, default=datetime.utcnow)
    finetuned_model_id = Column(String(255), nullable=True)  # ID du modèle OpenAI fine-tuné
    _slack_bot_token = Column("slack_bot_token", Text, nullable=True)  # Encrypted token du bot Slack
    slack_team_id = Column(String(64), nullable=True)  # ID du workspace Slack associé à l'agent
    slack_bot_user_id = Column(String(64), nullable=True)  # Bot user ID (ex: U123ABC) pour identifier le bot dans une team
    _slack_signing_secret = Column("slack_signing_secret", Text, nullable=True)  # Encrypted Signing Secret

    @property
    def slack_bot_token(self):
        from encryption import decrypt_value
        return decrypt_value(self._slack_bot_token)

    @slack_bot_token.setter
    def slack_bot_token(self, value):
        from encryption import encrypt_value
        self._slack_bot_token = encrypt_value(value)

    @property
    def slack_signing_secret(self):
        from encryption import decrypt_value
        return decrypt_value(self._slack_signing_secret)

    @slack_signing_secret.setter
    def slack_signing_secret(self, value):
        from encryption import encrypt_value
        self._slack_signing_secret = encrypt_value(value)
    email_tags = Column(Text, nullable=True)  # JSON array de tags email ex: ["@finance", "@rh"]

    # Neo4j Knowledge Graph fields
    neo4j_enabled = Column(Boolean, default=False, nullable=False)
    neo4j_person_name = Column(String(200), nullable=True)
    neo4j_depth = Column(Integer, default=1, nullable=False)

    # Weekly Recap
    weekly_recap_enabled = Column(Boolean, default=False, nullable=False)

    # Relations
    owner = relationship("User", back_populates="agents")
    documents = relationship("Document", back_populates="agent", cascade="all, delete-orphan")


class AgentShare(Base):
    __tablename__ = "agent_shares"
    __table_args__ = (UniqueConstraint("agent_id", "user_id", name="uq_agent_share"),)

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    shared_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    can_edit = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")
    user = relationship("User", foreign_keys=[user_id])
    shared_by = relationship("User", foreign_keys=[shared_by_user_id])


class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    content = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)  # Documents peuvent être liés à un agent spécifique
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    created_at = Column(DateTime, default=datetime.utcnow)
    gcs_url = Column(String(512), nullable=True)  # URL du fichier dans le bucket GCS
    document_type = Column(String(20), nullable=False, default="rag", server_default="rag")  # 'rag' or 'traceability'
    notion_link_id = Column(Integer, ForeignKey("notion_links.id"), nullable=True, index=True)

    # Relations
    owner = relationship("User", back_populates="documents")
    agent = relationship("Agent", back_populates="documents")
    notion_link = relationship("NotionLink")
    # Relation avec les chunks
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation (critical for RAG)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # Legacy JSON string (kept for backward compat)
    embedding_vec = Column(Vector(1024), nullable=True)  # pgvector native column (Mistral 1024d)
    chunk_index = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relation avec le document
    document = relationship("Document", back_populates="chunks")


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    action_type = Column(String(100), nullable=False)
    params = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    agent = relationship("Agent")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    contexte = Column(Text, nullable=True)
    leader_agent_id = Column(Integer, nullable=False)
    # Store action agent ids as a JSON array string
    action_agent_ids = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")
    user = relationship("User")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    role = Column(String(20), nullable=False)  # 'user' ou 'agent'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    feedback = Column(String(10), nullable=True)  # 'like', 'dislike', ou None
    buffered = Column(Integer, default=0)  # 0 = non bufferisé, 1 = à bufferiser

    conversation = relationship("Conversation", back_populates="messages")


class NotionLink(Base):
    __tablename__ = "notion_links"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    notion_resource_id = Column(String(64), nullable=False)
    resource_type = Column(String(20), nullable=False)  # 'page' or 'database'
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")


class WeeklyRecapLog(Base):
    __tablename__ = "weekly_recap_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    status = Column(String(20), nullable=False)  # 'success', 'error', 'no_data'
    error_message = Column(Text, nullable=True)
    recap_content = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")
    user = relationship("User")


# Create database engine with connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    echo=False  # Set to True for SQL debugging
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Re-apply tenant context on every new transaction (including after commit/rollback).
# This ensures SET LOCAL survives across db.commit() + db.refresh() sequences.
@event.listens_for(SessionLocal, "after_begin")
def _set_tenant_on_begin(session, transaction, connection):
    cid = _current_company_id.get()
    if cid is not None:
        connection.execute(text(f"SET LOCAL app.company_id = '{int(cid)}'"))


def set_current_company_id(company_id: Optional[int]):
    """Set the tenant company_id for the current async context (called by middleware)."""
    _current_company_id.set(company_id)


def get_db():
    """Database dependency for FastAPI.
    Reads company_id from contextvars (set by tenant middleware) and
    executes SET LOCAL app.company_id for PostgreSQL RLS enforcement."""
    db = SessionLocal()
    try:
        cid = _current_company_id.get()
        if cid is not None:
            try:
                db.execute(text(f"SET LOCAL app.company_id = '{int(cid)}'"))
            except Exception as e:
                logger.warning(f"get_db: failed to SET LOCAL app.company_id={cid}: {e}")
        yield db
    finally:
        db.close()


def get_db_with_tenant(user_id: int, db: Session):
    """Set the RLS session variable for the current tenant.
    Call this at the start of any request that needs tenant isolation.
    Returns the user's company_id (or None for legacy users)."""
    user = db.query(User).filter(User.id == user_id).first()
    company_id = user.company_id if user else None
    if company_id is not None:
        db.execute(text(f"SET LOCAL app.company_id = '{company_id}'"))
    return company_id

def init_db():
    """Initialize database tables"""
    try:
        logger.info("Initializing database...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise e

def ensure_pgvector():
    """Enable the pgvector extension and add the embedding_vec column + HNSW index."""
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            logger.info("pgvector extension enabled")

            # Add embedding_vec column if missing
            try:
                conn.execute(text(
                    "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(1024)"
                ))
                conn.commit()
                logger.info("ensure_pgvector: embedding_vec column OK")
            except Exception as e:
                logger.warning(f"ensure_pgvector: embedding_vec column skipped: {e}")
                conn.rollback()

            # Create HNSW index for cosine distance if it doesn't exist
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_vec_hnsw "
                    "ON document_chunks USING hnsw (embedding_vec vector_cosine_ops)"
                ))
                conn.commit()
                logger.info("ensure_pgvector: HNSW index OK")
            except Exception as e:
                logger.warning(f"ensure_pgvector: HNSW index skipped: {e}")
                conn.rollback()
    except Exception as e:
        logger.error(f"ensure_pgvector failed: {e}")


def ensure_columns():
    """Add new columns to existing tables if they don't exist (safe migration)"""
    migrations = [
        ("agents", "weekly_recap_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("documents", "document_type", "VARCHAR(20) NOT NULL DEFAULT 'rag'"),
        # Company org-level columns
        ("companies", "invite_code", "VARCHAR(32) UNIQUE"),
        ("companies", "invite_code_enabled", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("companies", "neo4j_uri", "TEXT"),
        ("companies", "neo4j_user", "TEXT"),
        ("companies", "neo4j_password", "TEXT"),
        ("companies", "notion_api_key", "TEXT"),
        ("companies", "slack_bot_token", "TEXT"),
        ("companies", "slack_signing_secret", "TEXT"),
        ("companies", "slack_team_id", "VARCHAR(64)"),
        ("conversations", "user_id", "INTEGER REFERENCES users(id)"),
        ("agent_shares", "can_edit", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("documents", "notion_link_id", "INTEGER REFERENCES notion_links(id)"),
        # Email verification & OAuth
        ("users", "email_verified", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("users", "oauth_provider", "VARCHAR(20)"),
        # Tier 1 data sovereignty: company_id tenant isolation on all tenant-scoped tables
        ("agents", "company_id", "INTEGER REFERENCES companies(id)"),
        ("agent_shares", "company_id", "INTEGER REFERENCES companies(id)"),
        ("documents", "company_id", "INTEGER REFERENCES companies(id)"),
        ("document_chunks", "company_id", "INTEGER REFERENCES companies(id)"),
        ("agent_actions", "company_id", "INTEGER REFERENCES companies(id)"),
        ("teams", "company_id", "INTEGER REFERENCES companies(id)"),
        ("conversations", "company_id", "INTEGER REFERENCES companies(id)"),
        ("messages", "company_id", "INTEGER REFERENCES companies(id)"),
        ("notion_links", "company_id", "INTEGER REFERENCES companies(id)"),
        ("weekly_recap_logs", "company_id", "INTEGER REFERENCES companies(id)"),
    ]
    try:
        with engine.connect() as conn:
            for table, column, col_def in migrations:
                try:
                    conn.execute(text(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_def}"
                    ))
                    conn.commit()
                    logger.info(f"ensure_columns: {table}.{column} OK")
                except Exception as e:
                    logger.warning(f"ensure_columns: {table}.{column} skipped: {e}")
                    conn.rollback()
            # Make hashed_password nullable for OAuth users
            try:
                conn.execute(text(
                    "ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"
                ))
                conn.commit()
                logger.info("ensure_columns: users.hashed_password DROP NOT NULL OK")
            except Exception as e:
                logger.warning(f"ensure_columns: hashed_password nullable skipped: {e}")
                conn.rollback()
        logger.info("ensure_columns completed")
    except Exception as e:
        logger.error(f"ensure_columns failed: {e}")


def migrate_existing_company_memberships():
    """Create CompanyMembership records for existing users with company_id.
    The first user (by creation date) for each company becomes the owner."""
    try:
        db = SessionLocal()
        # Check if any memberships exist already
        existing_count = db.query(CompanyMembership).count()
        if existing_count > 0:
            logger.info("migrate_existing_company_memberships: memberships already exist, skipping")
            db.close()
            return

        # Get all users with a company_id, ordered by created_at
        users_with_company = (
            db.query(User)
            .filter(User.company_id.isnot(None))
            .order_by(User.created_at.asc())
            .all()
        )

        if not users_with_company:
            logger.info("migrate_existing_company_memberships: no users with company, skipping")
            db.close()
            return

        # Track which companies already have an owner assigned
        company_owners = set()

        for user in users_with_company:
            role = "member"
            if user.company_id not in company_owners:
                role = "owner"
                company_owners.add(user.company_id)

            membership = CompanyMembership(
                user_id=user.id,
                company_id=user.company_id,
                role=role,
                joined_at=user.created_at or datetime.utcnow()
            )
            db.add(membership)

        # Generate invite_code for companies that don't have one
        companies = db.query(Company).filter(Company.invite_code.is_(None)).all()
        for company in companies:
            company.invite_code = secrets.token_urlsafe(16)

        db.commit()
        logger.info(f"migrate_existing_company_memberships: created {len(users_with_company)} memberships, updated {len(companies)} invite codes")
        db.close()
    except Exception as e:
        logger.error(f"migrate_existing_company_memberships failed: {e}")


def test_connection():
    """Test database connection"""
    try:
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
