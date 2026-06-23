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

from recap_scheduler import _is_schedule_due


class _FakeMission:
    def __init__(self, status="active", agent_id=1):
        self.id = 1
        self.status = status
        self.agent_id = agent_id


class _FakeSchedule:
    def __init__(self, kind, weekday=None, run_date=None, hour=8, enabled=True, last_run_at=None):
        self.id = 1
        self.kind = kind
        self.weekday = weekday
        self.run_date = run_date
        self.hour = hour
        self.enabled = enabled
        self.last_run_at = last_run_at


class TestIsScheduleDue:
    def _now(self, weekday, hour):
        # 2026-06-15 is a Monday (weekday 0). Offset to reach target weekday.
        base = _date(2026, 6, 15)
        d = base + timedelta(days=weekday)
        return _pytz.timezone("Europe/Paris").localize(_dt(d.year, d.month, d.day, hour, 0))

    def test_recurring_due(self):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8)) is True

    def test_recurring_wrong_hour(self):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 9)) is False

    def test_recurring_wrong_weekday(self):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(3, 8)) is False

    def test_recurring_deduped_within_6_days(self):
        now = self._now(2, 8)
        recent = now.replace(tzinfo=None) - timedelta(days=2)
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8, last_run_at=recent)
        assert _is_schedule_due(s, m, now) is False

    def test_once_due(self):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date(), hour=8)
        assert _is_schedule_due(s, m, now) is True

    def test_once_wrong_date(self):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date() + timedelta(days=1), hour=8)
        assert _is_schedule_due(s, m, now) is False

    def test_once_already_run(self):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date(), hour=8, last_run_at=now.replace(tzinfo=None))
        assert _is_schedule_due(s, m, now) is False

    def test_disabled(self):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8, enabled=False)
        assert _is_schedule_due(s, m, self._now(2, 8)) is False

    def test_archived_mission(self):
        m, s = _FakeMission(status="archived"), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8)) is False

    def test_no_companion(self):
        m, s = _FakeMission(agent_id=None), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8)) is False


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
    sched = await client.post(
        f"/api/automations/missions/{mid}/recap-schedules",
        json={"kind": "recurring", "weekday": 0, "hour": 8, "enabled": True},
        cookies=member_cookies,
    )
    sid = sched.json()["id"]
    resp = await client.post(f"/api/automations/missions/{mid}/recap-schedules/{sid}/generate", cookies=member_cookies)
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


