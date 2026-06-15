"""Tests for the missions feature: schemas, date windows, due-check, models."""

import pytest
from datetime import date
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
