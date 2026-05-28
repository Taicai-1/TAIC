"""
Internal scheduler for recap emails.
Runs an hourly job that checks which agents are due for a recap
based on their recap_frequency and recap_hour settings.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from sqlalchemy import text
from database import SessionLocal, Agent, Recap, WeeklyRecapLog

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

PARIS_TZ = pytz.timezone("Europe/Paris")


def _is_due(agent: Agent, now: datetime, db) -> bool:
    """Check if an agent is due for a recap right now."""
    freq = agent.recap_frequency or "weekly"
    hour = agent.recap_hour if agent.recap_hour is not None else 9
    current_hour = now.hour

    if freq in ("daily", "weekly", "monthly"):
        if current_hour != hour:
            return False
    else:
        return False

    if freq == "weekly" and now.weekday() != 0:  # Monday = 0
        return False

    if freq == "monthly" and now.day != 1:  # 1st of the month
        return False

    # Check last send time to avoid duplicates
    last_log = (
        db.query(WeeklyRecapLog)
        .filter(
            WeeklyRecapLog.agent_id == agent.id,
            WeeklyRecapLog.status.in_(["success", "no_data"]),
        )
        .order_by(WeeklyRecapLog.sent_at.desc())
        .first()
    )

    if last_log and last_log.sent_at:
        min_gap = {"daily": timedelta(hours=23), "weekly": timedelta(days=6), "monthly": timedelta(days=27)}
        if now.replace(tzinfo=None) - last_log.sent_at < min_gap.get(freq, timedelta(days=6)):
            return False

    return True


def _is_recap_due(recap: Recap, now: datetime, db) -> bool:
    """Check if a Recap entity is due for sending right now."""
    freq = recap.frequency or "weekly"
    hour = recap.hour if recap.hour is not None else 9
    current_hour = now.hour

    if freq in ("daily", "weekly", "monthly"):
        if current_hour != hour:
            return False
    else:
        return False

    if freq == "weekly" and now.weekday() != 0:
        return False

    if freq == "monthly" and now.day != 1:
        return False

    last_log = (
        db.query(WeeklyRecapLog)
        .filter(
            WeeklyRecapLog.recap_id == recap.id,
            WeeklyRecapLog.status.in_(["success", "no_data"]),
        )
        .order_by(WeeklyRecapLog.sent_at.desc())
        .first()
    )

    if last_log and last_log.sent_at:
        min_gap = {"daily": timedelta(hours=23), "weekly": timedelta(days=6), "monthly": timedelta(days=27)}
        if now.replace(tzinfo=None) - last_log.sent_at < min_gap.get(freq, timedelta(days=6)):
            return False

    return True


def _run_scheduled_recaps():
    """Hourly tick: find and process all due recaps (both legacy agent-level and new Recap entities)."""
    logger.info("Recap scheduler tick starting")
    now = datetime.now(PARIS_TZ)
    db = SessionLocal()

    try:
        db.execute(text("SET LOCAL app.service_bypass = 'true'"))

        # Process new Recap entities
        recaps = db.query(Recap).filter(Recap.enabled == True).all()
        recap_due_count = 0

        for recap in recaps:
            if _is_recap_due(recap, now, db):
                recap_due_count += 1
                try:
                    from weekly_recap import process_recap

                    result = process_recap(recap, db)
                    logger.info(f"Recap {recap.id} ({recap.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Recap failed for recap {recap.id}: {e}")

        # Legacy: still process agents with weekly_recap_enabled that have NO Recap entities
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        legacy_due_count = 0
        for agent in agents:
            has_recaps = db.query(Recap).filter(Recap.agent_id == agent.id).count() > 0
            if has_recaps:
                continue  # Skip — handled by Recap entities above
            if _is_due(agent, now, db):
                legacy_due_count += 1
                try:
                    from weekly_recap import process_agent_recap

                    result = process_agent_recap(agent, db)
                    logger.info(f"Legacy recap for agent {agent.id} ({agent.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Legacy recap failed for agent {agent.id}: {e}")

        logger.info(f"Recap scheduler tick done: {recap_due_count} recaps + {legacy_due_count} legacy agents processed")
    except Exception as e:
        logger.error(f"Recap scheduler tick failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler with an hourly recap job."""
    scheduler.add_job(
        _run_scheduled_recaps,
        trigger=IntervalTrigger(hours=1),
        id="recap_hourly_tick",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Recap scheduler started (hourly tick)")


def shutdown_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Recap scheduler shut down")
