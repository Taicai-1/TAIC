"""
Monitoring helpers: error capture and request metrics.

Global instances are attached in main.py at startup.
"""

import logging
import statistics
import time
import traceback as tb_module
from collections import deque
from datetime import datetime, timezone
from typing import Any

# Windows-compatible memory helper
try:
    import resource

    def _get_memory_rss_kb():
        """Return max RSS in KB (Unix only)."""
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

except ImportError:
    # Windows: resource module unavailable
    def _get_memory_rss_kb():
        return None


# ---------------------------------------------------------------------------
# Error capture handler
# ---------------------------------------------------------------------------
class ErrorCaptureHandler(logging.Handler):
    """Ring-buffer handler that captures ERROR+ log records for monitoring."""

    def __init__(self, maxlen: int = 100):
        super().__init__(level=logging.ERROR)
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "traceback": None,
        }
        if record.exc_info and record.exc_info[1] is not None:
            entry["traceback"] = tb_module.format_exception(*record.exc_info)
        self._buffer.append(entry)

    def get_errors(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent errors (newest first)."""
        items = list(self._buffer)
        items.reverse()
        return items[:limit]

    def __len__(self):
        return len(self._buffer)


# ---------------------------------------------------------------------------
# Request metrics tracker
# ---------------------------------------------------------------------------
class RequestMetricsTracker:
    """Ring-buffer tracker for HTTP request latencies and status codes."""

    def __init__(self, maxlen: int = 10000):
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, method: str, path: str, status_code: int, latency_ms: float):
        self._buffer.append(
            {
                "ts": time.time(),
                "method": method,
                "path": path,
                "status_code": status_code,
                "latency_ms": round(latency_ms, 2),
            }
        )

    def get_summary(self, seconds: int = 3600) -> dict[str, Any]:
        """Compute request summary for the last *seconds*."""
        cutoff = time.time() - seconds
        recent = [r for r in self._buffer if r["ts"] >= cutoff]

        if not recent:
            return {
                "window_seconds": seconds,
                "total_requests": 0,
                "by_status": {},
                "by_method": {},
                "latency_percentiles": {},
            }

        latencies = [r["latency_ms"] for r in recent]
        latencies_sorted = sorted(latencies)

        def _percentile(data, p):
            k = (len(data) - 1) * (p / 100)
            f = int(k)
            c = f + 1 if f + 1 < len(data) else f
            return round(data[f] + (k - f) * (data[c] - data[f]), 2)

        by_status: dict[str, int] = {}
        by_method: dict[str, int] = {}
        for r in recent:
            sc = str(r["status_code"])
            by_status[sc] = by_status.get(sc, 0) + 1
            by_method[r["method"]] = by_method.get(r["method"], 0) + 1

        return {
            "window_seconds": seconds,
            "total_requests": len(recent),
            "by_status": by_status,
            "by_method": by_method,
            "latency_percentiles": {
                "p50": _percentile(latencies_sorted, 50),
                "p90": _percentile(latencies_sorted, 90),
                "p95": _percentile(latencies_sorted, 95),
                "p99": _percentile(latencies_sorted, 99),
                "avg": round(statistics.mean(latencies), 2),
            },
        }

    def __len__(self):
        return len(self._buffer)


# ---------------------------------------------------------------------------
# Global instances (imported by main.py and routers)
# ---------------------------------------------------------------------------
error_handler = ErrorCaptureHandler(maxlen=100)
request_metrics = RequestMetricsTracker(maxlen=10000)
