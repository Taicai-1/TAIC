# Recap Timing Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to configure per-agent recap frequency (6h, daily, 2days, weekly) and send hour (0-23), with an internal APScheduler replacing the external Cloud Scheduler dependency.

**Architecture:** Two new columns on `agents` (`recap_frequency`, `recap_hour`). A new `recap_scheduler.py` module runs an hourly APScheduler job that checks which agents are due for a recap by comparing their settings against `weekly_recap_logs.sent_at`. The existing `weekly_recap.py` gains a `days_back` parameter to adjust the data window per frequency.

**Tech Stack:** APScheduler 3.x, FastAPI, SQLAlchemy, PostgreSQL, Next.js/React

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/database.py` | Modify | Add `recap_frequency`, `recap_hour` columns to Agent model + `ensure_columns` entries |
| `backend/migrations/007_add_recap_timing.sql` | Create | SQL migration for new columns |
| `backend/recap_scheduler.py` | Create | APScheduler setup, hourly tick logic, agent eligibility check |
| `backend/weekly_recap.py` | Modify | Add `days_back` parameter to `fetch_weekly_messages` |
| `backend/main.py` | Modify | Start/stop scheduler in startup/shutdown events |
| `backend/routers/agents.py` | Modify | Accept, validate, persist, return new fields |
| `backend/requirements.txt` | Modify | Add `apscheduler` |
| `frontend/pages/index.js` | Modify | Add frequency + hour dropdowns in recap config panel |
| `frontend/pages/agents.js` | Modify | Add new fields to form state and serialization |
| `frontend/public/locales/fr/agents.json` | Modify | Add i18n keys for new controls |

---

### Task 1: Database — Add columns to Agent model

**Files:**
- Modify: `backend/database.py:315-318` (Agent model, weekly recap section)
- Modify: `backend/database.py:616-644` (ensure_columns migrations list)
- Create: `backend/migrations/007_add_recap_timing.sql`

- [ ] **Step 1: Add columns to Agent model**

In `backend/database.py`, after line 318 (`weekly_recap_recipients`), add:

```python
    recap_frequency = Column(String(20), default="weekly", nullable=False)
    recap_hour = Column(Integer, default=9, nullable=False)
```

- [ ] **Step 2: Add ensure_columns entries**

In `backend/database.py`, inside `ensure_columns()`, add two new entries to the `migrations` list (after the `weekly_recap_recipients` entry around line 619):

```python
        ("agents", "recap_frequency", "VARCHAR(20) NOT NULL DEFAULT 'weekly'"),
        ("agents", "recap_hour", "INTEGER NOT NULL DEFAULT 9"),
```

- [ ] **Step 3: Create SQL migration file**

Create `backend/migrations/007_add_recap_timing.sql`:

```sql
-- Add recap timing customization columns to agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_frequency VARCHAR(20) NOT NULL DEFAULT 'weekly';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS recap_hour INTEGER NOT NULL DEFAULT 9;
```

- [ ] **Step 4: Commit**

```bash
git add backend/database.py backend/migrations/007_add_recap_timing.sql
git commit -m "feat(recap): add recap_frequency and recap_hour columns to Agent model"
```

---

### Task 2: Backend API — Accept and return new fields

**Files:**
- Modify: `backend/routers/agents.py:139-143` (create_agent form params)
- Modify: `backend/routers/agents.py:200-214` (create_agent ORM instantiation)
- Modify: `backend/routers/agents.py:88-91,115-117,305-309` (agent serialization in list/detail)
- Modify: `backend/routers/agents.py:493-497` (update_agent form params)
- Modify: `backend/routers/agents.py:530-535` (update_agent field assignment)

- [ ] **Step 1: Add form params to create_agent**

In `backend/routers/agents.py`, after the `weekly_recap_recipients` param (line 143), add:

```python
    recap_frequency: str = Form("weekly"),
    recap_hour: str = Form("9"),
```

- [ ] **Step 2: Add validation and ORM assignment in create_agent**

After the `weekly_recap_recipients` assignment (line 212-214), add:

```python
            recap_frequency=recap_frequency if recap_frequency in ("6h", "daily", "2days", "weekly") else "weekly",
            recap_hour=max(0, min(23, int(recap_hour))) if recap_hour.isdigit() else 9,
```

- [ ] **Step 3: Add fields to agent serialization (list endpoints)**

In the two agent list serializations (around lines 88-91 and 115-117), after `"weekly_recap_enabled"`, add:

```python
                "recap_frequency": a.recap_frequency,
                "recap_hour": a.recap_hour,
