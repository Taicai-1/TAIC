import os
import logging
import secrets
import contextvars
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Date, ForeignKey, Boolean, text, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy import UniqueConstraint
from pgvector.sqlalchemy import Vector
from datetime import datetime, timedelta

# Tenant context variable — set by middleware, read by get_db
_current_company_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("company_id", default=None)

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
        # Development: require DATABASE_URL — no hardcoded credentials
        raise RuntimeError(
            "DATABASE_URL not set. Set DATABASE_URL=postgresql://user:password@host:5432/dbname in your .env file."
        )


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

    # Slash commands for prompt shortcuts
    slash_commands = Column(
        Text, nullable=True
    )  # JSON: [{"id":"uuid","command":"name","prompt":"text","agent_ids":[1,2]}]

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


class CompanyCreationRequest(Base):
    __tablename__ = "company_creation_requests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_name = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="pending")  # 'pending' | 'approved' | 'rejected'
    token = Column(String(128), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)
    decided_reason = Column(Text, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    company = relationship("Company", foreign_keys=[company_id])


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
    slack_bot_user_id = Column(
        String(64), nullable=True
    )  # Bot user ID (ex: U123ABC) pour identifier le bot dans une team
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

    # Template reference
    template_id = Column(Integer, ForeignKey("agent_templates.id", ondelete="SET NULL"), nullable=True)

    # Weekly Recap
    weekly_recap_enabled = Column(Boolean, default=False, nullable=False)
    weekly_recap_prompt = Column(Text, nullable=True)
    weekly_recap_recipients = Column(Text, nullable=True)  # JSON array of extra email recipients
    recap_frequency = Column(String(20), default="weekly", nullable=False)
    recap_hour = Column(Integer, default=9, nullable=False)

    # Date awareness: inject current date/time into system prompt
    date_awareness_enabled = Column(Boolean, default=False, nullable=False)

    # Company RAG: include the organization's shared documents in this agent's retrieval
    include_company_rag = Column(Boolean, default=False, nullable=False)

    # Actionnable plugins
    enabled_plugins = Column(Text, nullable=True)  # JSON array: ["google_docs", "gmail", ...]

    # Relations
    owner = relationship("User", back_populates="agents")
    documents = relationship("Document", back_populates="agent", cascade="all, delete-orphan")


class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)  # créateur
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    questions = relationship(
        "QuestionnaireQuestion",
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        order_by="QuestionnaireQuestion.position",
    )
    responses = relationship("QuestionnaireResponse", back_populates="questionnaire", cascade="all, delete-orphan")


