"""Unit tests for monitoring.ErrorCaptureHandler and RequestMetricsTracker."""

import logging
import time

import pytest

from monitoring import ErrorCaptureHandler, RequestMetricsTracker


# ---------------------------------------------------------------------------
# ErrorCaptureHandler
# ---------------------------------------------------------------------------
class TestErrorCaptureHandler:
    def test_captures_error(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.error")
        logger.addHandler(h)
        logger.error("something broke")
        errors = h.get_errors()
        assert len(errors) == 1
        assert errors[0]["level"] == "ERROR"
        assert "something broke" in errors[0]["message"]
        logger.removeHandler(h)

    def test_captures_critical(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.critical")
        logger.addHandler(h)
        logger.critical("fatal issue")
        errors = h.get_errors()
        assert len(errors) == 1
        assert errors[0]["level"] == "CRITICAL"
        logger.removeHandler(h)

    def test_ignores_warning(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.warning")
        logger.addHandler(h)
        logger.warning("just a warning")
        assert len(h) == 0
        logger.removeHandler(h)

    def test_ignores_info(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.info")
        logger.addHandler(h)
        logger.info("informational")
        assert len(h) == 0
        logger.removeHandler(h)

    def test_ring_buffer_maxlen(self):
        h = ErrorCaptureHandler(maxlen=3)
        logger = logging.getLogger("test.capture.ring")
        logger.addHandler(h)
        for i in range(5):
            logger.error(f"error {i}")
        assert len(h) == 3
        errors = h.get_errors()
        assert errors[0]["message"] == "error 4"
        assert errors[2]["message"] == "error 2"
        logger.removeHandler(h)

    def test_entry_structure(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.struct")
        logger.addHandler(h)
        logger.error("structured test")
        entry = h.get_errors()[0]
        assert "timestamp" in entry
        assert entry["logger"] == "test.capture.struct"
        assert entry["traceback"] is None
        logger.removeHandler(h)

    def test_traceback_captured(self):
        h = ErrorCaptureHandler(maxlen=10)
        logger = logging.getLogger("test.capture.tb")
        logger.addHandler(h)
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("caught error")
        entry = h.get_errors()[0]
        assert entry["traceback"] is not None
        assert any("ValueError" in line for line in entry["traceback"])
        logger.removeHandler(h)

    def test_get_errors_limit(self):
        h = ErrorCaptureHandler(maxlen=50)
        logger = logging.getLogger("test.capture.limit")
        logger.addHandler(h)
        for i in range(10):
            logger.error(f"err {i}")
        errors = h.get_errors(limit=3)
        assert len(errors) == 3
        assert errors[0]["message"] == "err 9"
        logger.removeHandler(h)

    def test_get_errors_newest_first(self):
        h = ErrorCaptureHandler(maxlen=50)
        logger = logging.getLogger("test.capture.order")
        logger.addHandler(h)
        logger.error("first")
        logger.error("second")
        errors = h.get_errors()
        assert errors[0]["message"] == "second"
        assert errors[1]["message"] == "first"
        logger.removeHandler(h)


# ---------------------------------------------------------------------------
# RequestMetricsTracker
# ---------------------------------------------------------------------------
class TestRequestMetricsTracker:
    def test_record_and_len(self):
        t = RequestMetricsTracker(maxlen=100)
        t.record("GET", "/health", 200, 5.0)
        assert len(t) == 1

    def test_ring_buffer_maxlen(self):
        t = RequestMetricsTracker(maxlen=3)
        for i in range(5):
            t.record("GET", f"/path{i}", 200, float(i))
        assert len(t) == 3

    def test_summary_empty(self):
        t = RequestMetricsTracker(maxlen=100)
        summary = t.get_summary(seconds=60)
        assert summary["total_requests"] == 0
        assert summary["by_status"] == {}
        assert summary["by_method"] == {}
        assert summary["latency_percentiles"] == {}

    def test_summary_basic(self):
        t = RequestMetricsTracker(maxlen=100)
        t.record("GET", "/a", 200, 10.0)
        t.record("POST", "/b", 201, 20.0)
        t.record("GET", "/c", 500, 30.0)
        summary = t.get_summary(seconds=60)
        assert summary["total_requests"] == 3
        assert summary["by_status"]["200"] == 1
        assert summary["by_status"]["201"] == 1
        assert summary["by_status"]["500"] == 1
        assert summary["by_method"]["GET"] == 2
        assert summary["by_method"]["POST"] == 1

    def test_summary_percentiles(self):
        t = RequestMetricsTracker(maxlen=1000)
        for i in range(100):
            t.record("GET", "/x", 200, float(i + 1))
        summary = t.get_summary(seconds=60)
        p = summary["latency_percentiles"]
        assert p["p50"] == pytest.approx(50.5, abs=1)
        assert p["p90"] == pytest.approx(90.1, abs=1)
        assert p["p99"] == pytest.approx(99.01, abs=1)
        assert p["avg"] == pytest.approx(50.5, abs=1)

    def test_summary_respects_time_window(self):
        t = RequestMetricsTracker(maxlen=100)
        # Inject an old entry by manipulating the buffer directly
        t._buffer.append(
            {"ts": time.time() - 7200, "method": "GET", "path": "/old", "status_code": 200, "latency_ms": 5.0}
        )
        t.record("GET", "/new", 200, 10.0)
        summary = t.get_summary(seconds=3600)
        assert summary["total_requests"] == 1

    def test_summary_single_request(self):
        t = RequestMetricsTracker(maxlen=100)
        t.record("GET", "/solo", 200, 42.0)
        summary = t.get_summary(seconds=60)
        p = summary["latency_percentiles"]
        assert p["p50"] == 42.0
        assert p["p99"] == 42.0
        assert p["avg"] == 42.0