```

- [ ] **Step 4: Add fields to agent detail serialization**

In the agent detail response (around lines 305-309), after `"weekly_recap_recipients"`, add:

```python
                    "recap_frequency": agent.recap_frequency,
                    "recap_hour": agent.recap_hour,
```

- [ ] **Step 5: Add form params to update_agent**

In `backend/routers/agents.py`, after the `weekly_recap_recipients` param in `update_agent` (line 497), add:

```python
    recap_frequency: str = Form("weekly"),
    recap_hour: str = Form("9"),
```

- [ ] **Step 6: Add field assignment in update_agent**

After the `weekly_recap_recipients` assignment (line 533-535), add:

```python
        agent.recap_frequency = recap_frequency if recap_frequency in ("6h", "daily", "2days", "weekly") else "weekly"
        agent.recap_hour = max(0, min(23, int(recap_hour))) if recap_hour.isdigit() else 9
```

- [ ] **Step 7: Commit**

```bash
git add backend/routers/agents.py
git commit -m "feat(recap): accept and return recap_frequency and recap_hour in agent endpoints"
```

---

### Task 3: Adapt data window in weekly_recap.py

**Files:**
- Modify: `backend/weekly_recap.py:28-44` (fetch_weekly_messages)
- Modify: `backend/weekly_recap.py:177-187` (process_agent_recap)

- [ ] **Step 1: Add days_back parameter to fetch_weekly_messages**

Replace the function signature and cutoff line (lines 28-30):

Old:
```python
def fetch_weekly_messages(agent_id: int, db: Session) -> list[dict]:
    """Fetch all messages from the last 7 days for a given agent."""
    cutoff = datetime.utcnow() - timedelta(days=7)
```

New:
```python
def fetch_weekly_messages(agent_id: int, db: Session, days_back: int = 7) -> list[dict]:
    """Fetch all messages from the last N days for a given agent."""
    cutoff = datetime.utcnow() - timedelta(days=days_back)
```

- [ ] **Step 2: Add helper to map frequency to days_back**

Add this function after `get_model_id_for_agent` (after line 25):

```python
FREQUENCY_DAYS = {"6h": 1, "daily": 1, "2days": 2, "weekly": 7}


def get_days_back(agent: Agent) -> int:
    """Return the number of days of data to fetch based on agent recap frequency."""
    freq = getattr(agent, "recap_frequency", "weekly")
    return FREQUENCY_DAYS.get(freq, 7)
```

- [ ] **Step 3: Use days_back in process_agent_recap**

In `process_agent_recap`, replace line 185:

Old:
```python
        messages = fetch_weekly_messages(agent.id, db)
```

New:
```python
        days_back = get_days_back(agent)
        messages = fetch_weekly_messages(agent.id, db, days_back=days_back)
```

- [ ] **Step 4: Commit**

```bash
git add backend/weekly_recap.py
git commit -m "feat(recap): adapt data window based on agent recap_frequency"
```

---

### Task 4: Add APScheduler dependency

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add apscheduler to requirements**

Add at the end of `backend/requirements.txt`:

```
apscheduler==3.11.0
```

- [ ] **Step 2: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: add apscheduler dependency for recap scheduling"
```

---

### Task 5: Create recap_scheduler.py

**Files:**
- Create: `backend/recap_scheduler.py`

- [ ] **Step 1: Create the scheduler module**

Create `backend/recap_scheduler.py`:

