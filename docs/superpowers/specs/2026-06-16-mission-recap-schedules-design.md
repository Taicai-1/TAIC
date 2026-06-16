# Mission recap schedules — design

**Date:** 2026-06-16
**Status:** Approved, pending implementation
**Branch:** `feature/missions`

## Problem

A mission today has exactly one recap configuration, baked into the `missions`
row: `recap_enabled` (bool), `recap_weekday` (0–6) and `recap_hour` (0–23,
Europe/Paris). It is always a single recurring weekly recap. Users want to:

- create **several** recaps per mission,
- choose per recap whether it is **recurring** (weekday + hour) or **one-shot**
  (date + hour).

## Decisions (from brainstorming)

1. **Multiple schedules per mission** → a new table, not the existing columns.
2. **Hour-level precision** (00–23h), no minutes → the hourly scheduler tick is
   unchanged; no infra change.
3. **Migrate** existing config → every mission with `recap_enabled=true` gets an
   equivalent `recurring` schedule created by the migration. Nothing is lost.

## Data model

New table **`mission_recap_schedules`** (the *schedules*; distinct from
`mission_recaps`, which stores *generated* recap output):

| column        | type                        | role                                    |
|---------------|-----------------------------|-----------------------------------------|
| `id`          | int PK                      |                                         |
| `mission_id`  | FK → missions (CASCADE)     |                                         |
| `company_id`  | int FK → companies          | tenant isolation (matches sibling rows) |
| `kind`        | `"recurring"` \| `"once"`   | schedule type                           |
| `weekday`     | int 0–6, nullable           | day of week (recurring only)            |
| `run_date`    | Date, nullable              | run date (one-shot only)                |
| `hour`        | int 0–23, NOT NULL          | full hour, Europe/Paris                 |
| `enabled`     | bool, default true          | activate/deactivate without deleting    |
| `last_run_at` | DateTime, nullable          | anti-duplicate guard                    |
| `created_at`  | DateTime                    |                                         |

The existing `Mission.recap_enabled / recap_weekday / recap_hour` columns are
**kept** (no drop — avoids breaking templates/agents code paths and the
factory/tests) but no longer drive the scheduler.

`mission_recaps` gains a nullable `schedule_id` FK linking a generated recap to
the schedule that produced it (`null` = manual or legacy).

### Migration

For each mission with `recap_enabled = true`, insert one
`mission_recap_schedules` row: `kind="recurring"`, `weekday=recap_weekday`,
`hour=recap_hour`, `enabled=true`. Both a SQLAlchemy auto-migration entry (the
`database.py` column-add list pattern) and an Alembic revision, consistent with
`0007_missions.py`.

## Scheduler logic

`recap_scheduler.py`:

- `_run_scheduled_mission_recaps(now, db)` iterates **enabled schedules**
  (joined to their active missions) instead of iterating missions.
- New `_is_schedule_due(schedule, now, db)`:
  - **common guards:** `schedule.enabled`, mission `status == "active"`, mission
    has `agent_id`, and `now.hour == schedule.hour`.
  - **recurring:** `now.weekday() == schedule.weekday`, and (`last_run_at` is
    null OR `now - last_run_at >= 6 days`).
  - **once:** `now.date() == schedule.run_date` and `last_run_at` is null.
- After a successful/no_data run: set `schedule.last_run_at = now`; for `once`
  also set `schedule.enabled = false` (it is finished). The created
  `MissionRecap` is stamped with `schedule_id`.
- Tick stays **hourly** (`IntervalTrigger(hours=1)`), unchanged.

`_is_mission_due` (old mission-level due check) is removed/replaced once the
schedule path is live; `process_mission_recap` is unchanged (it already derives
the period from `run_date` and does not read `recap_weekday`).

## API

New CRUD block in `routers/missions.py`, same scoping as sibling mission
endpoints (`require_role(..., "member")` + `_get_mission_or_404`, and reject
when the mission is archived):

- `GET    /api/automations/missions/{mission_id}/recap-schedules`
- `POST   /api/automations/missions/{mission_id}/recap-schedules`
- `PUT    /api/automations/missions/{mission_id}/recap-schedules/{schedule_id}`
- `DELETE /api/automations/missions/{mission_id}/recap-schedules/{schedule_id}`

Pydantic schemas in `schemas/missions.py` with **conditional validation**:

- `kind == "recurring"` requires `weekday` (0–6); `run_date` ignored/null.
- `kind == "once"` requires `run_date`; `weekday` ignored/null.
- `hour` in 0–23.

A `RecapScheduleCreate` / `RecapScheduleUpdate` pair (update allows toggling
`enabled` and editing fields).

## Frontend

`SettingsTab.js`: the current recap block (checkbox + single weekday + single
hour) is replaced by a **list of schedules** plus an "Add recap" button,
extracted into a dedicated `RecapSchedules.js` component (SettingsTab already
handles name/objective/companion/archive/delete — keep it focused).

Each schedule row:

- enabled/disabled toggle,
- radio **Recurring** / **One-shot**:
  - recurring → `<select>` weekday + `<select>` hour,
  - one-shot → `<input type="date">` + `<select>` hour,
- delete button.

The rest of `SettingsTab` (mission fields, archive, delete) is unchanged.

New i18n keys under `missions.settings.*` (fr + en) for the schedule UI;
reuse the existing `weekdays` map.

## Out of scope (YAGNI)

- Minute-level precision.
- Per-schedule custom recap content / templates.
- Timezones other than Europe/Paris.
- Dropping the legacy `Mission.recap_*` columns (defer to a later cleanup).

## Testing

- Schema validation: recurring requires weekday, once requires run_date, hour
  bounds (extend `test_missions.py`).
- `_is_schedule_due`: recurring due/not-due (weekday/hour match, 6-day dedup),
  once due then disabled after run, guards (disabled, archived, no companion).
- Endpoint integration: create/list/update/delete scoped to mission + company,
  archived mission rejected.
- Migration: a mission with `recap_enabled=true` yields one recurring schedule.
