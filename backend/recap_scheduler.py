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

from database import SessionLocal, Agent, WeeklyRecapLog

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

PARIS_TZ = pytz.timezone("Europe/Paris")


def _get_send_hours(recap_hour: int) -> set[int]:
    """For 6h frequency, return the 4 send hours in a day."""
    return {(recap_hour + offset) % 24 for offset in (0, 6, 12, 18)}


def _is_due(agent: Agent, now: datetime, db) -> bool:
    """Check if an agent is due for a recap right now."""
    freq = agent.recap_frequency or "weekly"
    hour = agent.recap_hour if agent.recap_hour is not None else 9
    current_hour = now.hour

    if freq == "6h":
        if current_hour not in _get_send_hours(hour):
            return False
    elif freq in ("daily", "2days", "weekly"):
        if current_hour != hour:
            return False
    else:
        return False

    if freq == "weekly" and now.weekday() != 0:  # Monday = 0
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
        min_gap = {"6h": timedelta(hours=5), "daily": timedelta(hours=23), "2days": timedelta(hours=47), "weekly": timedelta(days=6)}
        if now.replace(tzinfo=None) - last_log.sent_at < min_gap.get(freq, timedelta(days=6)):
            return False

    return True


def _run_scheduled_recaps():
    """Hourly tick: find and process all due recaps."""
    logger.info("Recap scheduler tick starting")
    now = datetime.now(PARIS_TZ)
    db = SessionLocal()

    try:
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        due_count = 0

        for agent in agents:
            if _is_due(agent, now, db):
                due_count += 1
                try:
                    from weekly_recap import process_agent_recap

                    result = process_agent_recap(agent, db)
                    logger.info(f"Recap for agent {agent.id} ({agent.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Recap failed for agent {agent.id}: {e}")

        logger.info(f"Recap scheduler tick done: {due_count} agents processed out of {len(agents)} enabled")
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