```python
"""
Internal scheduler for recap emails.
Runs an hourly job that checks which agents are due for a recap
based on their recap_frequency and recap_hour settings.
"""

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz

from database import SessionLocal, Agent, WeeklyRecapLog

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

PARIS_TZ = pytz.timezone("Europe/Paris")


def _get_send_hours(recap_hour: int) -> set[int]:
    """For 6h frequency, return the 4 send hours in a day."""
    return {(recap_hour + offset) % 24 for offset in (0, 6, 12, 18)}


def _is_due(agent: Agent, now: datetime, db) -> bool:
    """Check if an agent is due for a recap right now."""
    freq = agent.recap_frequency or "weekly"
    hour = agent.recap_hour if agent.recap_hour is not None else 9
    current_hour = now.hour

    if freq == "6h":
        if current_hour not in _get_send_hours(hour):
            return False
    elif freq in ("daily", "2days", "weekly"):
        if current_hour != hour:
            return False
    else:
        return False

    if freq == "weekly" and now.weekday() != 0:  # Monday = 0
        return False

    # Check last send time to avoid duplicates
    last_log = (
        db.query(WeeklyRecapLog)
        .filter(
            WeeklyRecapLog.agent_id == agent.id,
            WeeklyRecapLog.status.in_(["success", "no_data"]),
        )
        .order_by(WeeklyRecapLog.sent_at.desc())
        .first()
    )

    if last_log and last_log.sent_at:
        min_gap = {"6h": timedelta(hours=5), "daily": timedelta(hours=23), "2days": timedelta(hours=47), "weekly": timedelta(days=6)}
        if now.replace(tzinfo=None) - last_log.sent_at < min_gap.get(freq, timedelta(days=6)):
            return False

    return True


def _run_scheduled_recaps():
    """Hourly tick: find and process all due recaps."""
    logger.info("Recap scheduler tick starting")
    now = datetime.now(PARIS_TZ)
    db = SessionLocal()

    try:
        agents = db.query(Agent).filter(Agent.weekly_recap_enabled == True).all()
        due_count = 0

        for agent in agents:
            if _is_due(agent, now, db):
                due_count += 1
                try:
                    from weekly_recap import process_agent_recap

                    result = process_agent_recap(agent, db)
                    logger.info(f"Recap for agent {agent.id} ({agent.name}): {result.get('status')}")
                except Exception as e:
                    logger.error(f"Recap failed for agent {agent.id}: {e}")

        logger.info(f"Recap scheduler tick done: {due_count} agents processed out of {len(agents)} enabled")
    except Exception as e:
        logger.error(f"Recap scheduler tick failed: {e}")
    finally:
        db.close()


def start_scheduler():
    """Start the background scheduler with an hourly recap job."""
    scheduler.add_job(
        _run_scheduled_recaps,
        trigger=IntervalTrigger(hours=1),
        id="recap_hourly_tick",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Recap scheduler started (hourly tick)")


def shutdown_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Recap scheduler shut down")
```

- [ ] **Step 2: Commit**

```bash
git add backend/recap_scheduler.py
git commit -m "feat(recap): create internal APScheduler for per-agent recap timing"
```

---

### Task 6: Integrate scheduler into FastAPI startup

**Files:**
- Modify: `backend/main.py:330-355` (startup_event)

- [ ] **Step 1: Add scheduler start to startup_event**

In `backend/main.py`, at the end of `startup_event()` (after line 352, after `"Database initialization completed successfully"`), add:

```python
    # Start internal recap scheduler
    try:
        from recap_scheduler import start_scheduler
        start_scheduler()
        logger.info("Recap scheduler started")
    except Exception as e:
        logger.warning(f"Recap scheduler failed to start: {e}")
```

- [ ] **Step 2: Add shutdown event**

After the `startup_event` function (after line 354), add:

```python
@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down background services."""
    try:
        from recap_scheduler import shutdown_scheduler
        shutdown_scheduler()
    except Exception as e:
        logger.warning(f"Recap scheduler shutdown error: {e}")
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat(recap): start/stop recap scheduler on app lifecycle"
```

---

### Task 7: Frontend — Add i18n keys

**Files:**
- Modify: `frontend/public/locales/fr/agents.json:77-86` (weeklyRecap section)

- [ ] **Step 1: Add i18n keys**

In `frontend/public/locales/fr/agents.json`, inside the `"weeklyRecap"` object (after `"recipientsHelpText"` on line 85), add:

```json
      "frequencyLabel": "Fréquence",
      "frequencyOptions": {
        "6h": "Toutes les 6 heures",
        "daily": "1 fois par jour",
        "2days": "1 fois tous les 2 jours",
        "weekly": "1 fois par semaine"
      },
      "hourLabel": "Heure d'envoi",
      "hourSuffix": "h"
```

- [ ] **Step 2: Update helpText to be frequency-aware**

Replace the current `helpText` value (line 79):

Old:
```json
      "helpText": "Recevez chaque lundi par email un résumé IA basé sur les conversations et documents de traçabilité.",
```

New:
```json
      "helpText": "Recevez par email un résumé IA basé sur les conversations et documents de traçabilité.",
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/agents.json
git commit -m "feat(recap): add i18n keys for frequency and hour selectors"
```

---

### Task 8: Frontend — Add dropdowns to index.js (agent detail page)

**Files:**
- Modify: `frontend/pages/index.js:57-62` (form state initialization)
- Modify: `frontend/pages/index.js:134-139` (form population from API)
- Modify: `frontend/pages/index.js:270-276` (form serialization for save)
- Modify: `frontend/pages/index.js:989-990` (recap config panel UI)

- [ ] **Step 1: Add fields to form state initialization**

In `frontend/pages/index.js`, update the form state initialization (lines 57-62). Replace:

```javascript
    neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "",
    weekly_recap_recipients: []
```

With:

```javascript
    neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "",
    weekly_recap_recipients: [], recap_frequency: "weekly", recap_hour: 9
```

