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
    AgentTemplate,
    AgentTemplateDocument,
    Team,
    TeamMember,
    ActionExecution,
    UserGoogleToken,
    Questionnaire,
    QuestionnaireQuestion,
    QuestionnaireResponse,
    QuestionnaireAnswer,
    Mission,
    MissionEvent,
    AgentFolder,
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
    statut = "privé"
    type = "conversationnel"
    llm_provider = "mistral"


class AgentFolderFactory(factory.Factory):
    class Meta:
        model = AgentFolder

    name = factory.Sequence(lambda n: f"folder-{n}")
    is_active = True


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


class AgentTemplateFactory(factory.Factory):
    class Meta:
        model = AgentTemplate

    name = factory.Sequence(lambda n: f"template-{n}")
    description = "Test template description"
    category = "Tech"
    icon = "Monitor"
    default_contexte = "Tu es un expert technique."
    default_biographie = "Assistant technique"
    default_type = "conversationnel"


class TeamFactory(factory.Factory):
    class Meta:
        model = Team

    name = factory.Sequence(lambda n: f"team-{n}")
    contexte = "Equipe de test"


class TeamMemberFactory(factory.Factory):
    class Meta:
        model = TeamMember

    role = "member"
    specialization = None
    position = 0


class AgentTemplateDocumentFactory(factory.Factory):
    class Meta:
        model = AgentTemplateDocument


class ActionExecutionFactory(factory.Factory):
    class Meta:
        model = ActionExecution

    plugin_name = "google_docs"
    action_name = "create_doc"
    action_params = '{"title": "Test Doc"}'
    status = "pending_confirmation"


class UserGoogleTokenFactory(factory.Factory):
    class Meta:
        model = UserGoogleToken

    _access_token = "test-access-token"
    _refresh_token = "test-refresh-token"
    token_expiry = factory.LazyFunction(
        lambda: __import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(hours=1)
    )
    granted_scopes = '["https://www.googleapis.com/auth/documents"]'


class QuestionnaireFactory(factory.Factory):
    class Meta:
        model = Questionnaire

    title = factory.Sequence(lambda n: f"questionnaire-{n}")
    description = "Questionnaire de test"


class QuestionnaireQuestionFactory(factory.Factory):
    class Meta:
        model = QuestionnaireQuestion

    question_text = "Quelle est votre couleur préférée ?"
    question_type = "open"
    options = None
    position = 0
    required = True


class QuestionnaireResponseFactory(factory.Factory):
    class Meta:
        model = QuestionnaireResponse

    respondent_email = factory.Sequence(lambda n: f"respondent{n}@test.com")
    token = factory.LazyFunction(lambda: __import__("secrets").token_urlsafe(32))
    status = "pending"
    email_sent = False


class QuestionnaireAnswerFactory(factory.Factory):
    class Meta:
        model = QuestionnaireAnswer

    answer_text = "Bleu"


class MissionFactory(factory.Factory):
    class Meta:
        model = Mission

    name = factory.Sequence(lambda n: f"mission-{n}")
    objective = "Réussir le lancement du produit."
    status = "active"
    recap_enabled = True
    recap_weekday = 0
    recap_hour = 8


class MissionEventFactory(factory.Factory):
    class Meta:
        model = MissionEvent

    title = factory.Sequence(lambda n: f"event-{n}")
    description = "Détail de l'évènement."
    source = "upload"
