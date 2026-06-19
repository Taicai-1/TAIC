# Mission Recap Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a mission own multiple recap schedules, each either recurring (weekday + hour) or one-shot (date + hour), replacing the single mission-level weekly recap config that drives the scheduler.

**Architecture:** A new `mission_recap_schedules` table holds the schedules. The hourly recap scheduler iterates enabled schedules (instead of missions) and fires `process_mission_recap` when one is due. A nullable `schedule_id` on `mission_recaps` links a generated recap to its schedule. The legacy `Mission.recap_*` columns are kept but no longer drive scheduling; a migration backfills one recurring schedule per mission that had `recap_enabled=true`. The frontend Settings tab gets a `RecapSchedules` list component.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic v2, Alembic, APScheduler, pytest; Next.js / React, next-i18next.

**Spec:** `docs/superpowers/specs/2026-06-16-mission-recap-schedules-design.md`

---

## File Structure

- `backend/database.py` — add `MissionRecapSchedule` model; add `schedule_id` to `MissionRecap`; add `mission_recaps.schedule_id` to the `ensure_columns()` list; extend the RLS-exempt comment.
- `backend/alembic/versions/0008_mission_recap_schedules.py` — **create**: new table, `schedule_id` column, data backfill.
- `backend/schemas/missions.py` — add `RecapScheduleCreate` / `RecapScheduleUpdate`.
- `backend/recap_scheduler.py` — add `_is_schedule_due`; rewrite `_run_scheduled_mission_recaps`; remove `_is_mission_due`.
- `backend/mission_recap.py` — add `schedule_id` param to `process_mission_recap`, stamp it on the 3 `MissionRecap(...)` sites.
- `backend/routers/missions.py` — add recap-schedules CRUD endpoints.
- `backend/tests/test_missions.py` — schema tests, `_is_schedule_due` tests (replace `_is_mission_due` tests), endpoint tests.
- `frontend/components/automations/missions/RecapSchedules.js` — **create**: schedule list UI.
- `frontend/components/automations/missions/SettingsTab.js` — replace the recap block with `<RecapSchedules>`.
- `frontend/public/locales/fr/automations.json`, `frontend/public/locales/en/automations.json` — add `missions.settings.recapSchedules.*` keys.

---

## Task 1: `MissionRecapSchedule` model + `MissionRecap.schedule_id`

**Files:**
- Modify: `backend/database.py` (after the `MissionRecap` class, ~line 803; the `MissionRecap` class ~788-803; the `ensure_columns()` list ~1013-1015; the RLS comment ~1097-1104)

- [ ] **Step 1: Add `schedule_id` column to `MissionRecap`**

In `backend/database.py`, in `class MissionRecap`, add after the `trigger` column (line 800):

