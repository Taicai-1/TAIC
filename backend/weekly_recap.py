"""
Weekly Recap Module
Generates and sends weekly AI-powered recap emails per agent.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database import Agent, Document, Message, Conversation, User, WeeklyRecapLog, NotionLink
from openai_client import get_chat_response
from email_service import generate_recap_html, send_recap_email

logger = logging.getLogger(__name__)


def get_model_id_for_agent(agent: Agent) -> str:
    """Resolve the model_id string based on the agent's type."""
    atype = getattr(agent, "type", "conversationnel")
    if atype == "recherche_live":
        return "perplexity:sonar"
    else:
        return "mistral:mistral-large-latest"


FREQUENCY_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}


def get_days_back(agent: Agent) -> int:
    """Return the number of days of data to fetch based on agent recap frequency."""
    freq = getattr(agent, "recap_frequency", "weekly")
    return FREQUENCY_DAYS.get(freq, 7)


def fetch_weekly_messages(agent_id: int, db: Session, days_back: int = 7) -> list[dict]:
    """Fetch all messages from the last N days for a given agent."""
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    conversations = db.query(Conversation).filter(Conversation.agent_id == agent_id).all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]
    messages = (
        db.query(Message)
        .filter(Message.conversation_id.in_(conv_ids), Message.timestamp >= cutoff)
        .order_by(Message.timestamp.asc())
        .all()
    )

    return [{"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()} for m in messages]


def fetch_traceability_documents(agent_id: int, db: Session, days_back: int = 7) -> list[dict]:
    """Fetch content of traceability documents imported in the last N days for a given agent."""
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    docs = (
        db.query(Document)
        .filter(
            Document.agent_id == agent_id,
            Document.document_type == "traceability",
            Document.created_at >= cutoff,
        )
        .all()
    )

    return [{"filename": d.filename, "content": (d.content or "")[:10000]} for d in docs]


def fetch_recap_traceability_documents(recap_id: int, db: Session, days_back: int = 7) -> list[dict]:
    """Fetch traceability documents for a specific recap, filtered by RecapDocument inclusion."""
    from database import RecapDocument
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    docs = (
        db.query(Document)
        .join(RecapDocument, RecapDocument.document_id == Document.id)
        .filter(
            RecapDocument.recap_id == recap_id,
            RecapDocument.included == True,
            Document.document_type == "traceability",
            Document.created_at >= cutoff,
        )
        .all()
    )
    return [{"filename": d.filename, "content": (d.content or "")[:10000]} for d in docs]


def fetch_notion_content(agent_id: int, db: Session) -> list[dict]:
    """Fetch live content from all Notion links attached to the agent."""
    links = db.query(NotionLink).filter(NotionLink.agent_id == agent_id).all()
    if not links:
        return []

    from notion_client import (
        get_notion_token,
        fetch_page_content,
        fetch_database_entries,
        blocks_to_text,
        database_entries_to_text,
    )

    # Get company_id from the agent's owner
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    company_id = None
    if agent:
        owner = db.query(User).filter(User.id == agent.user_id).first()
        company_id = owner.company_id if owner else None

    if not get_notion_token(company_id):
        logger.warning("Notion not configured for this organization, skipping Notion content")
        return []

    results = []
    for link in links:
        try:
            if link.resource_type == "page":
                blocks = fetch_page_content(link.notion_resource_id, company_id=company_id)
                content = blocks_to_text(blocks)
            else:
                entries = fetch_database_entries(link.notion_resource_id, company_id=company_id)
                content = database_entries_to_text(entries)

            if content.strip():
                results.append({"label": link.label or "Notion", "content": content[:10000]})
        except Exception as e:
            logger.warning(f"Failed to fetch Notion link {link.id} ({link.label}): {e}")

    return results


FREQUENCY_LABELS = {
    "daily": {"period": "de la journée", "adj": "quotidien", "no_data": "aujourd'hui"},
    "weekly": {"period": "de la semaine", "adj": "hebdomadaire", "no_data": "cette semaine"},
    "monthly": {"period": "du mois", "adj": "mensuel", "no_data": "ce mois-ci"},
}


def build_recap_prompt(
    agent: Agent,
    messages: list[dict],
    docs: list[dict],
    notion_pages: list[dict] | None = None,
    frequency: str = "weekly",
    custom_prompt: str | None = None,
) -> list[dict]:
    """Build the structured prompt for the LLM to generate the recap."""
    labels = FREQUENCY_LABELS.get(frequency, FREQUENCY_LABELS["weekly"])

    # Build messages summary
    messages_text = ""
    for m in messages:
        role_label = "Utilisateur" if m["role"] == "user" else "Assistant"
        messages_text += f"[{m['timestamp']}] {role_label}: {m['content'][:500]}\n"

    if not messages_text:
        messages_text = f"(Aucun message {labels['no_data']})"

    # Build traceability docs summary
    docs_text = ""
    for d in docs:
        docs_text += f"\n--- Document: {d['filename']} ---\n{d['content'][:5000]}\n"

    if not docs_text:
        docs_text = "(Aucun document de traçabilité)"

    agent_name = agent.name or "Agent"
    agent_context = agent.contexte or ""
    custom_prompt = custom_prompt or getattr(agent, "weekly_recap_prompt", None)

    if custom_prompt and custom_prompt.strip():
        system_prompt = f"""Tu es {agent_name}, un assistant IA d'entreprise. {agent_context}

{custom_prompt.strip()}

IMPORTANT: Génère UNIQUEMENT du contenu HTML, sans balises <html>, <head>, <body>.
Utilise des <h2> pour les titres de section et des <ul>/<li> pour les listes."""
    else:
        system_prompt = f"""Tu es {agent_name}, un assistant IA d'entreprise. {agent_context}

Tu dois générer un recap {labels["adj"]} structuré en HTML à partir des conversations et documents {labels["period"]}.

IMPORTANT: Génère UNIQUEMENT le contenu HTML des 3 sections ci-dessous, sans balises <html>, <head>, <body>.

Les 3 sections obligatoires:
1. **Projets réalisés** - Ce qui a été accompli {labels["period"]}
2. **Deadlines à venir** - Échéances et dates importantes identifiées
3. **Enjeux clés** - Points d'attention et risques

Format HTML attendu:
<h2 style="color: #6366f1; margin-top: 20px;">Projets réalisés</h2>
<ul>...</ul>

<h2 style="color: #8b5cf6; margin-top: 20px;">Deadlines à venir</h2>
<ul>...</ul>

<h2 style="color: #a855f7; margin-top: 20px;">Enjeux clés</h2>
<ul>...</ul>

Si une section n'a pas de contenu pertinent, indique "Aucun élément identifié {labels["no_data"]}."
Sois concis et actionnable. Utilise des <li> pour chaque point."""

    # Build Notion pages summary
    notion_text = ""
    if notion_pages:
        for n in notion_pages:
            notion_text += f"\n--- Page Notion: {n['label']} ---\n{n['content'][:5000]}\n"

    if not notion_text:
        notion_text = "(Aucune page Notion liée)"

    user_prompt = f"""Voici les conversations {labels["period"]}:
{messages_text}

Voici les documents de traçabilité {labels["period"]}:
{docs_text}

Voici le contenu des pages Notion liées:
{notion_text}

Génère le recap {labels["adj"]} HTML maintenant."""

    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def process_agent_recap(agent: Agent, db: Session) -> dict:
    """Full pipeline: fetch data -> LLM -> email -> log. Returns result dict."""
    user = db.query(User).filter(User.id == agent.user_id).first()
    if not user:
        return {"status": "error", "error": "User not found"}

    try:
        # 1. Fetch data scoped to the recap period
        days_back = get_days_back(agent)
        messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
        docs = fetch_traceability_documents(agent.id, db, days_back=days_back)
        notion_pages = fetch_notion_content(agent.id, db)

        if not messages and not docs and not notion_pages:
            log = WeeklyRecapLog(
                agent_id=agent.id, user_id=user.id, company_id=agent.company_id, status="no_data", recap_content=None
            )
            db.add(log)
            db.commit()
            return {"status": "no_data", "message": "No messages or documents this week"}

        # 2. Build prompt and call LLM
        freq = getattr(agent, "recap_frequency", "weekly")
        prompt_messages = build_recap_prompt(agent, messages, docs, notion_pages, frequency=freq)
        model_id = get_model_id_for_agent(agent)
        recap_content = get_chat_response(prompt_messages, model_id=model_id)

        # 3. Generate HTML email
        html = generate_recap_html(agent.name, recap_content)

        # 4. Build recipient list (owner + extra recipients)
        recipients = [user.email]
        raw_recipients = getattr(agent, "weekly_recap_recipients", None)
        if raw_recipients:
            try:
                extra = json.loads(raw_recipients)
                if isinstance(extra, list):
                    recipients.extend(e.strip() for e in extra if e.strip() and e.strip() != user.email)
            except (json.JSONDecodeError, TypeError):
                pass
        # Deduplicate while preserving order
        seen = set()
        unique_recipients = []
        for r in recipients:
            if r not in seen:
                seen.add(r)
                unique_recipients.append(r)

        send_recap_email(unique_recipients, agent.name, html)

        # 5. Log success
        log = WeeklyRecapLog(
            agent_id=agent.id,
            user_id=user.id,
            company_id=agent.company_id,
            status="success",
            recap_content=recap_content,
        )
        db.add(log)
        db.commit()

        return {
            "status": "success",
            "agent_name": agent.name,
            "email": ", ".join(unique_recipients),
            "message_count": len(messages),
            "doc_count": len(docs),
        }

    except Exception as e:
        logger.error(f"Recap failed for agent {agent.id}: {e}")
        try:
            log = WeeklyRecapLog(
                agent_id=agent.id,
                user_id=user.id,
                company_id=agent.company_id,
                status="error",
                error_message=str(e)[:500],
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()

        return {"status": "error", "error": str(e)}


def process_recap(recap, db: Session) -> dict:
    """Full pipeline for a single Recap entity: fetch data -> LLM -> email -> log."""
    from database import Recap, User, WeeklyRecapLog
    agent = db.query(Agent).filter(Agent.id == recap.agent_id).first()
    if not agent:
        return {"status": "error", "error": "Agent not found"}

    user = db.query(User).filter(User.id == agent.user_id).first()
    if not user:
        return {"status": "error", "error": "User not found"}

    try:
        days_back = FREQUENCY_DAYS.get(recap.frequency, 7)
        messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
        docs = fetch_recap_traceability_documents(recap.id, db, days_back=days_back)
        notion_pages = fetch_notion_content(agent.id, db)

        if not messages and not docs and not notion_pages:
            log = WeeklyRecapLog(
                agent_id=agent.id,
                recap_id=recap.id,
                user_id=user.id,
                company_id=agent.company_id,
                status="no_data",
                recap_content=None,
            )
            db.add(log)
            db.commit()
            return {"status": "no_data", "message": "No data for this period"}

        prompt_messages = build_recap_prompt(
            agent, messages, docs, notion_pages,
            frequency=recap.frequency, custom_prompt=recap.prompt,
        )
        model_id = get_model_id_for_agent(agent)
        recap_content = get_chat_response(prompt_messages, model_id=model_id)

        html = generate_recap_html(agent.name, recap_content, recap_name=recap.name)

        # Build recipient list
        recipients = [user.email]
        if recap.recipients:
            try:
                import json
                extra = json.loads(recap.recipients)
                if isinstance(extra, list):
                    recipients.extend(e.strip() for e in extra if e.strip() and e.strip() != user.email)
            except (json.JSONDecodeError, TypeError):
                pass
        seen = set()
        unique_recipients = []
        for r in recipients:
            if r not in seen:
                seen.add(r)
                unique_recipients.append(r)

        send_recap_email(unique_recipients, agent.name, html, recap_name=recap.name)

        log = WeeklyRecapLog(
            agent_id=agent.id,
            recap_id=recap.id,
            user_id=user.id,
            company_id=agent.company_id,
            status="success",
            recap_content=recap_content,
        )
        db.add(log)
        db.commit()

        return {
            "status": "success",
            "agent_name": agent.name,
            "recap_name": recap.name,
            "email": ", ".join(unique_recipients),
            "message_count": len(messages),
            "doc_count": len(docs),
        }

    except Exception as e:
        logger.error(f"Recap failed for recap {recap.id}: {e}")
        try:
            log = WeeklyRecapLog(
                agent_id=agent.id,
                recap_id=recap.id,
                user_id=user.id,
                company_id=agent.company_id,
                status="error",
                error_message=str(e)[:500],
            )
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "error", "error": str(e)}