class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False, default="open")  # open, single_choice, multiple_choice, rating
    options = Column(Text, nullable=True)  # JSON: ["Oui","Non"] ou {"min":1,"max":5}
    position = Column(Integer, nullable=False, default=0)
    required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    questionnaire = relationship("Questionnaire", back_populates="questions")


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"
    __table_args__ = (UniqueConstraint("questionnaire_id", "respondent_email", name="uq_response_questionnaire_email"),)

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    respondent_email = Column(String(255), nullable=False)
    respondent_name = Column(String(255), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, completed
    email_sent = Column(Boolean, default=False, nullable=False)
    invited_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    questionnaire = relationship("Questionnaire", back_populates="responses")
    answers = relationship("QuestionnaireAnswer", back_populates="response", cascade="all, delete-orphan")


class QuestionnaireAnswer(Base):
    __tablename__ = "questionnaire_answers"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(
        Integer, ForeignKey("questionnaire_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("questionnaire_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    answer_text = Column(Text, nullable=True)  # texte libre, JSON array pour multiple_choice, note en texte pour rating
    answered_at = Column(DateTime, default=datetime.utcnow)

    response = relationship("QuestionnaireResponse", back_populates="answers")
    question = relationship("QuestionnaireQuestion", foreign_keys=[question_id])


class UserGoogleToken(Base):
    __tablename__ = "user_google_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    _access_token = Column("access_token", Text, nullable=False)
    _refresh_token = Column("refresh_token", Text, nullable=False)
    token_expiry = Column(DateTime, nullable=False)
    granted_scopes = Column(Text, nullable=False)  # JSON array of scope strings
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", foreign_keys=[user_id])

    @property
    def access_token(self):
        from encryption import decrypt_value

        return decrypt_value(self._access_token)

    @access_token.setter
    def access_token(self, value):
        from encryption import encrypt_value

        self._access_token = encrypt_value(value)

    @property
    def refresh_token(self):
        from encryption import decrypt_value

        return decrypt_value(self._refresh_token)

    @refresh_token.setter
    def refresh_token(self, value):
        from encryption import encrypt_value

        self._refresh_token = encrypt_value(value)


class ActionExecution(Base):
    __tablename__ = "action_executions"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    plugin_name = Column(String(64), nullable=False)
    action_name = Column(String(64), nullable=False)
    action_params = Column(Text, nullable=False)  # JSON
    status = Column(String(32), nullable=False, default="pending_confirmation")
    result = Column(Text, nullable=True)  # JSON
    error_message = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    loop_state = Column(Text, nullable=True)  # JSON: serialized AgentLoopState for ReAct resume

    agent = relationship("Agent", foreign_keys=[agent_id])
    user = relationship("User", foreign_keys=[user_id])


class AgentTemplate(Base):
    __tablename__ = "agent_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=True)
    icon = Column(String(50), nullable=True)
    default_contexte = Column(Text, nullable=True)
    default_biographie = Column(Text, nullable=True)
    default_type = Column(String(32), nullable=False, default="conversationnel")
    default_email_tags = Column(Text, nullable=True)  # JSON array string
    default_neo4j_enabled = Column(Boolean, nullable=False, default=False)
    default_neo4j_person_name = Column(String(200), nullable=True)
    default_neo4j_depth = Column(Integer, nullable=False, default=1)
    default_weekly_recap_enabled = Column(Boolean, nullable=False, default=False)
    default_weekly_recap_prompt = Column(Text, nullable=True)
    default_weekly_recap_recipients = Column(Text, nullable=True)  # JSON array string
    default_recap_frequency = Column(String(20), nullable=False, default="weekly")
    default_recap_hour = Column(Integer, nullable=False, default=9)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)

    company = relationship("Company")
    creator = relationship("User")
    template_documents = relationship("AgentTemplateDocument", back_populates="template", cascade="all, delete-orphan")


class AgentTemplateDocument(Base):
    __tablename__ = "agent_template_documents"
    __table_args__ = (UniqueConstraint("template_id", "document_id", name="uq_template_document"),)

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("agent_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)

    template = relationship("AgentTemplate", back_populates="template_documents")
    document = relationship("Document")


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
    agent_id = Column(
        Integer, ForeignKey("agents.id"), nullable=True, index=True
    )  # Documents peuvent être liés à un agent spécifique
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    created_at = Column(DateTime, default=datetime.utcnow)
    gcs_url = Column(String(512), nullable=True)  # URL du fichier dans le bucket GCS
    document_type = Column(String(20), nullable=False, default="rag", server_default="rag")  # 'rag' or 'traceability'
    notion_link_id = Column(Integer, ForeignKey("notion_links.id"), nullable=True, index=True)
    drive_link_id = Column(Integer, ForeignKey("drive_links.id"), nullable=True, index=True)
    drive_file_id = Column(String(128), nullable=True, index=True)
    source_url = Column(String(2048), nullable=True)
    mission_id = Column(
        Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )  # Documents siloed to a mission (RAG sources)
    is_company_rag = Column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )  # Company-shared document (agent_id is NULL); included only when an agent opts in

    # Relations
    owner = relationship("User", back_populates="documents")
    agent = relationship("Agent", back_populates="documents")
    notion_link = relationship("NotionLink")
    drive_link = relationship("DriveLink")
    # Relation avec les chunks
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    company_id = Column(
        Integer, ForeignKey("companies.id"), nullable=True, index=True
    )  # Tenant isolation (critical for RAG)
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
    orchestration_prompt = Column(Text, nullable=True)


class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, default="member")  # "leader" or "member"
    specialization = Column(Text, nullable=True)
    auto_specialization = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("team_id", "agent_id", name="uq_team_member"),)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    mission_id = Column(
        Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True
    )  # Conversations scoped to a mission chat
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")
    user = relationship("User")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    role = Column(String(20), nullable=False)  # 'user' ou 'agent'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    feedback = Column(String(10), nullable=True)  # 'like', 'dislike', ou None
    buffered = Column(Integer, default=0)  # 0 = non bufferisé, 1 = à bufferiser
    sources_json = Column(Text, nullable=True)  # JSON array of RAG source chunks
    graph_data_json = Column(Text, nullable=True)  # JSON structured Neo4j graph data
    contributions_json = Column(Text, nullable=True)  # JSON array of team agent contributions
    action_proposal_json = Column(Text, nullable=True)  # JSON action proposal for actionnable agents

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


