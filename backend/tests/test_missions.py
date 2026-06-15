"""Tests for the missions feature: schemas, date windows, due-check, models."""

import pytest
from datetime import date, timedelta
from pydantic import ValidationError

from schemas.missions import MissionCreate, ParsedEvent, EventsBulk


class TestMissionCreateSchema:
    def test_minimal_valid(self):
        m = MissionCreate(name="Lancement", objective="Réussir le lancement")
        assert m.name == "Lancement"
        assert m.agent_id is None

    def test_blank_name_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(name="   ", objective="x")

    def test_blank_objective_rejected(self):
        with pytest.raises(ValidationError):
            MissionCreate(name="x", objective="  ")

    def test_recap_weekday_bounds(self):
        with pytest.raises(ValidationError):
            MissionCreate(name="x", objective="y", recap_weekday=7)

    def test_recap_hour_bounds(self):
        with pytest.raises(ValidationError):
            MissionCreate(name="x", objective="y", recap_hour=24)


class TestParsedEventSchema:
    def test_iso_date_parsed(self):
        e = ParsedEvent(date="2026-06-20", title="Comité")
        assert e.date == date(2026, 6, 20)

    def test_blank_title_rejected(self):
        with pytest.raises(ValidationError):
            ParsedEvent(date="2026-06-20", title="  ")

    def test_invalid_date_rejected(self):
        with pytest.raises(ValidationError):
            ParsedEvent(date="not-a-date", title="x")

    def test_description_optional(self):
        e = ParsedEvent(date="2026-06-20", title="x")
        assert e.description is None


class TestEventsBulkSchema:
    def test_replace_flag_default_false(self):
        b = EventsBulk(events=[{"date": "2026-06-20", "title": "x"}])
        assert b.replace_upload is False
        assert len(b.events) == 1

    def test_empty_events_allowed(self):
        b = EventsBulk(events=[])
        assert b.events == []

from datetime import date as _date

from mission_recap import upcoming_window, recall_window


class TestDateWindows:
    def test_upcoming_window_is_7_days_inclusive(self):
        d = _date(2026, 6, 15)
        start, end = upcoming_window(d)
        assert start == _date(2026, 6, 15)
        assert end == _date(2026, 6, 21)

    def test_recall_window_is_prior_7_days(self):
        d = _date(2026, 6, 15)
        start, end = recall_window(d)
        assert start == _date(2026, 6, 8)
        assert end == _date(2026, 6, 14)


from datetime import datetime as _dt
import pytz as _pytz

from recap_scheduler import _is_mission_due


class _FakeMission:
    def __init__(self, weekday, hour, enabled=True, status="active", agent_id=1):
        self.id = 1
        self.recap_weekday = weekday
        self.recap_hour = hour
        self.recap_enabled = enabled
        self.status = status
        self.agent_id = agent_id


class TestIsMissionDue:
    def _now(self, weekday, hour):
        # 2026-06-15 is a Monday (weekday 0). Offset to reach target weekday.
        base = _date(2026, 6, 15)
        d = base + timedelta(days=weekday)
        return _pytz.timezone("Europe/Paris").localize(_dt(d.year, d.month, d.day, hour, 0))

    def test_due_on_matching_weekday_and_hour(self, db_session):
        m = _FakeMission(weekday=2, hour=8)
        assert _is_mission_due(m, self._now(2, 8), db_session) is True

    def test_not_due_wrong_hour(self, db_session):
        m = _FakeMission(weekday=2, hour=8)
        assert _is_mission_due(m, self._now(2, 9), db_session) is False

    def test_not_due_wrong_weekday(self, db_session):
        m = _FakeMission(weekday=2, hour=8)
        assert _is_mission_due(m, self._now(3, 8), db_session) is False

    def test_not_due_when_disabled(self, db_session):
        m = _FakeMission(weekday=2, hour=8, enabled=False)
        assert _is_mission_due(m, self._now(2, 8), db_session) is False

    def test_not_due_when_no_companion(self, db_session):
        m = _FakeMission(weekday=2, hour=8, agent_id=None)
        assert _is_mission_due(m, self._now(2, 8), db_session) is False