- [ ] **Step 2: Add fields to form population from API**

In `frontend/pages/index.js`, after the `weekly_recap_recipients` line (line 139), add:

```javascript
        recap_frequency: agent.recap_frequency || "weekly",
        recap_hour: agent.recap_hour !== undefined ? agent.recap_hour : 9,
```

- [ ] **Step 3: Add fields to form serialization**

In `frontend/pages/index.js`, after the `weekly_recap_recipients` serialization (line 276), add:

```javascript
      formData.append("recap_frequency", form.recap_frequency);
      formData.append("recap_hour", String(form.recap_hour));
```

- [ ] **Step 4: Add frequency and hour dropdowns to the UI**

In `frontend/pages/index.js`, inside the `{form.weekly_recap_enabled && (` block (line 989), add the following right after `<>` and before the prompt textarea `<div className="mt-3">` (line 991):

```jsx
                {/* Frequency + Hour selectors */}
                <div className="mt-3 grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-gray-600 mb-1 block">
                      {t('agents:form.weeklyRecap.frequencyLabel')}
                    </label>
                    <select
                      className="w-full px-3 py-2 border border-amber-200 rounded-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm"
                      value={form.recap_frequency}
                      onChange={e => setForm(f => ({ ...f, recap_frequency: e.target.value }))}
                    >
                      {["6h", "daily", "2days", "weekly"].map(freq => (
                        <option key={freq} value={freq}>
                          {t(`agents:form.weeklyRecap.frequencyOptions.${freq}`)}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-gray-600 mb-1 block">
                      {t('agents:form.weeklyRecap.hourLabel')}
                    </label>
                    <select
                      className="w-full px-3 py-2 border border-amber-200 rounded-sm focus:border-amber-500 focus:ring-2 focus:ring-amber-200 transition-all outline-none bg-white text-sm"
                      value={form.recap_hour}
                      onChange={e => setForm(f => ({ ...f, recap_hour: parseInt(e.target.value, 10) }))}
                    >
                      {Array.from({ length: 24 }, (_, i) => (
                        <option key={i} value={i}>{i}{t('agents:form.weeklyRecap.hourSuffix')}</option>
                      ))}
                    </select>
                  </div>
                </div>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/pages/index.js
git commit -m "feat(recap): add frequency and hour selectors to agent detail page"
```

---

### Task 9: Frontend — Add fields to agents.js (create form)

**Files:**
- Modify: `frontend/pages/agents.js:29` (form state)
- Modify: `frontend/pages/agents.js:442-446` (form serialization)

- [ ] **Step 1: Add fields to form state**

In `frontend/pages/agents.js`, update the form state initialization (line 29). Replace:

```javascript
  const [form, setForm] = useState({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [] });
```

With:

```javascript
  const [form, setForm] = useState({ name: "", contexte: "", biographie: "", profile_photo: null, email: "", password: "", type: 'conversationnel', email_tags: [], neo4j_enabled: false, neo4j_person_name: "", neo4j_depth: 1, weekly_recap_enabled: false, weekly_recap_prompt: "", weekly_recap_recipients: [], recap_frequency: "weekly", recap_hour: 9 });
```

- [ ] **Step 2: Add fields to form serialization**

In `frontend/pages/agents.js`, after the `weekly_recap_recipients` append (line 446), add:

```javascript
                    formData.append("recap_frequency", form.recap_frequency);
                    formData.append("recap_hour", String(form.recap_hour));
```

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/agents.js
git commit -m "feat(recap): add recap timing fields to agent creation form"
```

---

### Task 10: Verify and final commit

- [ ] **Step 1: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors related to new code.

- [ ] **Step 2: Run backend syntax check**

Run: `cd backend && python -c "import database; import recap_scheduler; import weekly_recap; print('OK')"`
Expected: `OK` (no import errors)

- [ ] **Step 3: Verify the complete file list**

Confirm all files are committed:
- `backend/database.py` — 2 new columns + 2 ensure_columns entries
- `backend/migrations/007_add_recap_timing.sql` — new file
- `backend/routers/agents.py` — new form params, validation, serialization
- `backend/weekly_recap.py` — `days_back` param + `get_days_back` helper
- `backend/requirements.txt` — `apscheduler`
- `backend/recap_scheduler.py` — new file
- `backend/main.py` — scheduler start/stop
- `frontend/pages/index.js` — form state, population, serialization, UI dropdowns
- `frontend/pages/agents.js` — form state, serialization
- `frontend/public/locales/fr/agents.json` — new i18n keys

Run: `git status`
Expected: Clean working tree.