class DriveLink(Base):
    __tablename__ = "drive_links"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    drive_folder_id = Column(String(128), nullable=False)
    label = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")


class WeeklyRecapLog(Base):
    __tablename__ = "weekly_recap_logs"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    recap_id = Column(Integer, ForeignKey("recaps.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)  # Tenant isolation
    status = Column(String(20), nullable=False)  # 'success', 'error', 'no_data'
    error_message = Column(Text, nullable=True)
    recap_content = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent")
    user = relationship("User")
    recap = relationship("Recap")


class Recap(Base):
    __tablename__ = "recaps"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    frequency = Column(String(20), default="weekly", nullable=False)
    hour = Column(Integer, default=9, nullable=False)
    prompt = Column(Text, nullable=True)
    recipients = Column(Text, nullable=True)  # JSON array of email addresses
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = relationship("Agent")
    recap_documents = relationship("RecapDocument", back_populates="recap", cascade="all, delete-orphan")


class RecapDocument(Base):
    __tablename__ = "recap_documents"
    __table_args__ = (UniqueConstraint("recap_id", "document_id", name="uq_recap_document"),)

    id = Column(Integer, primary_key=True, index=True)
    recap_id = Column(Integer, ForeignKey("recaps.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    included = Column(Boolean, default=True, nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)

    recap = relationship("Recap", back_populates="recap_documents")
    document = relationship("Document")


class Mission(Base):
    __tablename__ = "missions"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)  # Tenant isolation
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Creator (private)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)  # Companion
    name = Column(String(255), nullable=False)
    objective = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active")  # active | archived
    recap_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    recap_weekday = Column(Integer, nullable=False, default=0, server_default="0")  # 0=Monday .. 6=Sunday
    recap_hour = Column(Integer, nullable=False, default=8, server_default="8")  # Europe/Paris
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = relationship("Agent")
    events = relationship(
        "MissionEvent",
        back_populates="mission",
        cascade="all, delete-orphan",
        order_by="MissionEvent.event_date",
    )
    recaps = relationship("MissionRecap", back_populates="mission", cascade="all, delete-orphan")


class MissionEvent(Base):
    __tablename__ = "mission_events"

    id = Column(Integer, primary_key=True, index=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    event_date = Column(Date, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source = Column(String(10), nullable=False, default="upload", server_default="upload")  # upload | manual
    created_at = Column(DateTime, default=datetime.utcnow)

    mission = relationship("Mission", back_populates="events")


class MissionRecap(Base):
    __tablename__ = "mission_recaps"

    id = Column(Integer, primary_key=True, index=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    content = Column(Text, nullable=True)
    status = Column(String(20), nullable=False)  # success | error | no_data
    error_message = Column(Text, nullable=True)
    email_sent = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    trigger = Column(String(10), nullable=False, default="scheduled", server_default="scheduled")  # scheduled | manual
    created_at = Column(DateTime, default=datetime.utcnow)

    mission = relationship("Mission", back_populates="recaps")


class RoutineReport(Base):
    __tablename__ = "routine_reports"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(20), nullable=False, index=True)  # health, ci_cd, security, billing
    status = Column(String(10), nullable=False)  # pass, warn, fail
    data = Column(Text, nullable=False)  # JSON string (use json.dumps/loads)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# Create database engine with connection pooling (env-configurable for Cloud Run scaling)
engine = create_engine(
    DATABASE_URL,
    pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    pool_pre_ping=True,
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "600")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    echo=False,  # Set to True for SQL debugging
)
logger.info(
    "DB pool: size=%s overflow=%s recycle=%ss timeout=%ss",
    engine.pool.size(),
    engine.pool._max_overflow,
    engine.pool._recycle,
    engine.pool._timeout,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Re-apply tenant context on every new transaction (including after commit/rollback).
# This ensures SET LOCAL survives across db.commit() + db.refresh() sequences.
@event.listens_for(SessionLocal, "after_begin")
def _set_tenant_on_begin(session, transaction, connection):
    cid = _current_company_id.get()
    if cid is not None:
        connection.execute(text("SET LOCAL app.company_id = :cid"), {"cid": str(int(cid))})


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
                db.execute(text("SET LOCAL app.company_id = :cid"), {"cid": str(int(cid))})
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
        db.execute(text("SET LOCAL app.company_id = :cid"), {"cid": str(int(company_id))})
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

            # Check if embedding_vec column already exists before ALTER TABLE
            has_col = False
            try:
                row = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='document_chunks' AND column_name='embedding_vec'"
                    )
                ).first()
                has_col = row is not None
            except Exception:
                conn.rollback()

            if not has_col:
                try:
                    conn.execute(
                        text("ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(1024)")
                    )
                    conn.commit()
                    logger.info("ensure_pgvector: embedding_vec column OK")
                except Exception as e:
                    logger.warning(f"ensure_pgvector: embedding_vec column skipped: {e}")
                    conn.rollback()

            # Check if HNSW index already exists before CREATE INDEX
            has_idx = False
            try:
                row = conn.execute(
                    text("SELECT 1 FROM pg_indexes WHERE indexname='idx_chunks_embedding_vec_hnsw'")
                ).first()
                has_idx = row is not None
            except Exception:
                conn.rollback()

            if not has_idx:
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_vec_hnsw "
                            "ON document_chunks USING hnsw (embedding_vec vector_cosine_ops)"
                        )
                    )
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
        ("agents", "weekly_recap_prompt", "TEXT"),
        ("agents", "weekly_recap_recipients", "TEXT"),
        ("agents", "recap_frequency", "VARCHAR(20) NOT NULL DEFAULT 'weekly'"),
        ("agents", "recap_hour", "INTEGER NOT NULL DEFAULT 9"),
        ("documents", "document_type", "VARCHAR(20) NOT NULL DEFAULT 'rag'"),
        ("documents", "source_url", "VARCHAR(2048)"),
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
        ("companies", "slash_commands", "TEXT"),
        ("conversations", "user_id", "INTEGER REFERENCES users(id)"),
        ("agent_shares", "can_edit", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("documents", "notion_link_id", "INTEGER REFERENCES notion_links(id)"),
        ("documents", "drive_link_id", "INTEGER REFERENCES drive_links(id)"),
        ("documents", "drive_file_id", "VARCHAR(128)"),
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
        ("weekly_recap_logs", "recap_id", "INTEGER REFERENCES recaps(id)"),
        ("messages", "sources_json", "TEXT"),
        ("messages", "graph_data_json", "TEXT"),
        ("messages", "action_proposal_json", "TEXT"),
        # Companion templates
        ("agents", "template_id", "INTEGER REFERENCES agent_templates(id) ON DELETE SET NULL"),
        ("agent_templates", "default_email_tags", "TEXT"),
        ("agent_templates", "default_neo4j_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("agent_templates", "default_neo4j_person_name", "VARCHAR(200)"),
        ("agent_templates", "default_neo4j_depth", "INTEGER NOT NULL DEFAULT 1"),
        ("agent_templates", "default_weekly_recap_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("agent_templates", "default_weekly_recap_prompt", "TEXT"),
        ("agent_templates", "default_weekly_recap_recipients", "TEXT"),
        ("agent_templates", "default_recap_frequency", "VARCHAR(20) NOT NULL DEFAULT 'weekly'"),
        ("agent_templates", "default_recap_hour", "INTEGER NOT NULL DEFAULT 9"),
        # Team orchestration
        ("teams", "orchestration_prompt", "TEXT"),
        ("messages", "contributions_json", "TEXT"),
        # Actionnable agents
        ("agents", "enabled_plugins", "TEXT"),
        ("action_executions", "loop_state", "TEXT"),
        # Date awareness
        ("agents", "date_awareness_enabled", "BOOLEAN NOT NULL DEFAULT FALSE"),
        # Missions
        ("documents", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        ("conversations", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        # Company RAG
        ("documents", "is_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("agents", "include_company_rag", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ]
    try:
        with engine.connect() as conn:
            # Prevent hanging on table locks during startup
            conn.execute(text("SET lock_timeout = '5s'"))
            conn.execute(text("SET statement_timeout = '30s'"))
            # Pre-fetch existing columns to avoid unnecessary ALTER TABLE locks
            existing = set()
            try:
                rows = conn.execute(
                    text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
                ).fetchall()
                existing = {(r[0], r[1]) for r in rows}
            except Exception:
                pass  # Fall back to ALTER TABLE IF NOT EXISTS

            for table, column, col_def in migrations:
                if (table, column) in existing:
                    continue
                try:
                    stmt = "ALTER TABLE " + table + " ADD COLUMN IF NOT EXISTS " + column + " " + col_def
                    conn.execute(text(stmt))
                    conn.commit()
                    logger.info(f"ensure_columns: {table}.{column} OK")
                except Exception as e:
                    logger.warning(f"ensure_columns: {table}.{column} skipped: {e}")
                    conn.rollback()
            # Make hashed_password nullable for OAuth users (skip if already nullable)
            is_nullable = True
            try:
                row = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name='users' AND column_name='hashed_password'"
                    )
                ).first()
                is_nullable = row is not None and row[0] == "YES"
            except Exception:
                conn.rollback()

            if not is_nullable:
                try:
                    conn.execute(text("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL"))
                    conn.commit()
                    logger.info("ensure_columns: users.hashed_password DROP NOT NULL OK")
                except Exception as e:
                    logger.warning(f"ensure_columns: hashed_password nullable skipped: {e}")
                    conn.rollback()
        logger.info("ensure_columns completed")
    except Exception as e:
        logger.error(f"ensure_columns failed: {e}")


def ensure_rls_policies():
    """Create RLS bypass policies and fix tenant_isolation policies.

    1. Adds a 'service_bypass' policy on tenant-scoped tables that allows
       SELECT when the session variable app.service_bypass = 'true'.
    2. Recreates 'tenant_isolation' policies with NULLIF to handle empty
       string from current_setting (prevents ''::int cast errors).
    """
    tables = [
        "agents",
        "agent_shares",
        "documents",
        "document_chunks",
        "agent_actions",
        "teams",
        "conversations",
        "messages",
        "notion_links",
        "weekly_recap_logs",
        "recaps",
        "recap_documents",
        # Questionnaire tables (questionnaires, questionnaire_questions/responses/
        # answers) are intentionally ABSENT: RLS is never enabled on them because
        # the public token endpoints (/questionnaire/{token}) run without a tenant
        # session var. Tenant isolation is app-level (company_id filters in
        # routers/automations.py). Do not add them here without reworking the
        # public endpoints first.
        # Mission tables (missions, mission_events, mission_recaps) are also
        # intentionally ABSENT: the recap scheduler INSERTs mission_recaps from a
        # background session that has no app.company_id set, which a tenant_isolation
        # WITH CHECK policy would reject (service_bypass only covers SELECT). Tenant
        # isolation is app-level and stricter here — every mission query in
        # routers/missions.py filters BOTH company_id AND the creator user_id
        # (private-to-creator). Mission documents live in `documents`, which keeps
        # its RLS. Do not add mission tables here without making the scheduler set a
        # tenant/bypass context for its writes first.
    ]
    try:
        with engine.connect() as conn:
            # Set lock_timeout early to prevent blocking on any DDL
            conn.execute(text("SET lock_timeout = '5s'"))

            for table in tables:
                # service_bypass policy
                try:
                    stmt = (
                        "CREATE POLICY service_bypass ON "
                        + table
                        + " FOR SELECT USING (current_setting('app.service_bypass', true) = 'true')"
                    )
                    conn.execute(text(stmt))
                    conn.commit()
                    print(f"ensure_rls_policies: service_bypass on {table} created", flush=True)
                except Exception as e:
                    conn.rollback()
                    if "already exists" in str(e):
                        pass  # expected
                    else:
                        print(f"ensure_rls_policies: {table} skipped: {e}", flush=True)

            # Fix tenant_isolation policies: use NULLIF to prevent ''::int error.
            # Check if already fixed by looking at policy definition.
            needs_fix = False
            try:
                row = conn.execute(
                    text(
                        "SELECT polqual::text FROM pg_policy "
                        "WHERE polname = 'tenant_isolation' AND polrelid = 'agents'::regclass"
                    )
                ).first()
                needs_fix = row is not None and "nullif" not in (row[0] or "").lower()
            except Exception:
                conn.rollback()

            if needs_fix:
                print("ensure_rls_policies: fixing tenant_isolation policies (adding NULLIF)", flush=True)
                try:
                    for table in tables:
                        drop_stmt = "DROP POLICY IF EXISTS tenant_isolation ON " + table
                        conn.execute(text(drop_stmt))
                        create_stmt = (
                            "CREATE POLICY tenant_isolation ON " + table + " "
                            "USING (company_id = NULLIF(current_setting('app.company_id', true), '')::int) "
                            "WITH CHECK (company_id = NULLIF(current_setting('app.company_id', true), '')::int)"
                        )
                        conn.execute(text(create_stmt))
                    conn.commit()
                    print("ensure_rls_policies: tenant_isolation policies fixed", flush=True)
                except Exception as e:
                    conn.rollback()
                    print(
                        f"ensure_rls_policies: tenant_isolation fix failed (will retry next startup): {e}", flush=True
                    )
            else:
                print("ensure_rls_policies: tenant_isolation already OK", flush=True)

        print("ensure_rls_policies completed", flush=True)
    except Exception as e:
        print(f"ensure_rls_policies failed: {e}", flush=True)


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
        users_with_company = db.query(User).filter(User.company_id.isnot(None)).order_by(User.created_at.asc()).all()

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
                user_id=user.id, company_id=user.company_id, role=role, joined_at=user.created_at or datetime.utcnow()
            )
            db.add(membership)

        # Generate invite_code for companies that don't have one
        companies = db.query(Company).filter(Company.invite_code.is_(None)).all()
        for company in companies:
            company.invite_code = secrets.token_urlsafe(16)

        db.commit()
        logger.info(
            f"migrate_existing_company_memberships: created {len(users_with_company)} memberships, updated {len(companies)} invite codes"
        )
        db.close()
    except Exception as e:
        logger.error(f"migrate_existing_company_memberships failed: {e}")


def migrate_existing_recaps():
    """Create Recap entities for agents that have weekly_recap_enabled=True but no Recap entities yet."""
    try:
        db = SessionLocal()
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        migrated = 0

        for agent in agents:
            existing = db.query(Recap).filter(Recap.agent_id == agent.id).count()
            if existing > 0:
                continue

            recap = Recap(
                agent_id=agent.id,
                company_id=agent.company_id,
                name="Recap principal",
                enabled=True,
                frequency=agent.recap_frequency or "weekly",
                hour=agent.recap_hour if agent.recap_hour is not None else 9,
                prompt=agent.weekly_recap_prompt,
                recipients=agent.weekly_recap_recipients,
            )
            db.add(recap)
            db.commit()
            db.refresh(recap)

            # Associate all existing traceability docs
            trace_docs = (
                db.query(Document).filter(Document.agent_id == agent.id, Document.document_type == "traceability").all()
            )
            for doc in trace_docs:
                rd = RecapDocument(
                    recap_id=recap.id,
                    document_id=doc.id,
                    included=True,
                    company_id=agent.company_id,
                )
                db.add(rd)

            db.commit()
            migrated += 1

        logger.info(f"migrate_existing_recaps: migrated {migrated} agents")
        db.close()
    except Exception as e:
        logger.error(f"migrate_existing_recaps failed: {e}")


def migrate_teams_to_members():
    """Migrate existing teams from JSON action_agent_ids to team_members table.
    Idempotent: skips if team_members already has entries."""
    import json as _json

    try:
        db = SessionLocal()
        existing_count = db.query(TeamMember).count()
        if existing_count > 0:
            logger.info("migrate_teams_to_members: team_members already populated, skipping")
            db.close()
            return

        teams = db.query(Team).all()
        if not teams:
            logger.info("migrate_teams_to_members: no teams to migrate")
            db.close()
            return

        for team in teams:
            # Migrate leader
            if team.leader_agent_id:
                leader_member = TeamMember(
                    team_id=team.id,
                    agent_id=team.leader_agent_id,
                    role="leader",
                    position=0,
                    company_id=team.company_id,
                )
                db.add(leader_member)

            # Migrate action agents
            action_ids = []
            if team.action_agent_ids:
                try:
                    action_ids = (
                        _json.loads(team.action_agent_ids)
                        if isinstance(team.action_agent_ids, str)
                        else team.action_agent_ids
                    )
                except (ValueError, TypeError):
                    action_ids = []

            for i, aid in enumerate(action_ids):
                member = TeamMember(
                    team_id=team.id,
                    agent_id=int(aid),
                    role="member",
                    position=i + 1,
                    company_id=team.company_id,
                )
                db.add(member)

        db.commit()
        logger.info(f"migrate_teams_to_members: migrated {len(teams)} teams")
        db.close()
    except Exception as e:
        logger.error(f"migrate_teams_to_members failed: {e}")


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
