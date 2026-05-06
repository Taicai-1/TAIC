# Recap Timing Customization

## Context

The weekly recap currently fires every Monday at 9 AM via an external Cloud Scheduler hitting `/api/weekly-recap/trigger`. There is no per-agent control over frequency or send hour. Users want to choose how often they receive recaps and at what time.

## Requirements

- Users can select a recap frequency per agent: every 6 hours, daily, every 2 days, or weekly
- Users can select the send hour (0-23) per agent
- The scheduler runs inside the FastAPI process (no external cron dependency for timing)
- The existing batch trigger endpoint remains functional as a manual/fallback mechanism
- Data window adapts to frequency (24h for 6h/daily, 2 days for 2days, 7 days for weekly)

## Database Changes

### New columns on `agents` table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `recap_frequency` | `VARCHAR(20)` | `'weekly'` | One of: `6h`, `daily`, `2days`, `weekly` |
| `recap_hour` | `INTEGER` | `9` | Hour of day (0-23) for send time |

### Migration

File: `backend/migrations/010_add_recap_timing.sql`

```sql
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_frequency VARCHAR(20) NOT NULL DEFAULT 'weekly';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_hour INTEGER NOT NULL DEFAULT 9;
```

## Frequency Presets

| Value | Label (FR) | Behavior | Data Window |
|-------|-----------|----------|-------------|
| `6h` | Toutes les 6 heures | Sends at recap_hour, +6, +12, +18 | Last 24 hours |
| `daily` | 1 fois par jour | Sends at recap_hour every day | Last 24 hours |
| `2days` | 1 fois tous les 2 jours | Sends at recap_hour every other day | Last 2 days |
| `weekly` | 1 fois par semaine | Sends at recap_hour on Monday | Last 7 days |

## Backend Changes

### 1. Database model (`backend/database.py`)

Add to the `Agent` class:

```python
recap_frequency = Column(String(20), default="weekly", nullable=False)
recap_hour = Column(Integer, default=9, nullable=False)
```

### 2. Scheduler (`backend/recap_scheduler.py`) — new file

- Uses `apscheduler` (`AsyncIOScheduler` with `AsyncIO` event loop)
- Registers a single `IntervalTrigger` job that runs **every hour**
- On each tick:
  1. Query all agents where `weekly_recap_enabled = True`
  2. For each agent, determine if now is a valid send time:
     - Get current hour (Europe/Paris timezone)
     - Check if current hour matches one of the agent's send hours based on frequency
     - For `6h`: send if current hour is in `{recap_hour, (recap_hour+6)%24, (recap_hour+12)%24, (recap_hour+18)%24}`
     - For `daily`: send if current hour == recap_hour
     - For `2days`: send if current hour == recap_hour AND the last recap was sent >= 48h ago (checked via `weekly_recap_logs`)
     - For `weekly`: send if current hour == recap_hour AND today is Monday AND last recap was sent >= 6 days ago
  3. For each qualifying agent, call `process_agent_recap()` from `weekly_recap.py`

### 3. Data window adjustment (`backend/weekly_recap.py`)

Modify `fetch_weekly_messages()` to accept a `days_back` parameter:

- `6h` / `daily` → `days_back=1`
- `2days` → `days_back=2`
- `weekly` → `days_back=7`

Same adjustment for `fetch_traceability_documents()` if it filters by date.

### 4. FastAPI integration (`backend/main.py`)

- Start the scheduler in the `lifespan` context manager
- Shut it down on app shutdown

```python
from recap_scheduler import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app):
    start_scheduler()
    yield
    shutdown_scheduler()
```

### 5. API changes (`backend/routers/agents.py`)

- Accept `recap_frequency` and `recap_hour` in agent create/update endpoints
- Validate `recap_frequency` is one of `["6h", "daily", "2days", "weekly"]`
- Validate `recap_hour` is an integer 0-23
- Return these fields in agent GET responses

### 6. Existing endpoint preservation

`/api/weekly-recap/trigger` continues to work unchanged. It triggers all enabled agents regardless of their schedule — useful for manual triggers and backward compatibility.

## Frontend Changes

### `frontend/pages/index.js` — Recap configuration panel

Add two controls after the `weekly_recap_enabled` toggle (within the existing recap config section around lines 977-1074):

1. **Frequency dropdown** — label: "Fréquence", options:
   - "Toutes les 6 heures" (`6h`)
   - "1 fois par jour" (`daily`)
   - "1 fois tous les 2 jours" (`2days`)
   - "1 fois par semaine" (`weekly`) — default, selected

2. **Hour dropdown** — label: "Heure d'envoi", options: `0h` through `23h`, default `9`

Both controls are disabled when `weekly_recap_enabled` is false.

### `frontend/pages/agents.js` — Agent form

- Add `recap_frequency` and `recap_hour` to form state (defaults: `"weekly"`, `9`)
- Include in form serialization on save

### `frontend/public/locales/fr/agents.json` — i18n

Add keys:
```json
{
  "weeklyRecap.frequencyLabel": "Fréquence",
  "weeklyRecap.frequencyOptions.6h": "Toutes les 6 heures",
  "weeklyRecap.frequencyOptions.daily": "1 fois par jour",
  "weeklyRecap.frequencyOptions.2days": "1 fois tous les 2 jours",
  "weeklyRecap.frequencyOptions.weekly": "1 fois par semaine",
  "weeklyRecap.hourLabel": "Heure d'envoi",
  "weeklyRecap.helpTextCustom": "Le recap sera envoyé selon la fréquence et l'heure choisies."
}
```

## Dependencies

- `apscheduler>=3.10` added to `backend/requirements.txt`

## Files Modified

| File | Change |
|------|--------|
| `backend/database.py` | Add `recap_frequency`, `recap_hour` columns to Agent |
| `backend/recap_scheduler.py` | New file — APScheduler setup and hourly check logic |
| `backend/weekly_recap.py` | Add `days_back` parameter to data-fetching functions |
| `backend/main.py` | Start/stop scheduler in lifespan |
| `backend/routers/agents.py` | Accept and validate new fields in agent endpoints |
| `backend/requirements.txt` | Add `apscheduler` |
| `backend/migrations/010_add_recap_timing.sql` | New migration file |
| `frontend/pages/index.js` | Add frequency and hour dropdowns to recap config panel |
| `frontend/pages/agents.js` | Add fields to form state and serialization |
| `frontend/public/locales/fr/agents.json` | Add i18n keys for new controls |

## Edge Cases

- **First run after enabling:** If no `weekly_recap_logs` entry exists, the agent is eligible on the next matching hour tick
- **Frequency change:** Takes effect on the next scheduler tick. No retroactive sends.
- **Hour change:** Same — takes effect on the next matching tick
- **Timezone:** All time checks use `Europe/Paris` (consistent with existing Cloud Scheduler config)
- **Multiple Cloud Run instances:** APScheduler runs in-process, so multiple instances could cause duplicate sends. Mitigation: the hourly check queries `weekly_recap_logs` for recent sends before processing, effectively deduplicating.
