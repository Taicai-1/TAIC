"""Model factories for test data creation."""

import factory
from database import (
    Base,
    User,
    Agent,
    Document,
    DocumentChunk,
    Conversation,
    Message,
    Company,
    CompanyMembership,
    AgentShare,
)
from auth import hash_password


class CompanyFactory(factory.Factory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"company-{n}")
    invite_code = factory.LazyFunction(lambda: __import__("secrets").token_urlsafe(16))
    invite_code_enabled = True


class UserFactory(factory.Factory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"testuser{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@test.com")
    hashed_password = factory.LazyFunction(lambda: hash_password("Test1234"))
    email_verified = True
    totp_enabled = False


class AgentFactory(factory.Factory):
    class Meta:
        model = Agent

    name = factory.Sequence(lambda n: f"agent-{n}")
    contexte = "Tu es un assistant de test."
    biographie = "Agent de test"
    statut = "public"
    type = "conversationnel"
    llm_provider = "mistral"


class DocumentFactory(factory.Factory):
    class Meta:
        model = Document

    filename = factory.Sequence(lambda n: f"doc-{n}.txt")
    content = "This is test document content for RAG."
    document_type = "rag"


class DocumentChunkFactory(factory.Factory):
    class Meta:
        model = DocumentChunk

    chunk_text = "This is a test chunk of text for embedding."
    chunk_index = factory.Sequence(lambda n: n)


class ConversationFactory(factory.Factory):
    class Meta:
        model = Conversation

    title = factory.Sequence(lambda n: f"conversation-{n}")


class MessageFactory(factory.Factory):
    class Meta:
        model = Message

    role = "user"
    content = "Test message content"


class AgentShareFactory(factory.Factory):
    class Meta:
        model = AgentShare

    can_edit = False


class CompanyMembershipFactory(factory.Factory):
    class Meta:
        model = CompanyMembership

    role = "member"
