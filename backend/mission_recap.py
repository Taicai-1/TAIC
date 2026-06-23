"""Mission weekly recap: date windows, RAG enrichment, prompt, persistence, email."""

import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

UPCOMING_DAYS = 7
RECALL_DAYS = 7
RAG_TOP_K = 3
MAX_RAG_SNIPPETS = 12


def upcoming_window(d: date) -> tuple[date, date]:
    """The upcoming window: [d, d + 6] inclusive."""
    return d, d + timedelta(days=UPCOMING_DAYS - 1)


def recall_window(d: date) -> tuple[date, date]:
    """The recall window: the 7 days before d, [d - 7, d - 1] inclusive."""
    return d - timedelta(days=RECALL_DAYS), d - timedelta(days=1)


def fetch_events(mission_id: int, start: date, end: date, db: Session) -> list:
    """Return MissionEvent rows in [start, end] inclusive, ordered by date."""
    from database import MissionEvent

    return (
        db.query(MissionEvent)
        .filter(
            MissionEvent.mission_id == mission_id,
            MissionEvent.event_date >= start,
            MissionEvent.event_date <= end,
        )
        .order_by(MissionEvent.event_date.asc())
        .all()
    )


def enrich_events_with_docs(mission, events: list, db: Session) -> list:
    """For each upcoming event, attach top-k RAG snippets from the mission's docs.

    Returns a list of {event, snippets} dicts. Embeddings use the same Mistral
    model as ingestion so query vectors match the stored pgvector column.
    """
    from mistral_embeddings import get_embedding_fast
    from rag_engine import search_similar_texts_for_user

    enriched = []
    snippet_budget = MAX_RAG_SNIPPETS
    for ev in events:
        snippets = []
        if snippet_budget > 0:
            query = ev.title + (f" — {ev.description}" if ev.description else "")
            try:
                emb = get_embedding_fast(query)
                results = search_similar_texts_for_user(
                    emb,
                    user_id=mission.user_id,
                    db=db,
                    top_k=min(RAG_TOP_K, snippet_budget),
                    company_id=mission.company_id,
                    mission_id=mission.id,
                    recap_source_only=True,
                )
                snippets = [r["text"] for r in results]
                snippet_budget -= len(snippets)
            except Exception as e:
                logger.warning(f"Mission {mission.id}: RAG enrichment failed for event {ev.id}: {e}")
        enriched.append({"event": ev, "snippets": snippets})
    return enriched


def build_mission_recap_prompt(
    mission, agent, recall_events: list, enriched_upcoming: list, custom_prompt: str | None = None
) -> list:
    """Build the [system, user] message list for the recap LLM call."""
    agent_name = (agent.name if agent else None) or "Assistant"
    agent_context = (getattr(agent, "contexte", "") if agent else "") or ""

    if custom_prompt and custom_prompt.strip():
        system_prompt = custom_prompt.strip()
    else:
        system_prompt = f"""Tu es {agent_name}, un assistant IA d'entreprise. {agent_context}

Tu es connecté à une mission dont l'objectif est :
\"\"\"{mission.objective.strip()}\"\"\"

Tu dois produire un récap hebdomadaire en Markdown, analysé À LA LUMIÈRE DE CET OBJECTIF.

Structure attendue :
## Rappel de la semaine écoulée
Un paragraphe bref (2-3 phrases) rappelant ce qui s'est passé. Si aucun évènement, écris "Rien à signaler la semaine dernière."

## Semaine à venir
Pour chaque évènement à venir : ce qu'il implique pour l'objectif, les priorités et points d'attention, en t'appuyant sur les extraits de documents fournis quand ils sont pertinents.

Sois concret et actionnable. N'invente pas d'évènements absents des données."""

    def _fmt_events(events):
        if not events:
            return "(aucun)"
        lines = []
        for ev in events:
            d = ev.event_date.strftime("%A %d/%m/%Y")
            line = f"- {d} : {ev.title}"
            if ev.description:
                line += f" — {ev.description}"
            lines.append(line)
        return "\n".join(lines)

    upcoming_text = ""
    for item in enriched_upcoming:
        ev = item["event"]
        d = ev.event_date.strftime("%A %d/%m/%Y")
        upcoming_text += f"\n### {d} : {ev.title}\n"
        if ev.description:
            upcoming_text += f"{ev.description}\n"
        if item["snippets"]:
            upcoming_text += "Extraits de documents liés :\n"
            for s in item["snippets"]:
                upcoming_text += f"> {s[:800]}\n"
    if not upcoming_text:
        upcoming_text = "(aucun évènement à venir)"

    user_prompt = f"""ÉVÈNEMENTS DE LA SEMAINE ÉCOULÉE :
{_fmt_events(recall_events)}

ÉVÈNEMENTS DE LA SEMAINE À VENIR (avec extraits documentaires) :
{upcoming_text}

Génère le récap Markdown maintenant."""

    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


