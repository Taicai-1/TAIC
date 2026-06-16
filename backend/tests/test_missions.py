"""Tests for the missions feature: schemas, date windows, due-check, models."""

import pytest
from datetime import date, timedelta
from pydantic import ValidationError

from schemas.missions import MissionCreate, ParsedEvent, EventsBulk, RecapScheduleCreate


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


class TestRecapScheduleSchema:
    def test_recurring_valid(self):
        s = RecapScheduleCreate(kind="recurring", weekday=2, hour=8)
        assert s.weekday == 2

    def test_recurring_requires_weekday(self):
        with pytest.raises(ValidationError):
            RecapScheduleCreate(kind="recurring", hour=8)

    def test_once_valid(self):
        s = RecapScheduleCreate(kind="once", run_date="2026-07-01", hour=9)
        assert s.run_date == date(2026, 7, 1)

    def test_once_requires_run_date(self):
        with pytest.raises(ValidationError):
            RecapScheduleCreate(kind="once", hour=9)

    def test_bad_kind_rejected(self):
        with pytest.raises(ValidationError):
            RecapScheduleCreate(kind="daily", weekday=0, hour=9)

    def test_hour_bounds(self):
        with pytest.raises(ValidationError):
            RecapScheduleCreate(kind="recurring", weekday=0, hour=24)

    def test_weekday_bounds(self):
        with pytest.raises(ValidationError):
            RecapScheduleCreate(kind="recurring", weekday=7, hour=9)


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


# ---------------------------------------------------------------------------
# Endpoint tests (require DB; auto-skip when PostgreSQL is unavailable)
# ---------------------------------------------------------------------------


async def test_create_and_list_mission(client, member_cookies):
    resp = await client.post(
        "/api/automations/missions",
        json={"name": "Lancement", "objective": "Réussir le lancement"},
        cookies=member_cookies,
    )
    assert resp.status_code == 200, resp.text
    mid = resp.json()["mission"]["id"]

    listing = await client.get("/api/automations/missions", cookies=member_cookies)
    assert listing.status_code == 200
    assert any(m["id"] == mid for m in listing.json()["missions"])


async def test_owner_can_get_mission(client, member_cookies, test_mission):
    # member_cookies belongs to test_member_user, who OWNS test_mission → 200
    resp = await client.get(f"/api/automations/missions/{test_mission.id}", cookies=member_cookies)
    assert resp.status_code == 200, resp.text
    assert resp.json()["mission"]["id"] == test_mission.id


async def test_other_user_cannot_get_mission(client, db_session, test_mission, test_company):
    # A DIFFERENT user in the SAME company must not see another user's private mission → 404
    from auth import create_access_token
    from tests.factories import UserFactory, CompanyMembershipFactory

    other = UserFactory.build(company_id=test_company.id)
    db_session.add(other)
    db_session.flush()
    membership = CompanyMembershipFactory.build(user_id=other.id, company_id=test_company.id, role="member")
    db_session.add(membership)
    db_session.flush()
    other_cookies = {"token": create_access_token(data={"sub": str(other.id)})}

    resp = await client.get(f"/api/automations/missions/{test_mission.id}", cookies=other_cookies)
    assert resp.status_code == 404


async def test_create_event_and_list(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    ev = await client.post(
        f"/api/automations/missions/{mid}/events",
        json={"date": "2026-07-01", "title": "Comité"},
        cookies=member_cookies,
    )
    assert ev.status_code == 200, ev.text
    listing = await client.get(f"/api/automations/missions/{mid}/events", cookies=member_cookies)
    assert listing.status_code == 200
    events = listing.json()["events"]
    assert len(events) == 1
    assert events[0]["source"] == "manual"


async def test_generate_recap_requires_companion(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},  # no agent_id
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    resp = await client.post(
        f"/api/automations/missions/{mid}/recaps/generate", cookies=member_cookies
    )
    assert resp.status_code == 400


async def test_archived_mission_blocks_event_create(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    # archive it
    await client.put(
        f"/api/automations/missions/{mid}",
        json={"name": "M", "objective": "O", "status": "archived"},
        cookies=member_cookies,
    )
    resp = await client.post(
        f"/api/automations/missions/{mid}/events",
        json={"date": "2026-07-01", "title": "X"},
        cookies=member_cookies,
    )
    assert resp.status_code == 400