```python
    trigger = Column(String(10), nullable=False, default="scheduled", server_default="scheduled")  # scheduled | manual
    schedule_id = Column(
        Integer, ForeignKey("mission_recap_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

- [ ] **Step 2: Add the `MissionRecapSchedule` model**

In `backend/database.py`, immediately after the `MissionRecap` class (after its `mission` relationship line, ~803), add:

```python
class MissionRecapSchedule(Base):
    __tablename__ = "mission_recap_schedules"

    id = Column(Integer, primary_key=True, index=True)
    mission_id = Column(Integer, ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    kind = Column(String(10), nullable=False)  # recurring | once
    weekday = Column(Integer, nullable=True)  # 0=Monday .. 6=Sunday (recurring only)
    run_date = Column(Date, nullable=True)  # one-shot only
    hour = Column(Integer, nullable=False, default=8, server_default="8")  # Europe/Paris, full hour
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    mission = relationship("Mission")
```

- [ ] **Step 3: Register the new column in `ensure_columns()`**

In `backend/database.py`, in the `ensure_columns()` `migrations` list, in the `# Missions` block (~line 1013), add:

```python
        # Missions
        ("documents", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        ("conversations", "mission_id", "INTEGER REFERENCES missions(id) ON DELETE CASCADE"),
        ("mission_recaps", "schedule_id", "INTEGER REFERENCES mission_recap_schedules(id) ON DELETE SET NULL"),
```

(The `mission_recap_schedules` table itself is created by `Base.metadata.create_all` at startup and by Alembic 0008; only the new *column* on the existing `mission_recaps` table needs an `ensure_columns` entry.)

- [ ] **Step 4: Extend the RLS-exempt comment**

In `backend/database.py`, in the RLS-policies tables comment (~1096), update the mission-tables sentence to include the new table:

```python
        # Mission tables (missions, mission_events, mission_recaps,
        # mission_recap_schedules) are also intentionally ABSENT: the recap
        # scheduler INSERTs mission_recaps from a background session that has no
```

- [ ] **Step 5: Verify the module imports**

Run: `cd backend && python -c "import database; print(database.MissionRecapSchedule.__tablename__)"`
Expected: prints `mission_recap_schedules`

- [ ] **Step 6: Commit**

```bash
git add backend/database.py
git commit -m "feat(missions): MissionRecapSchedule model + recap schedule_id link"
```

---

## Task 2: Alembic migration 0008 (table + column + backfill)

**Files:**
- Create: `backend/alembic/versions/0008_mission_recap_schedules.py`

- [ ] **Step 1: Write the migration**

Create `backend/alembic/versions/0008_mission_recap_schedules.py`:

```python
"""mission recap schedules: table, mission_recaps.schedule_id, backfill

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # create_all() runs before Alembic at startup, so the table/column may
    # already exist on a fresh DB — guard each operation.
    if not inspector.has_table("mission_recap_schedules"):
        op.create_table(
            "mission_recap_schedules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "mission_id", sa.Integer(), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("weekday", sa.Integer(), nullable=True),
            sa.Column("run_date", sa.Date(), nullable=True),
            sa.Column("hour", sa.Integer(), nullable=False, server_default="8"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    existing_recap_cols = {c["name"] for c in inspector.get_columns("mission_recaps")}
    if "schedule_id" not in existing_recap_cols:
        op.add_column("mission_recaps", sa.Column("schedule_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "mission_recaps_schedule_id_fkey",
            "mission_recaps",
            "mission_recap_schedules",
            ["schedule_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index("ix_mission_recaps_schedule_id", "mission_recaps", ["schedule_id"])

    # Backfill: one recurring schedule per mission that had recap_enabled=true and
    # no schedule yet (idempotent on re-run).
    conn.execute(
        sa.text(
            """
            INSERT INTO mission_recap_schedules
                (mission_id, company_id, kind, weekday, hour, enabled, created_at)
            SELECT m.id, m.company_id, 'recurring', m.recap_weekday, m.recap_hour, true, NOW()
            FROM missions m
            WHERE m.recap_enabled = true
              AND NOT EXISTS (
                  SELECT 1 FROM mission_recap_schedules s WHERE s.mission_id = m.id
              )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE mission_recaps DROP COLUMN IF EXISTS schedule_id"))
    conn.execute(sa.text("DROP TABLE IF EXISTS mission_recap_schedules CASCADE"))
```

- [ ] **Step 2: Verify the migration file parses**

Run: `cd backend && python -c "import ast; ast.parse(open('alembic/versions/0008_mission_recap_schedules.py').read()); print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0008_mission_recap_schedules.py
git commit -m "feat(missions): alembic 0008 recap schedules table + backfill"
```

---

## Task 3: Pydantic schemas with conditional validation

**Files:**
- Modify: `backend/schemas/missions.py` (imports line 6; add classes after `EventUpdate`, ~line 81)
- Test: `backend/tests/test_missions.py`

- [ ] **Step 1: Write failing tests**

In `backend/tests/test_missions.py`, add the import at the top alongside the existing schema import:

```python
from schemas.missions import MissionCreate, ParsedEvent, EventsBulk, RecapScheduleCreate
```

Then add a new test class after `TestMissionCreateSchema`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_missions.py::TestRecapScheduleSchema -v`
Expected: FAIL with `ImportError: cannot import name 'RecapScheduleCreate'`

- [ ] **Step 3: Implement the schemas**

In `backend/schemas/missions.py`, change the import line (line 6) to add `model_validator`:

```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

Then add after the `EventUpdate` class (~line 81):

```python
class RecapScheduleCreate(BaseModel):
    kind: str = Field(..., pattern="^(recurring|once)$")
    weekday: Optional[int] = Field(None, ge=0, le=6)
    run_date: Optional[date] = None
    hour: int = Field(..., ge=0, le=23)
    enabled: bool = True

    @model_validator(mode="after")
    def check_kind_fields(self):
        if self.kind == "recurring" and self.weekday is None:
            raise ValueError("weekday is required for a recurring schedule")
        if self.kind == "once" and self.run_date is None:
            raise ValueError("run_date is required for a one-shot schedule")
        return self


class RecapScheduleUpdate(RecapScheduleCreate):
    pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_missions.py::TestRecapScheduleSchema -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/missions.py backend/tests/test_missions.py
git commit -m "feat(missions): recap schedule schemas with conditional validation"
```

---

## Task 4: Scheduler — `_is_schedule_due` + iterate schedules

**Files:**
- Modify: `backend/recap_scheduler.py` (replace `_is_mission_due` ~97-126 and `_run_scheduled_mission_recaps` ~129-145)
- Modify: `backend/mission_recap.py` (`process_mission_recap` signature ~133 + 3 `MissionRecap(...)` sites at ~157, ~181, ~213)
- Test: `backend/tests/test_missions.py` (replace `TestIsMissionDue`)

- [ ] **Step 1: Add `schedule_id` to `process_mission_recap`**

In `backend/mission_recap.py`, change the signature (line 133):

```python
def process_mission_recap(
    mission, db: Session, trigger: str = "scheduled", run_date: date | None = None, schedule_id: int | None = None
) -> dict:
```

Then add `schedule_id=schedule_id,` to each of the three `MissionRecap(...)` constructors (the `no_data` one ~157, the `success` one ~181, and the `error` one ~213). For example the `no_data` site becomes:

```python
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
```

Apply the same `schedule_id=schedule_id,` line to the `success` (status="success") and `error` (status="error") constructors.

- [ ] **Step 2: Write failing scheduler tests**

In `backend/tests/test_missions.py`, replace the `from recap_scheduler import _is_mission_due` import and the entire `_FakeMission` / `TestIsMissionDue` block with:

```python
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

    def test_recurring_due(self, db_session):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8), db_session) is True

    def test_recurring_wrong_hour(self, db_session):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 9), db_session) is False

    def test_recurring_wrong_weekday(self, db_session):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(3, 8), db_session) is False

    def test_recurring_deduped_within_6_days(self, db_session):
        now = self._now(2, 8)
        recent = now.replace(tzinfo=None) - timedelta(days=2)
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8, last_run_at=recent)
        assert _is_schedule_due(s, m, now, db_session) is False

    def test_once_due(self, db_session):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date(), hour=8)
        assert _is_schedule_due(s, m, now, db_session) is True

    def test_once_wrong_date(self, db_session):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date() + timedelta(days=1), hour=8)
        assert _is_schedule_due(s, m, now, db_session) is False

    def test_once_already_run(self, db_session):
        now = self._now(2, 8)
        m = _FakeMission()
        s = _FakeSchedule("once", run_date=now.date(), hour=8, last_run_at=now.replace(tzinfo=None))
        assert _is_schedule_due(s, m, now, db_session) is False

    def test_disabled(self, db_session):
        m, s = _FakeMission(), _FakeSchedule("recurring", weekday=2, hour=8, enabled=False)
        assert _is_schedule_due(s, m, self._now(2, 8), db_session) is False

    def test_archived_mission(self, db_session):
        m, s = _FakeMission(status="archived"), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8), db_session) is False

    def test_no_companion(self, db_session):
        m, s = _FakeMission(agent_id=None), _FakeSchedule("recurring", weekday=2, hour=8)
        assert _is_schedule_due(s, m, self._now(2, 8), db_session) is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_missions.py::TestIsScheduleDue -v`
Expected: FAIL with `ImportError: cannot import name '_is_schedule_due'`

- [ ] **Step 4: Implement `_is_schedule_due` and rewrite the sweep**

In `backend/recap_scheduler.py`, replace `_is_mission_due` (lines 97-126) and `_run_scheduled_mission_recaps` (lines 129-145) with:

```python
def _is_schedule_due(schedule, mission, now: datetime, db) -> bool:
    """Check if a recap schedule is due right now (Europe/Paris)."""
    if not getattr(schedule, "enabled", False):
        return False
    if getattr(mission, "status", "active") != "active":
        return False
    if not getattr(mission, "agent_id", None):
        return False
    if now.hour != schedule.hour:
        return False

    if schedule.kind == "recurring":
        if schedule.weekday is None or now.weekday() != schedule.weekday:
            return False
        if schedule.last_run_at and (now.replace(tzinfo=None) - schedule.last_run_at < timedelta(days=6)):
            return False
        return True

    if schedule.kind == "once":
        if schedule.run_date != now.date():
            return False
        if schedule.last_run_at is not None:
            return False
        return True

    return False


def _run_scheduled_mission_recaps(now: datetime, db) -> int:
    """Find and process all due mission recap schedules. Returns the count processed."""
    from database import Mission, MissionRecapSchedule

    schedules = (
        db.query(MissionRecapSchedule)
        .join(Mission, MissionRecapSchedule.mission_id == Mission.id)
        .filter(MissionRecapSchedule.enabled == True, Mission.status == "active")  # noqa: E712
        .all()
    )
    due_count = 0
    for schedule in schedules:
        mission = schedule.mission
        if mission and _is_schedule_due(schedule, mission, now, db):
            due_count += 1
            try:
                from mission_recap import process_mission_recap

                result = process_mission_recap(
                    mission, db, trigger="scheduled", run_date=now.date(), schedule_id=schedule.id
                )
                schedule.last_run_at = now.replace(tzinfo=None)
                if schedule.kind == "once":
                    schedule.enabled = False
                db.commit()
                logger.info(f"Mission recap schedule {schedule.id} (mission {mission.id}): {result.get('status')}")
            except Exception as e:
                db.rollback()
                logger.error(f"Mission recap failed for schedule {schedule.id}: {e}")
    return due_count
```

- [ ] **Step 5: Run the full missions test file**

Run: `cd backend && python -m pytest tests/test_missions.py -v`
Expected: PASS for `TestIsScheduleDue` and `TestRecapScheduleSchema` (DB-backed endpoint tests may skip if PostgreSQL is unavailable — that is expected).

- [ ] **Step 6: Commit**

```bash
git add backend/recap_scheduler.py backend/mission_recap.py backend/tests/test_missions.py
git commit -m "feat(missions): scheduler fires per recap schedule (recurring + one-shot)"
```

---

## Task 5: Recap-schedules CRUD endpoints

**Files:**
- Modify: `backend/routers/missions.py` (import line 12 + 14; add endpoints after `delete_event`, ~line 423)
- Test: `backend/tests/test_missions.py`

- [ ] **Step 1: Write failing endpoint tests**

In `backend/tests/test_missions.py`, add at the end of the file:

```python
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
    listing = await client.get(
        f"/api/automations/missions/{mid}/recap-schedules", cookies=member_cookies
    )
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
    deleted = await client.delete(
        f"/api/automations/missions/{mid}/recap-schedules/{sid}", cookies=member_cookies
    )
    assert deleted.status_code == 200
    listing = await client.get(
        f"/api/automations/missions/{mid}/recap-schedules", cookies=member_cookies
    )
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_missions.py::test_create_list_recap_schedule -v`
Expected: FAIL (404 Not Found, endpoint does not exist) — or skip if PostgreSQL is unavailable.

- [ ] **Step 3: Implement the endpoints**

In `backend/routers/missions.py`, update the model import (line 12) and schema import (line 14):

```python
from database import Agent, Document, Mission, MissionEvent, MissionRecap, MissionRecapSchedule, get_db
```

```python
from schemas.missions import (
    EventCreate,
    EventsBulk,
    EventUpdate,
    MissionChatRequest,
    MissionCreate,
    MissionUpdate,
    RecapScheduleCreate,
    RecapScheduleUpdate,
)
```

Then add, after the `delete_event` function (after line 423):

```python
# --------------------------------------------------------------------------- #
# Recap schedules (recurring + one-shot)
# --------------------------------------------------------------------------- #


def _schedule_detail(s: MissionRecapSchedule) -> dict:
    return {
        "id": s.id,
        "kind": s.kind,
        "weekday": s.weekday,
        "run_date": s.run_date.isoformat() if s.run_date else None,
        "hour": s.hour,
        "enabled": s.enabled,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
    }


@router.get("/api/automations/missions/{mission_id}/recap-schedules")
async def list_recap_schedules(
    mission_id: int, user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    rows = (
        db.query(MissionRecapSchedule)
        .filter(MissionRecapSchedule.mission_id == mission.id)
        .order_by(MissionRecapSchedule.created_at.asc())
        .all()
    )
    return {"schedules": [_schedule_detail(s) for s in rows]}


@router.post("/api/automations/missions/{mission_id}/recap-schedules")
async def create_recap_schedule(
    mission_id: int,
    body: RecapScheduleCreate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    if mission.status != "active":
        raise HTTPException(status_code=400, detail="Mission archivée : modification impossible")
    schedule = MissionRecapSchedule(
        mission_id=mission.id,
        company_id=mission.company_id,
        kind=body.kind,
        weekday=body.weekday if body.kind == "recurring" else None,
        run_date=body.run_date if body.kind == "once" else None,
        hour=body.hour,
        enabled=body.enabled,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {"id": schedule.id}


@router.put("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}")
async def update_recap_schedule(
    mission_id: int,
    schedule_id: int,
    body: RecapScheduleUpdate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    if mission.status != "active":
        raise HTTPException(status_code=400, detail="Mission archivée : modification impossible")
    schedule = (
        db.query(MissionRecapSchedule)
        .filter(MissionRecapSchedule.id == schedule_id, MissionRecapSchedule.mission_id == mission.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.kind = body.kind
    schedule.weekday = body.weekday if body.kind == "recurring" else None
    schedule.run_date = body.run_date if body.kind == "once" else None
    schedule.hour = body.hour
    schedule.enabled = body.enabled
    db.commit()
    return {"success": True}


@router.delete("/api/automations/missions/{mission_id}/recap-schedules/{schedule_id}")
async def delete_recap_schedule(
    mission_id: int,
    schedule_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    user_id = int(user_id)
    membership = require_role(user_id, db, "member")
    mission = _get_mission_or_404(mission_id, user_id, membership.company_id, db)
    schedule = (
        db.query(MissionRecapSchedule)
        .filter(MissionRecapSchedule.id == schedule_id, MissionRecapSchedule.mission_id == mission.id)
        .first()
    )
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    db.delete(schedule)
    db.commit()
    return {"success": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_missions.py -k recap_schedule -v`
Expected: PASS (or skip if PostgreSQL unavailable). If running against a local PostgreSQL, all 3 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/missions.py backend/tests/test_missions.py
git commit -m "feat(missions): recap-schedules CRUD endpoints"
```

---

## Task 6: Frontend — `RecapSchedules` component + i18n

**Files:**
- Create: `frontend/components/automations/missions/RecapSchedules.js`
- Modify: `frontend/components/automations/missions/SettingsTab.js`
- Modify: `frontend/public/locales/fr/automations.json`, `frontend/public/locales/en/automations.json`

- [ ] **Step 1: Add i18n keys (fr)**

In `frontend/public/locales/fr/automations.json`, inside `missions.settings`, add a `recapSchedules` object (keep the existing `weekdays` map; the component reuses it):

```json
"recapSchedules": {
  "title": "Récaps planifiés",
  "add": "Ajouter un récap",
  "empty": "Aucun récap planifié.",
  "recurring": "Récurrent",
  "once": "Ponctuel",
  "weekday": "Jour",
  "date": "Date",
  "hour": "Heure",
  "enabled": "Activé",
  "saved": "Récap planifié enregistré",
  "deleted": "Récap planifié supprimé"
}
```

- [ ] **Step 2: Add i18n keys (en)**

In `frontend/public/locales/en/automations.json`, inside `missions.settings`, add:

```json
"recapSchedules": {
  "title": "Scheduled recaps",
  "add": "Add a recap",
  "empty": "No scheduled recap yet.",
  "recurring": "Recurring",
  "once": "One-shot",
  "weekday": "Day",
  "date": "Date",
  "hour": "Hour",
  "enabled": "Enabled",
  "saved": "Scheduled recap saved",
  "deleted": "Scheduled recap deleted"
}
```

- [ ] **Step 3: Create the `RecapSchedules` component**

Create `frontend/components/automations/missions/RecapSchedules.js`:

```javascript
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Plus, Trash2 } from 'lucide-react';
import api from '../../../lib/api';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default function RecapSchedules({ missionId }) {
  const { t } = useTranslation('automations');
  const [schedules, setSchedules] = useState([]);

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/missions/${missionId}/recap-schedules`);
      setSchedules(res.data.schedules || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [missionId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    try {
      await api.post(`/api/automations/missions/${missionId}/recap-schedules`, {
        kind: 'recurring',
        weekday: 0,
        hour: 8,
        enabled: true,
      });
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const save = async (id, payload) => {
    try {
      await api.put(`/api/automations/missions/${missionId}/recap-schedules/${id}`, payload);
      toast.success(t('missions.settings.recapSchedules.saved'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/api/automations/missions/${missionId}/recap-schedules/${id}`);
      toast.success(t('missions.settings.recapSchedules.deleted'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const weekdays = t('missions.settings.weekdays', { returnObjects: true });

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-gray-800">
          {t('missions.settings.recapSchedules.title')}
        </p>
        <button
          onClick={add}
          className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-700 text-sm font-medium rounded-button hover:border-primary-300"
        >
          <Plus className="w-4 h-4" />
          {t('missions.settings.recapSchedules.add')}
        </button>
      </div>

      {schedules.length === 0 ? (
        <p className="text-sm text-gray-400 py-4">{t('missions.settings.recapSchedules.empty')}</p>
      ) : (
        <div className="space-y-2">
          {schedules.map((s) => (
            <ScheduleRow
              key={s.id}
              schedule={s}
              weekdays={weekdays}
              onSave={save}
              onDelete={remove}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ScheduleRow({ schedule, weekdays, onSave, onDelete, t }) {
  const [kind, setKind] = useState(schedule.kind);
  const [weekday, setWeekday] = useState(schedule.weekday ?? 0);
  const [runDate, setRunDate] = useState(schedule.run_date ?? todayIso());
  const [hour, setHour] = useState(schedule.hour);
  const [enabled, setEnabled] = useState(schedule.enabled);

  useEffect(() => {
    setKind(schedule.kind);
    setWeekday(schedule.weekday ?? 0);
    setRunDate(schedule.run_date ?? todayIso());
    setHour(schedule.hour);
    setEnabled(schedule.enabled);
  }, [schedule]);

  const commit = (overrides = {}) => {
    const next = { kind, weekday, run_date: runDate, hour, enabled, ...overrides };
    onSave(schedule.id, {
      kind: next.kind,
      weekday: next.kind === 'recurring' ? parseInt(next.weekday, 10) : null,
      run_date: next.kind === 'once' ? next.run_date : null,
      hour: parseInt(next.hour, 10),
      enabled: next.enabled,
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-card">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => {
          setEnabled(e.target.checked);
          commit({ enabled: e.target.checked });
        }}
        title={t('missions.settings.recapSchedules.enabled')}
      />

      <select
        value={kind}
        onChange={(e) => {
          setKind(e.target.value);
          commit({ kind: e.target.value });
        }}
        className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
      >
        <option value="recurring">{t('missions.settings.recapSchedules.recurring')}</option>
        <option value="once">{t('missions.settings.recapSchedules.once')}</option>
      </select>

      {kind === 'recurring' ? (
        <select
          value={weekday}
          onChange={(e) => setWeekday(e.target.value)}
          onBlur={() => commit()}
          className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
        >
          {[0, 1, 2, 3, 4, 5, 6].map((d) => (
            <option key={d} value={d}>
              {weekdays[String(d)]}
            </option>
          ))}
        </select>
      ) : (
        <input
          type="date"
          value={runDate}
          onChange={(e) => setRunDate(e.target.value)}
          onBlur={() => commit()}
          className="px-2 py-1.5 border border-gray-300 rounded-button text-sm"
        />
      )}

      <select
        value={hour}
        onChange={(e) => setHour(e.target.value)}
        onBlur={() => commit()}
        className="px-2 py-1.5 border border-gray-300 rounded-button text-sm bg-white"
      >
        {Array.from({ length: 24 }, (_, h) => (
          <option key={h} value={h}>
            {String(h).padStart(2, '0')}:00
          </option>
        ))}
      </select>

      <button
        onClick={() => onDelete(schedule.id)}
        className="p-1.5 text-gray-300 hover:text-red-500 ml-auto"
      >
        <Trash2 className="w-4 h-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Wire `RecapSchedules` into `SettingsTab` and drop the old recap fields**

In `frontend/components/automations/missions/SettingsTab.js`:

1. Add the import near the top:

```javascript
import RecapSchedules from './RecapSchedules';
```

2. Remove `recap_enabled`, `recap_weekday`, `recap_hour` from both `useState` initial `form` (lines 13-15) and the `useEffect` resync `setForm` (lines 28-30), so `form` is just `{ name, objective, agent_id, status }`.

3. In `save`, drop the `recap_weekday` / `recap_hour` parsing so `payload` becomes:

```javascript
    const payload = {
      ...merged,
      agent_id: merged.agent_id ? parseInt(merged.agent_id, 10) : null,
    };
```

4. Replace the recap checkbox + weekday/hour block (the `<label>` with `recap_enabled` and the `<div className="flex gap-4">` block, lines 76-118) with:

```javascript
      <RecapSchedules missionId={mission.id} />
```

Leave the companion `<select>`, the save/archive/delete buttons, and `weekdays` usage handling as-is (note: `weekdays` is still read inside `RecapSchedules`, not `SettingsTab`, so the `const weekdays = ...` line in SettingsTab can be removed).

> **Backend note:** `MissionUpdate` still defines `recap_enabled` / `recap_weekday` / `recap_hour` with defaults, so omitting them from the payload is valid (they fall back to defaults and no longer affect scheduling). No backend change needed for this task.

- [ ] **Step 5: Lint the frontend changes**

Run: `cd frontend && npx next lint --file components/automations/missions/RecapSchedules.js --file components/automations/missions/SettingsTab.js`
Expected: `✔ No ESLint warnings or errors`

- [ ] **Step 6: Verify i18n JSON is valid**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('public/locales/fr/automations.json','utf8')); JSON.parse(require('fs').readFileSync('public/locales/en/automations.json','utf8')); console.log('ok')"`
Expected: prints `ok`

- [ ] **Step 7: Commit**

```bash
git add frontend/components/automations/missions/RecapSchedules.js frontend/components/automations/missions/SettingsTab.js frontend/public/locales/fr/automations.json frontend/public/locales/en/automations.json
git commit -m "feat(missions): recap schedules UI (recurring + one-shot) in Settings"
```

---

## Self-Review

**Spec coverage:**
- Multiple schedules per mission → Task 1 (model), Task 2 (table), Task 5 (CRUD). ✓
- Recurring (weekday+hour) / one-shot (date+hour) → Task 3 (schema validation), Task 4 (due logic), Task 6 (UI). ✓
- Hour-level precision, hourly tick unchanged → Task 4 keeps `IntervalTrigger(hours=1)`; `_is_schedule_due` compares `now.hour`. ✓
- Migrate existing config → Task 2 backfill INSERT. ✓
- `schedule_id` link on `mission_recaps` → Task 1 (column), Task 2 (FK), Task 4 (stamped via `process_mission_recap`). ✓
- Keep legacy `Mission.recap_*` columns → not dropped anywhere; Task 6 just stops sending them from the UI. ✓
- API scoping + archived rejection → Task 5 mirrors sibling endpoints. ✓
- Conditional validation → Task 3 `model_validator`. ✓
- Frontend list component, reuse `weekdays` → Task 6. ✓
- Tests (schema, due-check, endpoints, migration) → Tasks 3/4/5 cover schema, due-check, endpoints. Migration backfill is verified manually on deploy (no offline pytest harness for Alembic in this repo; the existing 0007 migration is likewise untested in pytest). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `_is_schedule_due(schedule, mission, now, db)` signature matches its call in `_run_scheduled_mission_recaps` and the tests. `process_mission_recap(..., schedule_id=None)` matches its call. `RecapScheduleCreate` / `RecapScheduleUpdate` names match imports in `routers/missions.py`. `_schedule_detail` keys (`kind`, `weekday`, `run_date`, `hour`, `enabled`, `last_run_at`) match what the frontend reads (`schedule.kind`, `schedule.weekday`, `schedule.run_date`, `schedule.hour`, `schedule.enabled`). ✓