def process_mission_recap(
    mission, db: Session, trigger: str = "scheduled", run_date: date | None = None, schedule_id: int | None = None
) -> dict:
    """Full pipeline: fetch events -> RAG -> LLM -> persist MissionRecap -> email.

    trigger='manual' skips the email and the scheduler anti-dup is unaffected.
    Returns a result dict with status and the created recap id/content.
    """
    from database import Agent, MissionRecap
    from openai_client import get_chat_response
    from weekly_recap import get_model_id_for_agent

    if run_date is None:
        from datetime import datetime
        import pytz

        run_date = datetime.now(pytz.timezone("Europe/Paris")).date()

    up_start, up_end = upcoming_window(run_date)
    rc_start, rc_end = recall_window(run_date)

    agent = db.query(Agent).filter(Agent.id == mission.agent_id).first() if mission.agent_id else None

    upcoming = fetch_events(mission.id, up_start, up_end, db)

    if not upcoming:
        recap = MissionRecap(
            mission_id=mission.id,
            company_id=mission.company_id,
            period_start=up_start,
            period_end=up_end,
            content=None,
            status="no_data",
            trigger=trigger,
            schedule_id=schedule_id,
        )
        db.add(recap)
        db.commit()
        db.refresh(recap)
        return {"status": "no_data", "recap_id": recap.id}

    try:
        recall = fetch_events(mission.id, rc_start, rc_end, db)
        # RAG enrichment (the only RLS-protected SELECTs here) must run BEFORE the
        # first commit below: the scheduler sets `SET LOCAL app.service_bypass`,
        # which is transaction-scoped and lost after a commit. Do not reorder.
        enriched = enrich_events_with_docs(mission, upcoming, db)
        prompt = build_mission_recap_prompt(
            mission, agent, recall, enriched, custom_prompt=getattr(mission, "recap_prompt", None)
        )
        model_id = get_model_id_for_agent(agent) if agent else "mistral:mistral-large-latest"
        content = get_chat_response(prompt, model_id=model_id)

        recap = MissionRecap(
            mission_id=mission.id,
            company_id=mission.company_id,
            period_start=up_start,
            period_end=up_end,
            content=content,
            status="success",
            trigger=trigger,
            schedule_id=schedule_id,
        )
        db.add(recap)
        db.commit()
        db.refresh(recap)

        # Email is best-effort: the recap was generated and persisted as success,
        # so a send failure must not flip the run to error or leave it un-retried.
        if trigger == "scheduled":
            try:
                _send_recap_email(mission, content, db)
                recap.email_sent = True
                db.commit()
            except Exception as email_err:
                logger.error(f"Mission {mission.id}: recap email failed: {email_err}")
                db.rollback()

        return {"status": "success", "recap_id": recap.id, "content": content}

    except Exception as e:
        logger.error(f"Mission recap failed for mission {mission.id}: {e}")
        # The session may be in an aborted-transaction state after a DB-level
        # error; roll back before attempting the error-row INSERT.
        db.rollback()
        try:
            recap = MissionRecap(
                mission_id=mission.id,
                company_id=mission.company_id,
                period_start=up_start,
                period_end=up_end,
                content=None,
                status="error",
                error_message=str(e)[:500],
                trigger=trigger,
                schedule_id=schedule_id,
            )
            db.add(recap)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "error", "error": str(e)}


def _send_recap_email(mission, content: str, db: Session) -> None:
    """Email the recap to the mission creator. Markdown is wrapped minimally."""
    from database import User
    from email_service import send_email

    user = db.query(User).filter(User.id == mission.user_id).first()
    if not user or not user.email:
        logger.warning(f"Mission {mission.id}: no recipient email, skipping recap email")
        return

    safe = content.replace("\n", "<br>")
    html = (
        f'<div style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto;">'
        f"<h2>Récap mission — {mission.name}</h2>"
        f'<div style="white-space: normal; line-height: 1.6;">{safe}</div>'
        f"</div>"
    )
    subject = f"Récap mission — {mission.name}"
    send_email(user.email, subject, html)