async def test_create_list_recap_schedule(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    resp = await client.post(
        f"/api/automations/missions/{mid}/recap-schedules",
        json={"kind": "recurring", "weekday": 1, "hour": 9},
        cookies=member_cookies,
    )
    assert resp.status_code == 200, resp.text
    listing = await client.get(f"/api/automations/missions/{mid}/recap-schedules", cookies=member_cookies)
    assert listing.status_code == 200
    schedules = listing.json()["schedules"]
    assert len(schedules) == 1
    assert schedules[0]["kind"] == "recurring"
    assert schedules[0]["weekday"] == 1


async def test_update_and_delete_recap_schedule(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    made = await client.post(
        f"/api/automations/missions/{mid}/recap-schedules",
        json={"kind": "once", "run_date": "2026-07-01", "hour": 10},
        cookies=member_cookies,
    )
    sid = made.json()["id"]
    upd = await client.put(
        f"/api/automations/missions/{mid}/recap-schedules/{sid}",
        json={"kind": "once", "run_date": "2026-07-02", "hour": 11, "enabled": False},
        cookies=member_cookies,
    )
    assert upd.status_code == 200, upd.text
    deleted = await client.delete(f"/api/automations/missions/{mid}/recap-schedules/{sid}", cookies=member_cookies)
    assert deleted.status_code == 200
    listing = await client.get(f"/api/automations/missions/{mid}/recap-schedules", cookies=member_cookies)
    assert listing.json()["schedules"] == []


async def test_recap_schedule_recurring_requires_weekday(client, member_cookies):
    created = await client.post(
        "/api/automations/missions",
        json={"name": "M", "objective": "O"},
        cookies=member_cookies,
    )
    mid = created.json()["mission"]["id"]
    resp = await client.post(
        f"/api/automations/missions/{mid}/recap-schedules",
        json={"kind": "recurring", "hour": 9},
        cookies=member_cookies,
    )
    assert resp.status_code == 422


def test_mission_recap_prompt_and_recap_source_columns_exist():
    from database import Mission, Document

    assert hasattr(Mission, "recap_prompt")
    assert hasattr(Document, "is_mission_recap_source")


def test_mission_update_schema_accepts_recap_prompt():
    from schemas.missions import MissionUpdate

    m = MissionUpdate(name="x", objective="y", recap_prompt="hello")
    assert m.recap_prompt == "hello"


def test_mission_update_schema_recap_prompt_defaults_none():
    from schemas.missions import MissionUpdate

    m = MissionUpdate(name="x", objective="y")
    assert m.recap_prompt is None


def test_mission_update_schema_recap_prompt_max_length():
    from schemas.missions import MissionUpdate
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MissionUpdate(name="x", objective="y", recap_prompt="a" * 10001)


def test_build_mission_recap_prompt_uses_custom_prompt():
    import types
    from mission_recap import build_mission_recap_prompt

    mission = types.SimpleNamespace(objective="Obj", id=1, user_id=1, company_id=1)
    agent = types.SimpleNamespace(name="Bot", contexte="")
    msgs = build_mission_recap_prompt(mission, agent, [], [], custom_prompt="MY CUSTOM PROMPT")
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "MY CUSTOM PROMPT"


def test_build_mission_recap_prompt_default_when_no_custom():
    import types
    from mission_recap import build_mission_recap_prompt

    mission = types.SimpleNamespace(objective="Obj", id=1, user_id=1, company_id=1)
    agent = types.SimpleNamespace(name="Bot", contexte="")
    msgs = build_mission_recap_prompt(mission, agent, [], [])
    assert msgs[0]["role"] == "system"
    assert "récap" in msgs[0]["content"].lower() or "recap" in msgs[0]["content"].lower()


# ---------------------------------------------------------------------------
# Per-recap-schedule document endpoint tests (require DB; auto-skip when PG unavailable)
# ---------------------------------------------------------------------------


async def test_recap_schedule_document_upload_list_delete(client, db_session, member_cookies, test_mission):
    """Recap-schedule docs appear in /recap-schedules/{sid}/documents, not in /documents."""
    from tests.factories import DocumentFactory
    from database import Document, MissionRecapSchedule

    mid = test_mission.id

    # Create a recap schedule directly via DB (no factory needed).
    schedule = MissionRecapSchedule(
        mission_id=mid,
        company_id=test_mission.company_id,
        kind="recurring",
        weekday=1,
        hour=9,
        enabled=True,
    )
    db_session.add(schedule)
    db_session.flush()
    sid = schedule.id

    # Seed a regular mission doc (no recap link) — should appear in /documents only.
    regular_doc = DocumentFactory.build(
        user_id=test_mission.user_id,
        mission_id=mid,
        is_mission_recap_source=False,
        filename="regular.txt",
    )
    db_session.add(regular_doc)
    db_session.flush()

    # Seed a per-schedule recap doc directly (bypass GCS).
    recap_doc = DocumentFactory.build(
        user_id=test_mission.user_id,
        mission_id=mid,
        is_mission_recap_source=True,
        recap_schedule_id=sid,
        filename="recap-schedule-source.txt",
    )
    db_session.add(recap_doc)
    db_session.flush()
    recap_doc_id = recap_doc.id

    # GET /recap-schedules/{sid}/documents must include recap_doc, NOT regular_doc.
    resp = await client.get(f"/api/automations/missions/{mid}/recap-schedules/{sid}/documents", cookies=member_cookies)
    assert resp.status_code == 200, resp.text
    schedule_doc_ids = [d["id"] for d in resp.json()["documents"]]
    assert recap_doc_id in schedule_doc_ids
    assert regular_doc.id not in schedule_doc_ids

    # GET /documents must include regular_doc, NOT recap_doc (is_mission_recap_source=True filters it).
    resp = await client.get(f"/api/automations/missions/{mid}/documents", cookies=member_cookies)
    assert resp.status_code == 200, resp.text
    doc_ids = [d["id"] for d in resp.json()["documents"]]
    assert regular_doc.id in doc_ids
    assert recap_doc_id not in doc_ids

    # DELETE /recap-schedules/{sid}/documents/{id} must remove the recap doc.
    resp = await client.delete(
        f"/api/automations/missions/{mid}/recap-schedules/{sid}/documents/{recap_doc_id}",
        cookies=member_cookies,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True

    # After deletion, the schedule's document list must no longer contain the doc.
    resp = await client.get(f"/api/automations/missions/{mid}/recap-schedules/{sid}/documents", cookies=member_cookies)
    assert resp.status_code == 200
    remaining_ids = [d["id"] for d in resp.json()["documents"]]
    assert recap_doc_id not in remaining_ids


async def test_deleting_recap_schedule_cascades_its_documents(client, db_session, member_cookies, test_mission):
    """Deleting a recap schedule removes its documents AND their chunks, with no FK error."""
    from tests.factories import DocumentFactory
    from database import Document, DocumentChunk, MissionRecapSchedule

    mid = test_mission.id
    schedule = MissionRecapSchedule(
        mission_id=mid, company_id=test_mission.company_id, kind="recurring", weekday=1, hour=9, enabled=True
    )
    db_session.add(schedule)
    db_session.flush()
    sid = schedule.id

    doc = DocumentFactory.build(
        user_id=test_mission.user_id,
        mission_id=mid,
        is_mission_recap_source=True,
        recap_schedule_id=sid,
        filename="to-cascade.txt",
    )
    db_session.add(doc)
    db_session.flush()
    # A chunk on the doc exercises the document_chunks FK path that would 500 on a raw cascade.
    chunk = DocumentChunk(document_id=doc.id, company_id=test_mission.company_id, chunk_text="x", chunk_index=0)
    db_session.add(chunk)
    db_session.flush()
    doc_id = doc.id

    # Deleting the schedule must succeed (not 500) and remove the doc + its chunks.
    resp = await client.delete(f"/api/automations/missions/{mid}/recap-schedules/{sid}", cookies=member_cookies)
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    assert db_session.query(Document).filter(Document.id == doc_id).first() is None
    assert db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() == 0


def test_recap_schedule_prompt_and_doc_schedule_link_columns_exist():
    from database import Document, MissionRecapSchedule

    assert hasattr(MissionRecapSchedule, "recap_prompt")
    assert hasattr(Document, "recap_schedule_id")


def test_recap_schedule_create_schema_accepts_recap_prompt():
    from schemas.missions import RecapScheduleCreate

    s = RecapScheduleCreate(kind="recurring", weekday=0, hour=8, recap_prompt="hi")
    assert s.recap_prompt == "hi"


def test_search_similar_texts_accepts_recap_schedule_id():
    import inspect
    from rag_engine import search_similar_texts_for_user

    params = inspect.signature(search_similar_texts_for_user).parameters
    assert "recap_schedule_id" in params
    assert "recap_source_only" not in params
