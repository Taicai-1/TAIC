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
