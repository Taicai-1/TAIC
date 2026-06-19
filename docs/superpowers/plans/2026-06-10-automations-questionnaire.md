# Automations Questionnaire Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the broken "questionnaire" companion type entirely and rebuild questionnaires as a standalone feature in a new Automations page (create questionnaires, invite respondents by email, collect responses via a public form, export responses to a companion's RAG).

**Architecture:** New root entity `Questionnaire` (company-scoped, no link to agents) with questions/responses/answers tables; admin router `backend/routers/automations.py` under `/api/automations/questionnaires`; two public token endpoints in `backend/routers/public.py` (GET form data, POST single submit); frontend page `pages/automations.js` with an extensible tab bar and components under `components/automations/questionnaire/`; public form page `pages/questionnaire/[token].js`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest (backend), Next.js 14 Pages Router + Tailwind + next-i18next + lucide-react + react-hot-toast (frontend).

**Spec:** `docs/superpowers/specs/2026-06-10-automations-questionnaire-design.md`

**Conventions used throughout (read first):**
- Auth dependency pattern: `user_id: int = Depends(verify_token)` then `membership = require_role(user_id, db, "member")`; tenant scope is `membership.company_id` (see `backend/routers/templates.py` as the reference router).
- Frontend API calls: `import api from '../lib/api'` (relative depth varies), relative paths, cookies handled by the shared axios instance.
- Backend test commands run from `backend/`; tests that need PostgreSQL auto-skip if no local PG (CI runs them). Schema unit tests always run.
- Commit after every task. Do NOT add Co-Authored-By lines to commits (user preference).
- All work happens on branch `dev`.

---

## Task 1: Purge the old questionnaire feature from the backend

**Files:**
- Delete: `backend/routers/questionnaires.py`
- Delete: `backend/schemas/questionnaires.py`
- Modify: `backend/main.py` (~lines 521, 546)
- Modify: `backend/routers/public.py` (imports + lines ~96 to end of file)
- Modify: `backend/routers/agents.py` (~lines 170-171, 250-251, 700-701, 716-720)
- Modify: `backend/validation.py` (~line 304)
- Modify: `backend/database.py` (models ~lines 337-383, ensure_columns ~lines 916-918)

Note: `backend/email_service.py:send_questionnaire_invitation_email()` is KEPT unchanged — its signature (`questionnaire_name`, `company_name`, `respondent_name`, `questionnaire_url`) already fits the new feature and it has no agent coupling.

- [ ] **Step 1: Delete the two old backend files**

```bash
git rm backend/routers/questionnaires.py backend/schemas/questionnaires.py
```

- [ ] **Step 2: Remove router registration in `backend/main.py`**

Remove these two lines (they are at ~521 and ~546):

```python
from routers.questionnaires import router as questionnaires_router  # noqa: E402
```

```python
app.include_router(questionnaires_router)
```

- [ ] **Step 3: Strip questionnaire endpoints from `backend/routers/public.py`**

In the imports, change:

```python
from database import get_db, Agent, QuestionnaireQuestion, QuestionnaireResponse, QuestionnaireAnswer
```
to:
```python
from database import get_db, Agent
```

and delete the line:
```python
from schemas.questionnaires import PublicAnswerSubmit
```

Then delete everything from the line `##### Public questionnaire endpoints #####` (~line 96) to the end of the file — the three endpoints `GET /questionnaire/{token}`, `POST /questionnaire/{token}/answer`, `POST /questionnaire/{token}/complete`. Also delete any now-unused imports they pulled in (check whether `datetime` is still used by the remaining code at the top of the file — `public_get_agent` does NOT use it, so remove `from datetime import datetime` if nothing else uses it; run `ruff check backend/routers/public.py` to confirm).

- [ ] **Step 4: Strip the questionnaire branches from `backend/routers/agents.py`**

In `create_agent` (~lines 170-171), delete the two Form parameters:
```python
    welcome_message: str = Form(None),
    closing_message: str = Form(None),
```

In the `Agent(...)` constructor inside `create_agent` (~lines 250-251), delete:
```python
            welcome_message=welcome_message if type == "questionnaire" and welcome_message else None,
            closing_message=closing_message if type == "questionnaire" and closing_message else None,
```

In `update_agent` (~lines 700-701), delete the same two Form parameters, and delete the branch (~lines 716-720):
```python
        # Questionnaire fields
        if type == "questionnaire":
            agent.welcome_message = welcome_message or agent.welcome_message
            agent.closing_message = closing_message or agent.closing_message
            agent.llm_provider = "mistral"
```

Then run `grep -in "questionnaire\|welcome_message\|closing_message" backend/routers/agents.py` — expected: no matches.

- [ ] **Step 5: Tighten the type pattern in `backend/validation.py`**

At ~line 304, change:
```python
    type: Optional[str] = Field("conversationnel", pattern="^(conversationnel|recherche_live|questionnaire)$")
```
to:
```python
    type: Optional[str] = Field("conversationnel", pattern="^(conversationnel|recherche_live)$")
```

- [ ] **Step 6: Remove the old models and column migrations from `backend/database.py`**

Delete the three model classes `QuestionnaireQuestion`, `QuestionnaireResponse`, `QuestionnaireAnswer` (~lines 337-383, between `class Agent` and `class UserGoogleToken`).

In `ensure_columns()` (~lines 916-918), delete:
```python
        # Questionnaire companion
        ("agents", "welcome_message", "TEXT"),
        ("agents", "closing_message", "TEXT"),
```

Leave `ensure_rls_policies()` untouched for now (Task 3 updates its table list together with the new models).

- [ ] **Step 7: Verify the backend still imports and lints**

```bash
cd backend && ruff check . && python -c "import ast, pathlib; [ast.parse(p.read_text(encoding='utf-8')) for p in pathlib.Path('.').rglob('*.py') if 'alembic' not in str(p)]"
```
Expected: ruff passes, no syntax errors. Then:
```bash
cd backend && python -m pytest tests/ -q
```
Expected: same pass/skip count as before this task (39 unit tests; DB tests skip without local PG). No import errors.

- [ ] **Step 8: Grep sweep for backend leftovers**

```bash
grep -rin "questionnaire" backend/ --include="*.py"
```
Expected: ZERO matches (email_service.py mentions are allowed — `send_questionnaire_invitation_email` and its template strings are kept; everything else must be gone).

- [ ] **Step 9: Commit**

```bash
git add -A backend
git commit -m "refactor(backend): remove questionnaire companion type and legacy endpoints"
```

---

## Task 2: Purge the old questionnaire feature from the frontend

**Files:**
- Delete: `frontend/components/questionnaire/` (5 files)
- Delete: `frontend/pages/questionnaire/[token].js`
- Delete: `frontend/public/locales/en/questionnaire.json`, `frontend/public/locales/fr/questionnaire.json`
- Modify: `frontend/pages/agents.js` (~lines 31, 261, 376, 657-660, 688, 743)
- Modify: `frontend/pages/index.js` (~lines 16-18, 25, 55, 72, 154, 197-198, 512-514, 1237-1269, 2117)
- Modify: `frontend/public/locales/en/agents.json`, `frontend/public/locales/fr/agents.json` (~lines 22-25)

- [ ] **Step 1: Delete old files**

```bash
git rm -r frontend/components/questionnaire frontend/pages/questionnaire
git rm frontend/public/locales/en/questionnaire.json frontend/public/locales/fr/questionnaire.json
```

- [ ] **Step 2: Clean `frontend/pages/agents.js`**

Four form-state literals (lines ~31, ~261, ~688, ~743): remove `, welcome_message: "", closing_message: ""` from each object literal.

Line ~376, delete the dropdown option:
```jsx
                  <option value="questionnaire">{t('agents:types.questionnaire.name')} - {t('agents:types.questionnaire.description')}</option>
```

Lines ~657-660, delete the conditional FormData appends:
```jsx
                    if (form.type === 'questionnaire') {
                      formData.append('welcome_message', form.welcome_message || '');
                      formData.append('closing_message', form.closing_message || '');
                    }
```

Verify: `grep -in "questionnaire\|welcome_message\|closing_message" frontend/pages/agents.js` — expected: no matches.

- [ ] **Step 3: Clean `frontend/pages/index.js`**

- Lines ~16-18: delete the three imports of `QuestionBuilder`, `InvitationsTab`, `ResponsesTab` from `../components/questionnaire/...`.
- Line ~25: delete the `questionnaire:` entry from `AGENT_TYPES_CONFIG`.
- Line ~55: remove `'questionnaire'` from the `useTranslation([...])` array.
- Line ~72: remove `welcome_message: "", closing_message: ""` from the form initial state.
- Line ~154: delete the `questionnaire: { ...AGENT_TYPES_CONFIG.questionnaire, ... }` mapping entry.
- Lines ~197-198: remove `welcome_message: agent.welcome_message || "",` and `closing_message: agent.closing_message || "",`.
- Lines ~512-514: delete the `if (f.type === 'questionnaire') { formData.append(...welcome/closing...) }` block.
- Lines ~1237-1269: delete the entire `{/* Questionnaire Management Sections */}` block (`{form.type === 'questionnaire' && currentAgent?.id && (...)}`).
- Line ~2117: remove `'questionnaire'` from the `serverSideTranslations` namespaces array.

Verify: `grep -in "questionnaire\|welcome_message\|closing_message" frontend/pages/index.js` — expected: no matches.

- [ ] **Step 4: Remove the `questionnaire` type block from agents locale files**

In `frontend/public/locales/fr/agents.json` and `frontend/public/locales/en/agents.json`, inside the `"types"` object (~lines 22-25), delete the whole `"questionnaire": { "name": ..., "description": ... }` entry (watch trailing commas).

- [ ] **Step 5: Lint and sweep**

```bash
cd frontend && npm run lint
```
Expected: passes (no unused imports left).

```bash
grep -rin "questionnaire" frontend/ --include="*.js" --include="*.json" -l
```
Expected: ZERO files (everything questionnaire-related is gone; new code arrives in later tasks).

- [ ] **Step 6: Commit**

```bash
git add -A frontend
git commit -m "refactor(frontend): remove questionnaire companion UI"
```

---

## Task 3: New data model, RLS list, factories, and Alembic migration

**Files:**
- Modify: `backend/database.py` (add 4 models where the old ones were, ~after `class Agent`; update `ensure_rls_policies()` tables list ~line 992)
- Create: `backend/alembic/versions/0006_automations_questionnaires.py`
- Modify: `backend/tests/factories.py`
- Modify: `backend/tests/conftest.py` (add `test_questionnaire` fixture)
- Test: `backend/tests/test_questionnaires.py` (model roundtrip test)

- [ ] **Step 1: Add the four new models to `backend/database.py`**

Insert after the `Agent` class (where the old models were):

```python
class Questionnaire(Base):
    __tablename__ = "questionnaires"

    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # créateur
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    questions = relationship(
        "QuestionnaireQuestion",
        back_populates="questionnaire",
        cascade="all, delete-orphan",
        order_by="QuestionnaireQuestion.position",
    )
    responses = relationship(
        "QuestionnaireResponse", back_populates="questionnaire", cascade="all, delete-orphan"
    )


class QuestionnaireQuestion(Base):
    __tablename__ = "questionnaire_questions"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(
        Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(20), nullable=False, default="open")  # open, single_choice, multiple_choice, rating
    options = Column(Text, nullable=True)  # JSON: ["Oui","Non"] ou {"min":1,"max":5}
    position = Column(Integer, nullable=False, default=0)
    required = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    questionnaire = relationship("Questionnaire", back_populates="questions")


class QuestionnaireResponse(Base):
    __tablename__ = "questionnaire_responses"

    id = Column(Integer, primary_key=True, index=True)
    questionnaire_id = Column(
        Integer, ForeignKey("questionnaires.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    respondent_email = Column(String(255), nullable=False)
    respondent_name = Column(String(255), nullable=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending")  # pending, completed
    email_sent = Column(Boolean, default=False, nullable=False)
    invited_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    questionnaire = relationship("Questionnaire", back_populates="responses")
    answers = relationship(
        "QuestionnaireAnswer", back_populates="response", cascade="all, delete-orphan"
    )


class QuestionnaireAnswer(Base):
    __tablename__ = "questionnaire_answers"

    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(
        Integer, ForeignKey("questionnaire_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(
        Integer, ForeignKey("questionnaire_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    answer_text = Column(Text, nullable=True)  # texte libre, JSON array pour multiple_choice, note en texte pour rating
    answered_at = Column(DateTime, default=datetime.utcnow)

    response = relationship("QuestionnaireResponse", back_populates="answers")
    question = relationship("QuestionnaireQuestion", foreign_keys=[question_id])
```

- [ ] **Step 2: Update the `ensure_rls_policies()` tables list**

At ~line 992, the list already contains `"questionnaire_questions"`, `"questionnaire_responses"`, `"questionnaire_answers"`. Add `"questionnaires"` right before them:

```python
        "questionnaires",
        "questionnaire_questions",
        "questionnaire_responses",
        "questionnaire_answers",
```

IMPORTANT: do NOT add `ENABLE/FORCE ROW LEVEL SECURITY` statements for these tables anywhere. The public token endpoints (`/questionnaire/{token}`) run with no tenant session variable; forced RLS would return zero rows for respondents. Tenant isolation for these tables is enforced at the application layer (`company_id` filters on every admin query), matching the existing state of these tables.

- [ ] **Step 3: Create the Alembic migration**

Create `backend/alembic/versions/0006_automations_questionnaires.py`:

```python
"""rebuild questionnaires as standalone automations entity

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Clean rebuild decided in the 2026-06-10 spec: no data migration from the
    # legacy agent-based questionnaire tables.
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_answers CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_responses CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_questions CASCADE"))
    conn.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS welcome_message"))
    conn.execute(sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS closing_message"))

    # create_all() runs before Alembic at startup, so the new tables may already
    # exist on a fresh database — guard each create.
    inspector = sa.inspect(conn)

    if not inspector.has_table("questionnaires"):
        op.create_table(
            "questionnaires",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("questionnaire_questions"):
        op.create_table(
            "questionnaire_questions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "questionnaire_id",
                sa.Integer(),
                sa.ForeignKey("questionnaires.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("question_type", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("options", sa.Text(), nullable=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("questionnaire_responses"):
        op.create_table(
            "questionnaire_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "questionnaire_id",
                sa.Integer(),
                sa.ForeignKey("questionnaires.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("respondent_email", sa.String(length=255), nullable=False),
            sa.Column("respondent_name", sa.String(length=255), nullable=True),
            sa.Column("token", sa.String(length=64), nullable=False, unique=True, index=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("email_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("invited_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )

    if not inspector.has_table("questionnaire_answers"):
        op.create_table(
            "questionnaire_answers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "response_id",
                sa.Integer(),
                sa.ForeignKey("questionnaire_responses.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "question_id",
                sa.Integer(),
                sa.ForeignKey("questionnaire_questions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
            sa.Column("answer_text", sa.Text(), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_answers CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_responses CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaire_questions CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS questionnaires CASCADE"))
    conn.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS welcome_message TEXT"))
    conn.execute(sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS closing_message TEXT"))
```

- [ ] **Step 4: Add factories in `backend/tests/factories.py`**

Add the four model names to the `from database import (...)` list: `Questionnaire`, `QuestionnaireQuestion`, `QuestionnaireResponse`, `QuestionnaireAnswer`. Then append:

```python
class QuestionnaireFactory(factory.Factory):
    class Meta:
        model = Questionnaire

    title = factory.Sequence(lambda n: f"questionnaire-{n}")
    description = "Questionnaire de test"


class QuestionnaireQuestionFactory(factory.Factory):
    class Meta:
        model = QuestionnaireQuestion

    question_text = "Quelle est votre couleur préférée ?"
    question_type = "open"
    options = None
    position = 0
    required = True


class QuestionnaireResponseFactory(factory.Factory):
    class Meta:
        model = QuestionnaireResponse

    respondent_email = factory.Sequence(lambda n: f"respondent{n}@test.com")
    token = factory.LazyFunction(lambda: __import__("secrets").token_urlsafe(32))
    status = "pending"
    email_sent = False


class QuestionnaireAnswerFactory(factory.Factory):
    class Meta:
        model = QuestionnaireAnswer

    answer_text = "Bleu"
```

- [ ] **Step 5: Add the `test_questionnaire` fixture in `backend/tests/conftest.py`**

Append after the `test_member_user`/`member_cookies` fixtures:

```python
@pytest.fixture
def test_questionnaire(db_session, test_member_user, test_company):
    """Create a questionnaire with 2 questions (open + single_choice) in test_company."""
    from tests.factories import QuestionnaireFactory, QuestionnaireQuestionFactory

    questionnaire = QuestionnaireFactory.build(
        company_id=test_company.id, user_id=test_member_user.id
    )
    db_session.add(questionnaire)
    db_session.flush()

    q1 = QuestionnaireQuestionFactory.build(
        questionnaire_id=questionnaire.id, company_id=test_company.id, position=0
    )
    q2 = QuestionnaireQuestionFactory.build(
        questionnaire_id=questionnaire.id,
        company_id=test_company.id,
        position=1,
        question_text="Êtes-vous satisfait ?",
        question_type="single_choice",
        options='["Oui", "Non"]',
    )
    db_session.add(q1)
    db_session.add(q2)
    db_session.flush()
    return questionnaire
```

- [ ] **Step 6: Write the model roundtrip test (failing is OK to observe only if models are missing)**

Create `backend/tests/test_questionnaires.py`:

```python
"""Tests for the automations questionnaire feature (models, schemas, admin + public endpoints)."""

import pytest


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_questionnaire_model_roundtrip(db_session, test_questionnaire):
    from database import Questionnaire

    loaded = db_session.query(Questionnaire).filter(Questionnaire.id == test_questionnaire.id).first()
    assert loaded is not None
    assert len(loaded.questions) == 2
    assert loaded.questions[0].position == 0  # relationship ordered by position
    assert loaded.questions[1].question_type == "single_choice"


def test_questionnaire_cascade_delete(db_session, test_questionnaire, test_company):
    from database import Questionnaire, QuestionnaireQuestion
    from tests.factories import QuestionnaireResponseFactory

    response = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(response)
    db_session.flush()

    db_session.delete(test_questionnaire)
    db_session.flush()
    assert db_session.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.questionnaire_id == test_questionnaire.id
    ).count() == 0
```

- [ ] **Step 7: Run the tests**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v
```
Expected: 2 passed (or 2 skipped if no local PostgreSQL — they must pass in CI).

```bash
cd backend && ruff check .
```
Expected: passes.

- [ ] **Step 8: Commit**

```bash
git add backend/database.py backend/alembic/versions/0006_automations_questionnaires.py backend/tests/factories.py backend/tests/conftest.py backend/tests/test_questionnaires.py
git commit -m "feat(db): standalone questionnaire models + alembic 0006 rebuild migration"
```

---

## Task 4: Pydantic schemas with type-aware validation

**Files:**
- Create: `backend/schemas/questionnaires.py`
- Test: `backend/tests/test_questionnaires.py` (append schema tests)

- [ ] **Step 1: Write the failing schema tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Schema unit tests (no DB required)
# ---------------------------------------------------------------------------

from pydantic import ValidationError  # noqa: E402

from schemas.questionnaires import InviteRequest, QuestionInput  # noqa: E402


class TestQuestionInputSchema:
    def test_open_question_defaults(self):
        q = QuestionInput(question_text="Votre avis ?")
        assert q.question_type == "open"
        assert q.options is None
        assert q.required is True

    def test_open_question_drops_options(self):
        q = QuestionInput(question_text="Avis ?", question_type="open", options=["a"])
        assert q.options is None

    def test_choice_requires_options(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Choix ?", question_type="single_choice", options=None)

    def test_choice_rejects_blank_options(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Choix ?", question_type="multiple_choice", options=["  "])

    def test_rating_normalizes_missing_options(self):
        q = QuestionInput(question_text="Note ?", question_type="rating", options=None)
        assert q.options == {"min": 1, "max": 5}

    def test_rating_rejects_inverted_bounds(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="Note ?", question_type="rating", options={"min": 5, "max": 1})

    def test_unknown_type_rejected(self):
        with pytest.raises(ValidationError):
            QuestionInput(question_text="?", question_type="dropdown")


class TestInviteRequestSchema:
    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            InviteRequest(recipients=[{"email": "not-an-email"}])

    def test_email_normalized(self):
        req = InviteRequest(recipients=[{"email": "  Marie@Example.COM ", "name": "Marie"}])
        assert req.recipients[0].email == "marie@example.com"

    def test_empty_recipients_rejected(self):
        with pytest.raises(ValidationError):
            InviteRequest(recipients=[])
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v
```
Expected: collection FAILS with `ModuleNotFoundError: No module named 'schemas.questionnaires'` (the old file was deleted in Task 1).

- [ ] **Step 3: Implement `backend/schemas/questionnaires.py`**

```python
"""Pydantic schemas for the automations questionnaire feature."""

import re
from typing import List, Optional, Union

from pydantic import BaseModel, Field, field_validator

QUESTION_TYPE_PATTERN = "^(open|single_choice|multiple_choice|rating)$"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- Questionnaire CRUD ---


class QuestionInput(BaseModel):
    question_text: str = Field(..., min_length=1, max_length=2000)
    question_type: str = Field("open", pattern=QUESTION_TYPE_PATTERN)
    # list of choices for single/multiple_choice, {"min","max"} for rating, None for open
    options: Optional[Union[List[str], dict]] = None
    position: int = 0
    required: bool = True

    @field_validator("options")
    @classmethod
    def validate_options(cls, v, info):
        qtype = info.data.get("question_type", "open")
        if qtype in ("single_choice", "multiple_choice"):
            if (
                not isinstance(v, list)
                or not v
                or not all(isinstance(o, str) and o.strip() for o in v)
            ):
                raise ValueError("choice questions need a non-empty list of option strings")
            return [o.strip() for o in v]
        if qtype == "rating":
            if not isinstance(v, dict):
                return {"min": 1, "max": 5}
            try:
                bounds = {"min": int(v.get("min", 1)), "max": int(v.get("max", 5))}
            except (TypeError, ValueError):
                raise ValueError("rating bounds must be integers")
            if bounds["min"] >= bounds["max"]:
                raise ValueError("rating min must be lower than max")
            return bounds
        return None  # open questions carry no options


class QuestionnaireCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=5000)
    questions: List[QuestionInput] = Field(default_factory=list, max_length=100)


class QuestionnaireUpdate(QuestionnaireCreate):
    pass


# --- Invitations ---


class InviteRecipient(BaseModel):
    email: str = Field(..., max_length=255)
    name: Optional[str] = Field(None, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError(f"invalid email address: {v}")
        return v


class InviteRequest(BaseModel):
    recipients: List[InviteRecipient] = Field(..., min_length=1, max_length=200)


# --- Export ---


class ExportRequest(BaseModel):
    response_ids: List[int] = Field(..., min_length=1, max_length=500)
    target_agent_id: int


# --- Public submit ---


class PublicAnswerItem(BaseModel):
    question_id: int
    # str (open/single_choice), list[str] (multiple_choice), int (rating)
    value: Union[str, List[str], int, None] = None


class PublicSubmitRequest(BaseModel):
    respondent_name: Optional[str] = Field(None, max_length=255)
    answers: List[PublicAnswerItem] = Field(default_factory=list, max_length=200)
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v
```
Expected: all schema tests PASS (model tests pass or skip as before).

- [ ] **Step 5: Commit**

```bash
git add backend/schemas/questionnaires.py backend/tests/test_questionnaires.py
git commit -m "feat(schemas): questionnaire pydantic schemas with type-aware option validation"
```

---

## Task 5: Admin router — questionnaire CRUD

**Files:**
- Create: `backend/routers/automations.py`
- Modify: `backend/main.py` (register router)
- Test: `backend/tests/test_questionnaires.py` (append CRUD tests)

- [ ] **Step 1: Write the failing CRUD tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Admin endpoint tests — CRUD
# ---------------------------------------------------------------------------

CREATE_PAYLOAD = {
    "title": "Enquête satisfaction",
    "description": "Donnez-nous votre avis",
    "questions": [
        {"question_text": "Votre avis général ?", "question_type": "open", "position": 0, "required": True},
        {
            "question_text": "Recommanderiez-vous ?",
            "question_type": "single_choice",
            "options": ["Oui", "Non"],
            "position": 1,
            "required": True,
        },
        {
            "question_text": "Note globale ?",
            "question_type": "rating",
            "options": {"min": 1, "max": 5},
            "position": 2,
            "required": False,
        },
    ],
}


@pytest.mark.asyncio
async def test_create_and_get_questionnaire(client, member_cookies):
    resp = await client.post(
        "/api/automations/questionnaires", json=CREATE_PAYLOAD, cookies=member_cookies
    )
    assert resp.status_code == 200
    data = resp.json()["questionnaire"]
    assert data["title"] == "Enquête satisfaction"
    assert len(data["questions"]) == 3
    assert data["questions"][1]["options"] == ["Oui", "Non"]
    assert data["questions"][2]["options"] == {"min": 1, "max": 5}

    detail = await client.get(
        f"/api/automations/questionnaires/{data['id']}", cookies=member_cookies
    )
    assert detail.status_code == 200
    assert len(detail.json()["questionnaire"]["questions"]) == 3


@pytest.mark.asyncio
async def test_create_questionnaire_validation_422(client, member_cookies):
    resp = await client.post(
        "/api/automations/questionnaires",
        json={"title": "", "questions": []},
        cookies=member_cookies,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_questionnaires_with_counts(client, member_cookies, test_questionnaire):
    resp = await client.get("/api/automations/questionnaires", cookies=member_cookies)
    assert resp.status_code == 200
    items = resp.json()["questionnaires"]
    assert len(items) == 1
    assert items[0]["question_count"] == 2
    assert items[0]["invited_count"] == 0
    assert items[0]["completed_count"] == 0


@pytest.mark.asyncio
async def test_questionnaire_cross_company_404(client, member_cookies, db_session):
    from tests.factories import CompanyFactory, QuestionnaireFactory, UserFactory

    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()
    other_user = UserFactory.build(company_id=other_company.id)
    db_session.add(other_user)
    db_session.flush()
    foreign = QuestionnaireFactory.build(company_id=other_company.id, user_id=other_user.id)
    db_session.add(foreign)
    db_session.flush()

    resp = await client.get(
        f"/api/automations/questionnaires/{foreign.id}", cookies=member_cookies
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_replaces_questions(client, member_cookies, test_questionnaire):
    payload = {
        "title": "Titre modifié",
        "description": None,
        "questions": [
            {"question_text": "Nouvelle question unique ?", "question_type": "open", "position": 0, "required": True}
        ],
    }
    resp = await client.put(
        f"/api/automations/questionnaires/{test_questionnaire.id}",
        json=payload,
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()["questionnaire"]
    assert data["title"] == "Titre modifié"
    assert len(data["questions"]) == 1


@pytest.mark.asyncio
async def test_update_blocked_when_completed_responses(
    client, member_cookies, db_session, test_questionnaire, test_company
):
    from tests.factories import QuestionnaireResponseFactory

    done = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id, status="completed"
    )
    db_session.add(done)
    db_session.flush()

    resp = await client.put(
        f"/api/automations/questionnaires/{test_questionnaire.id}",
        json={"title": "X", "questions": []},
        cookies=member_cookies,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_questionnaire(client, member_cookies, test_questionnaire):
    resp = await client.delete(
        f"/api/automations/questionnaires/{test_questionnaire.id}", cookies=member_cookies
    )
    assert resp.status_code == 200
    again = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}", cookies=member_cookies
    )
    assert again.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v -k "create or list or update or delete or cross"
```
Expected: FAIL with 404s (routes don't exist) — or skip without local PG; in that case proceed on CI signal and code review.

- [ ] **Step 3: Implement the router (CRUD part) in `backend/routers/automations.py`**

```python
"""Automations endpoints: questionnaire CRUD, invitations, responses, RAG export."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import verify_token
from database import (
    Questionnaire,
    QuestionnaireQuestion,
    QuestionnaireResponse,
    get_db,
)
from permissions import require_role
from schemas.questionnaires import (
    QuestionnaireCreate,
    QuestionnaireUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()

EXPORTABLE_AGENT_TYPES = ("conversationnel", "actionnable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_questionnaire_or_404(questionnaire_id: int, company_id: int, db: Session) -> Questionnaire:
    questionnaire = (
        db.query(Questionnaire)
        .filter(Questionnaire.id == questionnaire_id, Questionnaire.company_id == company_id)
        .first()
    )
    if not questionnaire:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    return questionnaire


def _question_to_dict(question: QuestionnaireQuestion) -> dict:
    return {
        "id": question.id,
        "question_text": question.question_text,
        "question_type": question.question_type,
        "options": json.loads(question.options) if question.options else None,
        "position": question.position,
        "required": question.required,
    }


def _completed_count(questionnaire_id: int, db: Session) -> int:
    return (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire_id,
            QuestionnaireResponse.status == "completed",
        )
        .scalar()
        or 0
    )


def _questionnaire_detail(questionnaire: Questionnaire, db: Session) -> dict:
    invited = (
        db.query(func.count(QuestionnaireResponse.id))
        .filter(QuestionnaireResponse.questionnaire_id == questionnaire.id)
        .scalar()
        or 0
    )
    return {
        "id": questionnaire.id,
        "title": questionnaire.title,
        "description": questionnaire.description,
        "created_at": questionnaire.created_at.isoformat() if questionnaire.created_at else None,
        "updated_at": questionnaire.updated_at.isoformat() if questionnaire.updated_at else None,
        "questions": [_question_to_dict(q) for q in questionnaire.questions],
        "invited_count": invited,
        "completed_count": _completed_count(questionnaire.id, db),
    }


def _insert_questions(questionnaire: Questionnaire, questions, db: Session) -> None:
    for idx, qi in enumerate(questions):
        db.add(
            QuestionnaireQuestion(
                questionnaire_id=questionnaire.id,
                company_id=questionnaire.company_id,
                question_text=qi.question_text.strip(),
                question_type=qi.question_type,
                options=json.dumps(qi.options) if qi.options is not None else None,
                position=idx,
                required=qi.required,
            )
        )


# ---------------------------------------------------------------------------
# Questionnaire CRUD
# ---------------------------------------------------------------------------


@router.get("/api/automations/questionnaires")
async def list_questionnaires(
    user_id: int = Depends(verify_token), db: Session = Depends(get_db)
):
    membership = require_role(user_id, db, "member")

    questionnaires = (
        db.query(Questionnaire)
        .filter(Questionnaire.company_id == membership.company_id)
        .order_by(Questionnaire.created_at.desc())
        .all()
    )
    ids = [q.id for q in questionnaires]
    question_counts, invited_counts, completed_counts = {}, {}, {}
    if ids:
        question_counts = dict(
            db.query(QuestionnaireQuestion.questionnaire_id, func.count())
            .filter(QuestionnaireQuestion.questionnaire_id.in_(ids))
            .group_by(QuestionnaireQuestion.questionnaire_id)
            .all()
        )
        invited_counts = dict(
            db.query(QuestionnaireResponse.questionnaire_id, func.count())
            .filter(QuestionnaireResponse.questionnaire_id.in_(ids))
            .group_by(QuestionnaireResponse.questionnaire_id)
            .all()
        )
        completed_counts = dict(
            db.query(QuestionnaireResponse.questionnaire_id, func.count())
            .filter(
                QuestionnaireResponse.questionnaire_id.in_(ids),
                QuestionnaireResponse.status == "completed",
            )
            .group_by(QuestionnaireResponse.questionnaire_id)
            .all()
        )

    return {
        "questionnaires": [
            {
                "id": q.id,
                "title": q.title,
                "description": q.description,
                "created_at": q.created_at.isoformat() if q.created_at else None,
                "question_count": question_counts.get(q.id, 0),
                "invited_count": invited_counts.get(q.id, 0),
                "completed_count": completed_counts.get(q.id, 0),
            }
            for q in questionnaires
        ]
    }


@router.post("/api/automations/questionnaires")
async def create_questionnaire(
    body: QuestionnaireCreate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")

    questionnaire = Questionnaire(
        company_id=membership.company_id,
        user_id=int(user_id),
        title=body.title.strip(),
        description=body.description,
    )
    db.add(questionnaire)
    db.flush()
    _insert_questions(questionnaire, body.questions, db)
    db.commit()
    db.refresh(questionnaire)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.get("/api/automations/questionnaires/{questionnaire_id}")
async def get_questionnaire(
    questionnaire_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.put("/api/automations/questionnaires/{questionnaire_id}")
async def update_questionnaire(
    questionnaire_id: int,
    body: QuestionnaireUpdate,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    if _completed_count(questionnaire.id, db) > 0:
        raise HTTPException(
            status_code=409,
            detail="Des réponses ont déjà été reçues : le questionnaire n'est plus modifiable.",
        )

    questionnaire.title = body.title.strip()
    questionnaire.description = body.description
    questionnaire.updated_at = datetime.utcnow()
    db.query(QuestionnaireQuestion).filter(
        QuestionnaireQuestion.questionnaire_id == questionnaire.id
    ).delete()
    _insert_questions(questionnaire, body.questions, db)
    db.commit()
    db.refresh(questionnaire)
    return {"questionnaire": _questionnaire_detail(questionnaire, db)}


@router.delete("/api/automations/questionnaires/{questionnaire_id}")
async def delete_questionnaire(
    questionnaire_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    db.delete(questionnaire)
    db.commit()
    return {"success": True}
```

(Imports are added incrementally: Task 6 adds `os`, `secrets`, `BackgroundTasks`, `Company`, `SessionLocal`, `send_questionnaire_invitation_email`, `InviteRequest`; Task 7 adds `Optional`, `Query`, `QuestionnaireAnswer`; Task 8 adds `Agent`, `ExportRequest`. This keeps ruff green at every commit.)

- [ ] **Step 4: Register the router in `backend/main.py`**

Where the old questionnaires import was removed (after the `action_executions` import, ~line 520):
```python
from routers.automations import router as automations_router  # noqa: E402
```
And after `app.include_router(action_executions_router)` (~line 545):
```python
app.include_router(automations_router)
```

- [ ] **Step 5: Run the tests**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v
```
Expected: all PASS (or DB tests skip locally — schema tests must pass). Also `cd backend && ruff check .` passes.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/automations.py backend/main.py backend/tests/test_questionnaires.py
git commit -m "feat(api): questionnaire CRUD endpoints under /api/automations"
```

---

## Task 6: Admin router — invitations and resend

**Files:**
- Modify: `backend/routers/automations.py`
- Test: `backend/tests/test_questionnaires.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Admin endpoint tests — invitations
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402


@pytest.mark.asyncio
async def test_invite_dedupes_and_schedules_emails(client, member_cookies, db_session, test_questionnaire):
    from database import QuestionnaireResponse

    with patch("routers.automations._send_invitations") as mock_send:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/invite",
            json={
                "recipients": [
                    {"email": "a@test.com"},
                    {"email": "A@test.com"},  # duplicate after normalization
                    {"email": "b@test.com", "name": "Bob"},
                ]
            },
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json()["invited"] == 2
    assert resp.json()["skipped"] == 1

    rows = (
        db_session.query(QuestionnaireResponse)
        .filter(QuestionnaireResponse.questionnaire_id == test_questionnaire.id)
        .all()
    )
    assert len(rows) == 2
    assert all(r.status == "pending" and r.email_sent is False and r.token for r in rows)
    assert mock_send.called


@pytest.mark.asyncio
async def test_invite_skips_already_invited(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    existing = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id,
        company_id=test_company.id,
        respondent_email="deja@test.com",
    )
    db_session.add(existing)
    db_session.flush()

    with patch("routers.automations._send_invitations"):
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/invite",
            json={"recipients": [{"email": "deja@test.com"}]},
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json() == {"invited": 0, "skipped": 1}


@pytest.mark.asyncio
async def test_invite_requires_questions(client, member_cookies, db_session, test_member_user, test_company):
    from tests.factories import QuestionnaireFactory

    empty = QuestionnaireFactory.build(company_id=test_company.id, user_id=test_member_user.id)
    db_session.add(empty)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{empty.id}/invite",
        json={"recipients": [{"email": "x@test.com"}]},
        cookies=member_cookies,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resend_invitation(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    invitation = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(invitation)
    db_session.flush()

    with patch("routers.automations._send_invitations") as mock_send:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{invitation.id}/resend",
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert mock_send.called


@pytest.mark.asyncio
async def test_resend_rejected_for_completed(client, member_cookies, db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    done = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id, status="completed"
    )
    db_session.add(done)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{done.id}/resend",
        cookies=member_cookies,
    )
    assert resp.status_code == 409
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v -k "invite or resend"
```
Expected: FAIL (404, routes missing).

- [ ] **Step 3: Implement invite/resend in `backend/routers/automations.py`**

Add the imports now used: `os`, `secrets`, `BackgroundTasks`, `Company`, `SessionLocal`, `send_questionnaire_invitation_email`, `InviteRequest`. Then append:

```python
# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def _send_invitations(response_ids: list):
    """Background task: send invitation emails and flag email_sent.

    Failures are logged and leave email_sent=False so the invitation stays
    visible and resendable in the UI — never blocking.
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    db = SessionLocal()
    try:
        responses = (
            db.query(QuestionnaireResponse)
            .filter(QuestionnaireResponse.id.in_(response_ids))
            .all()
        )
        for response in responses:
            questionnaire = response.questionnaire
            company = db.query(Company).filter(Company.id == questionnaire.company_id).first()
            try:
                send_questionnaire_invitation_email(
                    to_email=response.respondent_email,
                    questionnaire_name=questionnaire.title,
                    company_name=company.name if company else "TAIC",
                    respondent_name=response.respondent_name,
                    questionnaire_url=f"{frontend_url}/questionnaire/{response.token}",
                )
                response.email_sent = True
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(
                    "Failed to send questionnaire invitation to %s (response %s): %s",
                    response.respondent_email,
                    response.id,
                    e,
                )
    finally:
        db.close()


@router.post("/api/automations/questionnaires/{questionnaire_id}/invite")
async def invite_respondents(
    questionnaire_id: int,
    body: InviteRequest,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    if not questionnaire.questions:
        raise HTTPException(status_code=400, detail="Le questionnaire n'a aucune question.")

    emails = [r.email for r in body.recipients]
    already_invited = {
        row[0]
        for row in db.query(QuestionnaireResponse.respondent_email)
        .filter(
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
            QuestionnaireResponse.respondent_email.in_(emails),
        )
        .all()
    }

    created = []
    seen = set(already_invited)
    for recipient in body.recipients:
        if recipient.email in seen:
            continue
        seen.add(recipient.email)
        response = QuestionnaireResponse(
            questionnaire_id=questionnaire.id,
            company_id=questionnaire.company_id,
            respondent_email=recipient.email,
            respondent_name=recipient.name,
            token=secrets.token_urlsafe(32),
            status="pending",
            email_sent=False,
        )
        db.add(response)
        created.append(response)

    db.flush()
    created_ids = [r.id for r in created]
    db.commit()

    if created_ids:
        background_tasks.add_task(_send_invitations, created_ids)

    return {"invited": len(created_ids), "skipped": len(body.recipients) - len(created_ids)}


@router.post(
    "/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}/resend"
)
async def resend_invitation(
    questionnaire_id: int,
    response_id: int,
    background_tasks: BackgroundTasks,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    response = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id == response_id,
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
        )
        .first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if response.status == "completed":
        raise HTTPException(status_code=409, detail="Ce questionnaire a déjà été complété.")

    background_tasks.add_task(_send_invitations, [response.id])
    return {"success": True}
```

- [ ] **Step 4: Run the tests**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v
```
Expected: PASS. `ruff check .` passes.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/automations.py backend/tests/test_questionnaires.py
git commit -m "feat(api): questionnaire invitations with background email and resend"
```

---

## Task 7: Admin router — responses list, detail, delete

**Files:**
- Modify: `backend/routers/automations.py`
- Test: `backend/tests/test_questionnaires.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Admin endpoint tests — responses
# ---------------------------------------------------------------------------


@pytest.fixture
def test_completed_response(db_session, test_questionnaire, test_company):
    """A completed response with one answer on the first (open) question."""
    from tests.factories import QuestionnaireAnswerFactory, QuestionnaireResponseFactory
    from datetime import datetime

    response = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id,
        company_id=test_company.id,
        status="completed",
        completed_at=datetime.utcnow(),
    )
    db_session.add(response)
    db_session.flush()
    answer = QuestionnaireAnswerFactory.build(
        response_id=response.id,
        question_id=test_questionnaire.questions[0].id,
        company_id=test_company.id,
        answer_text="Très satisfait",
    )
    db_session.add(answer)
    db_session.flush()
    return response


@pytest.mark.asyncio
async def test_list_responses_with_filter_and_pagination(
    client, member_cookies, db_session, test_questionnaire, test_company, test_completed_response
):
    from tests.factories import QuestionnaireResponseFactory

    pending = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(pending)
    db_session.flush()

    resp = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["completed_count"] == 1
    assert len(data["responses"]) == 2

    only_completed = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses?status=completed",
        cookies=member_cookies,
    )
    assert len(only_completed.json()["responses"]) == 1

    paged = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses?limit=1&offset=0",
        cookies=member_cookies,
    )
    assert len(paged.json()["responses"]) == 1
    assert paged.json()["total"] == 2


@pytest.mark.asyncio
async def test_response_detail_with_answers(
    client, member_cookies, test_questionnaire, test_completed_response
):
    resp = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    data = resp.json()["response"]
    assert data["status"] == "completed"
    assert len(data["answers"]) == 1
    assert data["answers"][0]["answer_text"] == "Très satisfait"
    assert data["answers"][0]["question_text"] == test_questionnaire.questions[0].question_text


@pytest.mark.asyncio
async def test_delete_response(client, member_cookies, test_questionnaire, test_completed_response):
    resp = await client.delete(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert resp.status_code == 200
    again = await client.get(
        f"/api/automations/questionnaires/{test_questionnaire.id}/responses/{test_completed_response.id}",
        cookies=member_cookies,
    )
    assert again.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v -k "responses or response_detail or delete_response"
```
Expected: FAIL (404).

- [ ] **Step 3: Implement responses endpoints in `backend/routers/automations.py`**

Add `Optional` and `Query` to imports if not already present. Append:

```python
# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


def _response_to_dict(response: QuestionnaireResponse) -> dict:
    return {
        "id": response.id,
        "respondent_email": response.respondent_email,
        "respondent_name": response.respondent_name,
        "status": response.status,
        "email_sent": response.email_sent,
        "invited_at": response.invited_at.isoformat() if response.invited_at else None,
        "completed_at": response.completed_at.isoformat() if response.completed_at else None,
    }


def _get_response_or_404(
    response_id: int, questionnaire: Questionnaire, db: Session
) -> QuestionnaireResponse:
    response = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id == response_id,
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
        )
        .first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Response not found")
    return response


@router.get("/api/automations/questionnaires/{questionnaire_id}/responses")
async def list_responses(
    questionnaire_id: int,
    status: Optional[str] = Query(None, pattern="^(pending|completed)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    base = db.query(QuestionnaireResponse).filter(
        QuestionnaireResponse.questionnaire_id == questionnaire.id
    )
    total = base.count()
    completed_count = _completed_count(questionnaire.id, db)

    query = base
    if status:
        query = query.filter(QuestionnaireResponse.status == status)
    rows = (
        query.order_by(QuestionnaireResponse.invited_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "responses": [_response_to_dict(r) for r in rows],
        "total": total,
        "completed_count": completed_count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}")
async def get_response(
    questionnaire_id: int,
    response_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    response = _get_response_or_404(response_id, questionnaire, db)

    rows = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )
    data = _response_to_dict(response)
    data["answers"] = [
        {
            "question_id": question.id,
            "question_text": question.question_text,
            "question_type": question.question_type,
            "answer_text": answer.answer_text,
        }
        for answer, question in rows
    ]
    return {"response": data}


@router.delete("/api/automations/questionnaires/{questionnaire_id}/responses/{response_id}")
async def delete_response(
    questionnaire_id: int,
    response_id: int,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)
    response = _get_response_or_404(response_id, questionnaire, db)
    db.delete(response)
    db.commit()
    return {"success": True}
```

- [ ] **Step 4: Run the tests, then commit**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v && ruff check .
git add backend/routers/automations.py backend/tests/test_questionnaires.py
git commit -m "feat(api): questionnaire responses list/detail/delete with pagination"
```

---

## Task 8: Admin router — export to companion RAG

**Files:**
- Modify: `backend/routers/automations.py`
- Test: `backend/tests/test_questionnaires.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Admin endpoint tests — export to RAG
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_to_rag(
    client, member_cookies, db_session, test_questionnaire, test_company,
    test_member_user, test_completed_response,
):
    from tests.factories import AgentFactory

    agent = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="conversationnel"
    )
    db_session.add(agent)
    db_session.flush()

    with patch("rag_engine.ingest_text_content", return_value=1) as mock_ingest:
        resp = await client.post(
            f"/api/automations/questionnaires/{test_questionnaire.id}/export",
            json={"response_ids": [test_completed_response.id], "target_agent_id": agent.id},
            cookies=member_cookies,
        )
    assert resp.status_code == 200
    assert resp.json()["exported"] == 1
    mock_ingest.assert_called_once()
    markdown = mock_ingest.call_args[0][0]
    assert test_questionnaire.questions[0].question_text in markdown
    assert "Très satisfait" in markdown


@pytest.mark.asyncio
async def test_export_rejects_foreign_agent(
    client, member_cookies, db_session, test_questionnaire, test_completed_response
):
    from tests.factories import AgentFactory, CompanyFactory, UserFactory

    other_company = CompanyFactory.build()
    db_session.add(other_company)
    db_session.flush()
    other_user = UserFactory.build(company_id=other_company.id)
    db_session.add(other_user)
    db_session.flush()
    foreign_agent = AgentFactory.build(user_id=other_user.id, company_id=other_company.id)
    db_session.add(foreign_agent)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/export",
        json={"response_ids": [test_completed_response.id], "target_agent_id": foreign_agent.id},
        cookies=member_cookies,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_requires_completed_responses(
    client, member_cookies, db_session, test_questionnaire, test_company, test_member_user
):
    from tests.factories import AgentFactory, QuestionnaireResponseFactory

    agent = AgentFactory.build(
        user_id=test_member_user.id, company_id=test_company.id, type="conversationnel"
    )
    pending = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(agent)
    db_session.add(pending)
    db_session.flush()

    resp = await client.post(
        f"/api/automations/questionnaires/{test_questionnaire.id}/export",
        json={"response_ids": [pending.id], "target_agent_id": agent.id},
        cookies=member_cookies,
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v -k "export"
```
Expected: FAIL (404).

- [ ] **Step 3: Implement the export endpoint in `backend/routers/automations.py`**

Add `Agent` and `ExportRequest` to imports if not already present. Append:

```python
# ---------------------------------------------------------------------------
# Export to companion RAG
# ---------------------------------------------------------------------------


def _build_response_markdown(
    questionnaire: Questionnaire, response: QuestionnaireResponse, db: Session
) -> str:
    lines = [
        f"# {questionnaire.title} — Réponse de {response.respondent_name or response.respondent_email}",
        "",
    ]
    if response.completed_at:
        lines.append(f"Complété le : {response.completed_at.strftime('%d/%m/%Y %H:%M')}")
        lines.append("")
    rows = (
        db.query(QuestionnaireAnswer, QuestionnaireQuestion)
        .join(QuestionnaireQuestion, QuestionnaireAnswer.question_id == QuestionnaireQuestion.id)
        .filter(QuestionnaireAnswer.response_id == response.id)
        .order_by(QuestionnaireQuestion.position)
        .all()
    )
    for answer, question in rows:
        value = answer.answer_text or ""
        if question.question_type == "multiple_choice" and value:
            try:
                value = ", ".join(json.loads(value))
            except (ValueError, TypeError):
                pass
        lines.append(f"**Q : {question.question_text}**")
        lines.append(f"R : {value}")
        lines.append("")
    return "\n".join(lines)


@router.post("/api/automations/questionnaires/{questionnaire_id}/export")
async def export_responses_to_rag(
    questionnaire_id: int,
    body: ExportRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    membership = require_role(user_id, db, "member")
    questionnaire = _get_questionnaire_or_404(questionnaire_id, membership.company_id, db)

    agent = (
        db.query(Agent)
        .filter(Agent.id == body.target_agent_id, Agent.company_id == membership.company_id)
        .first()
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Target agent not found")
    if agent.type not in EXPORTABLE_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="L'export RAG n'est possible que vers un companion conversationnel ou actionnable.",
        )

    responses = (
        db.query(QuestionnaireResponse)
        .filter(
            QuestionnaireResponse.id.in_(body.response_ids),
            QuestionnaireResponse.questionnaire_id == questionnaire.id,
            QuestionnaireResponse.status == "completed",
        )
        .all()
    )
    if not responses:
        raise HTTPException(status_code=400, detail="Aucune réponse complétée à exporter.")

    from rag_engine import ingest_text_content

    exported = 0
    for response in responses:
        markdown = _build_response_markdown(questionnaire, response, db)
        filename = f"questionnaire-{questionnaire.id}-reponse-{response.id}.md"
        ingest_text_content(
            markdown,
            filename,
            int(user_id),
            agent.id,
            db,
            company_id=membership.company_id,
        )
        exported += 1

    return {"exported": exported, "target_agent_id": agent.id}
```

NOTE: `ingest_text_content` is imported lazily inside the endpoint (same pattern used elsewhere) so tests can patch `rag_engine.ingest_text_content` and module import stays light.

- [ ] **Step 4: Run the tests, then commit**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v && ruff check .
git add backend/routers/automations.py backend/tests/test_questionnaires.py
git commit -m "feat(api): export questionnaire responses to companion RAG via ingest_text_content"
```

---

## Task 9: Public endpoints — GET form data and single-submit

**Files:**
- Modify: `backend/routers/public.py`
- Test: `backend/tests/test_questionnaires.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_questionnaires.py`:

```python
# ---------------------------------------------------------------------------
# Public endpoint tests (token-based, no auth)
# ---------------------------------------------------------------------------


@pytest.fixture
def test_invitation(db_session, test_questionnaire, test_company):
    from tests.factories import QuestionnaireResponseFactory

    invitation = QuestionnaireResponseFactory.build(
        questionnaire_id=test_questionnaire.id, company_id=test_company.id
    )
    db_session.add(invitation)
    db_session.flush()
    return invitation


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("routers.public._check_rate_limit", return_value=True):
        yield


@pytest.mark.asyncio
async def test_public_get_questionnaire(client, test_invitation, test_questionnaire):
    resp = await client.get(f"/questionnaire/{test_invitation.token}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is False
    assert data["title"] == test_questionnaire.title
    assert len(data["questions"]) == 2
    assert data["questions"][1]["options"] == ["Oui", "Non"]
    # no internal data leaks
    assert "company_id" not in data
    assert "respondent_email" not in data


@pytest.mark.asyncio
async def test_public_get_unknown_token_404(client):
    resp = await client.get("/questionnaire/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_public_submit_success_then_conflict(client, db_session, test_invitation, test_questionnaire):
    q_open, q_choice = test_questionnaire.questions
    payload = {
        "respondent_name": "Marie",
        "answers": [
            {"question_id": q_open.id, "value": "Très bien"},
            {"question_id": q_choice.id, "value": "Oui"},
        ],
    }
    resp = await client.post(f"/questionnaire/{test_invitation.token}/submit", json=payload)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    db_session.refresh(test_invitation)
    assert test_invitation.status == "completed"
    assert test_invitation.respondent_name == "Marie"
    assert len(test_invitation.answers) == 2

    again = await client.get(f"/questionnaire/{test_invitation.token}")
    assert again.json()["completed"] is True

    resubmit = await client.post(f"/questionnaire/{test_invitation.token}/submit", json=payload)
    assert resubmit.status_code == 409


@pytest.mark.asyncio
async def test_public_submit_missing_required_422(client, test_invitation, test_questionnaire):
    q_open = test_questionnaire.questions[0]
    resp = await client.post(
        f"/questionnaire/{test_invitation.token}/submit",
        json={"answers": [{"question_id": q_open.id, "value": "Seule réponse"}]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_public_submit_invalid_choice_422(client, test_invitation, test_questionnaire):
    q_open, q_choice = test_questionnaire.questions
    resp = await client.post(
        f"/questionnaire/{test_invitation.token}/submit",
        json={
            "answers": [
                {"question_id": q_open.id, "value": "ok"},
                {"question_id": q_choice.id, "value": "Peut-être"},  # not in ["Oui","Non"]
            ]
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_public_submit_unknown_question_422(client, test_invitation, test_questionnaire):
    q_open, q_choice = test_questionnaire.questions
    resp = await client.post(
        f"/questionnaire/{test_invitation.token}/submit",
        json={
            "answers": [
                {"question_id": q_open.id, "value": "ok"},
                {"question_id": q_choice.id, "value": "Oui"},
                {"question_id": 999999, "value": "x"},
            ]
        },
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

```bash
cd backend && python -m pytest tests/test_questionnaires.py -v -k "public"
```
Expected: FAIL (404, routes removed in Task 1).

- [ ] **Step 3: Implement the public endpoints in `backend/routers/public.py`**

Update imports at the top of the file:

```python
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, Agent, QuestionnaireAnswer, QuestionnaireResponse
from helpers.agent_helpers import resolve_model_id
from helpers.rate_limiting import _check_rate_limit
from rag_engine import get_answer
from schemas.public import PublicChatRequest
from schemas.questionnaires import PublicSubmitRequest
```

Append at the end of the file:

```python
##### Public questionnaire endpoints (token-based, no auth) #####


def _validate_answer_value(question, value):
    """Validate a submitted value against its question type.

    Returns the string to store, or None when the (optional) question was
    left unanswered. Raises HTTPException(422) on invalid values.
    """
    if value is None or value == "" or value == []:
        return None
    options = json.loads(question.options) if question.options else None

    if question.question_type == "open":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: texte attendu")
        return value[:10000]

    if question.question_type == "single_choice":
        if not isinstance(value, str) or (isinstance(options, list) and value not in options):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: choix invalide")
        return value

    if question.question_type == "multiple_choice":
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(v, str) for v in value)
        ):
            raise HTTPException(
                status_code=422, detail=f"Question {question.id}: liste de choix attendue"
            )
        if isinstance(options, list) and any(v not in options for v in value):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: choix invalide")
        return json.dumps(value)

    if question.question_type == "rating":
        try:
            rating = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"Question {question.id}: note attendue")
        bounds = options if isinstance(options, dict) else {"min": 1, "max": 5}
        if not (bounds.get("min", 1) <= rating <= bounds.get("max", 5)):
            raise HTTPException(
                status_code=422, detail=f"Question {question.id}: note hors limites"
            )
        return str(rating)

    return None


@router.get("/questionnaire/{token}")
async def public_get_questionnaire(token: str, request: Request, db: Session = Depends(get_db)):
    """Return the questionnaire form data for a respondent token. Rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    response = (
        db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")

    if response.status == "completed":
        return {"completed": True}

    questionnaire = response.questionnaire
    return {
        "completed": False,
        "title": questionnaire.title,
        "description": questionnaire.description,
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text,
                "question_type": q.question_type,
                "options": json.loads(q.options) if q.options else None,
                "position": q.position,
                "required": q.required,
            }
            for q in questionnaire.questions
        ],
    }


@router.post("/questionnaire/{token}/submit")
async def public_submit_questionnaire(
    token: str, body: PublicSubmitRequest, request: Request, db: Session = Depends(get_db)
):
    """Single-shot submit of all answers. Rate-limited by IP."""
    ip = request.client.host if hasattr(request, "client") and request.client else "unknown"
    if not _check_rate_limit(ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    response = (
        db.query(QuestionnaireResponse).filter(QuestionnaireResponse.token == token).first()
    )
    if not response:
        raise HTTPException(status_code=404, detail="Questionnaire not found")
    if response.status == "completed":
        raise HTTPException(status_code=409, detail="Ce questionnaire a déjà été complété.")

    questions = {q.id: q for q in response.questionnaire.questions}

    provided = {}
    for item in body.answers:
        if item.question_id not in questions:
            raise HTTPException(
                status_code=422, detail=f"Question inconnue : {item.question_id}"
            )
        provided[item.question_id] = item.value

    missing = [
        q.id
        for q in questions.values()
        if q.required and provided.get(q.id) in (None, "", [])
    ]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "Questions obligatoires sans réponse", "missing_question_ids": missing},
        )

    for question_id, value in provided.items():
        answer_text = _validate_answer_value(questions[question_id], value)
        if answer_text is None:
            continue
        db.add(
            QuestionnaireAnswer(
                response_id=response.id,
                question_id=question_id,
                company_id=response.company_id,
                answer_text=answer_text,
            )
        )

    if body.respondent_name:
        response.respondent_name = body.respondent_name.strip()[:255]
    response.status = "completed"
    response.completed_at = datetime.utcnow()
    db.commit()
    return {"success": True}
```

- [ ] **Step 4: Run the full backend suite, then commit**

```bash
cd backend && python -m pytest tests/ -q && ruff check .
git add backend/routers/public.py backend/tests/test_questionnaires.py
git commit -m "feat(api): public questionnaire form endpoints (get by token, single submit)"
```

---

## Task 10: Frontend foundation — locales, nav entry, Automations page shell

**Files:**
- Create: `frontend/public/locales/fr/automations.json`, `frontend/public/locales/en/automations.json`
- Create: `frontend/public/locales/fr/questionnaire.json`, `frontend/public/locales/en/questionnaire.json`
- Modify: `frontend/public/locales/fr/common.json`, `frontend/public/locales/en/common.json` (navigation key)
- Modify: `frontend/components/Sidebar.js` (nav item)
- Create: `frontend/pages/automations.js`
- Create: `frontend/components/automations/questionnaire/constants.js`

- [ ] **Step 1: Create `frontend/public/locales/fr/automations.json`**

```json
{
  "title": "Automatisations",
  "subtitle": "Automatisez des tâches récurrentes pour votre organisation",
  "tabs": {
    "questionnaires": "Questionnaires"
  },
  "list": {
    "empty": "Aucun questionnaire pour le moment",
    "emptyHint": "Créez votre premier questionnaire pour recueillir des réponses par email.",
    "create": "Nouveau questionnaire",
    "questionCount": "{{count}} question(s)",
    "responseCount": "{{completed}}/{{invited}} réponse(s)",
    "deleteConfirm": "Supprimer ce questionnaire et toutes ses réponses ?",
    "deleted": "Questionnaire supprimé"
  },
  "editor": {
    "createTitle": "Nouveau questionnaire",
    "titleLabel": "Titre",
    "titlePlaceholder": "Ex : Enquête de satisfaction client",
    "descriptionLabel": "Description (visible par les répondants)",
    "descriptionPlaceholder": "Décrivez l'objectif de ce questionnaire…",
    "questionsTitle": "Questions",
    "addQuestion": "Ajouter une question",
    "noQuestions": "Aucune question. Ajoutez-en une pour commencer.",
    "save": "Enregistrer",
    "cancel": "Annuler",
    "saved": "Questionnaire enregistré",
    "titleRequired": "Le titre est requis",
    "questionTextRequired": "Chaque question doit avoir un intitulé",
    "lockedByResponses": "Des réponses ont déjà été reçues : le questionnaire n'est plus modifiable."
  },
  "builder": {
    "questionPlaceholder": "Intitulé de la question…",
    "questionType": "Type",
    "required": "Obligatoire",
    "addOption": "Ajouter une option",
    "optionPlaceholder": "Option {{n}}",
    "ratingMin": "Min",
    "ratingMax": "Max",
    "types": {
      "open": "Texte libre",
      "single_choice": "Choix unique",
      "multiple_choice": "Choix multiple",
      "rating": "Note"
    }
  },
  "detail": {
    "back": "Retour aux questionnaires",
    "tabs": {
      "questions": "Questions",
      "invitations": "Invitations",
      "responses": "Réponses"
    }
  },
  "invitations": {
    "title": "Inviter des répondants",
    "hint": "Une adresse par ligne. Format optionnel : email, Nom",
    "placeholder": "marie@exemple.com\njean@exemple.com, Jean Dupont",
    "send": "Envoyer les invitations",
    "sent": "{{count}} invitation(s) envoyée(s)",
    "skipped": "{{count}} adresse(s) déjà invitée(s)",
    "noEmails": "Saisissez au moins une adresse email valide",
    "listTitle": "Invitations",
    "empty": "Aucune invitation envoyée",
    "resend": "Renvoyer",
    "resent": "Invitation renvoyée",
    "emailFailed": "Email non envoyé",
    "status": {
      "pending": "En attente",
      "completed": "Complété"
    }
  },
  "responses": {
    "empty": "Aucune réponse pour le moment",
    "filterAll": "Toutes",
    "filterCompleted": "Complétées",
    "filterPending": "En attente",
    "loadMore": "Voir plus",
    "export": "Exporter vers un companion",
    "selectHint": "Cochez des réponses complétées pour les exporter",
    "deleteConfirm": "Supprimer cette invitation et ses réponses ?",
    "deleted": "Réponse supprimée"
  },
  "export": {
    "title": "Exporter vers le RAG d'un companion",
    "description": "Les réponses sélectionnées seront ajoutées à la base documentaire du companion choisi.",
    "targetLabel": "Companion cible",
    "selectAgent": "Choisir un companion…",
    "confirm": "Exporter {{count}} réponse(s)",
    "cancel": "Annuler",
    "success": "{{count}} réponse(s) exportée(s)",
    "error": "Échec de l'export"
  },
  "errors": {
    "loadFailed": "Erreur de chargement",
    "saveFailed": "Échec de l'enregistrement"
  }
}
```

- [ ] **Step 2: Create `frontend/public/locales/en/automations.json`**

```json
{
  "title": "Automations",
  "subtitle": "Automate recurring tasks for your organization",
  "tabs": {
    "questionnaires": "Questionnaires"
  },
  "list": {
    "empty": "No questionnaires yet",
    "emptyHint": "Create your first questionnaire to collect answers by email.",
    "create": "New questionnaire",
    "questionCount": "{{count}} question(s)",
    "responseCount": "{{completed}}/{{invited}} response(s)",
    "deleteConfirm": "Delete this questionnaire and all its responses?",
    "deleted": "Questionnaire deleted"
  },
  "editor": {
    "createTitle": "New questionnaire",
    "titleLabel": "Title",
    "titlePlaceholder": "E.g. Customer satisfaction survey",
    "descriptionLabel": "Description (visible to respondents)",
    "descriptionPlaceholder": "Describe the purpose of this questionnaire…",
    "questionsTitle": "Questions",
    "addQuestion": "Add a question",
    "noQuestions": "No questions yet. Add one to get started.",
    "save": "Save",
    "cancel": "Cancel",
    "saved": "Questionnaire saved",
    "titleRequired": "Title is required",
    "questionTextRequired": "Every question needs a label",
    "lockedByResponses": "Responses have been received: this questionnaire can no longer be edited."
  },
  "builder": {
    "questionPlaceholder": "Question label…",
    "questionType": "Type",
    "required": "Required",
    "addOption": "Add an option",
    "optionPlaceholder": "Option {{n}}",
    "ratingMin": "Min",
    "ratingMax": "Max",
    "types": {
      "open": "Free text",
      "single_choice": "Single choice",
      "multiple_choice": "Multiple choice",
      "rating": "Rating"
    }
  },
  "detail": {
    "back": "Back to questionnaires",
    "tabs": {
      "questions": "Questions",
      "invitations": "Invitations",
      "responses": "Responses"
    }
  },
  "invitations": {
    "title": "Invite respondents",
    "hint": "One address per line. Optional format: email, Name",
    "placeholder": "marie@example.com\njohn@example.com, John Smith",
    "send": "Send invitations",
    "sent": "{{count}} invitation(s) sent",
    "skipped": "{{count}} address(es) already invited",
    "noEmails": "Enter at least one valid email address",
    "listTitle": "Invitations",
    "empty": "No invitations sent",
    "resend": "Resend",
    "resent": "Invitation resent",
    "emailFailed": "Email not sent",
    "status": {
      "pending": "Pending",
      "completed": "Completed"
    }
  },
  "responses": {
    "empty": "No responses yet",
    "filterAll": "All",
    "filterCompleted": "Completed",
    "filterPending": "Pending",
    "loadMore": "Load more",
    "export": "Export to a companion",
    "selectHint": "Select completed responses to export them",
    "deleteConfirm": "Delete this invitation and its answers?",
    "deleted": "Response deleted"
  },
  "export": {
    "title": "Export to a companion's RAG",
    "description": "Selected responses will be added to the chosen companion's knowledge base.",
    "targetLabel": "Target companion",
    "selectAgent": "Choose a companion…",
    "confirm": "Export {{count}} response(s)",
    "cancel": "Cancel",
    "success": "{{count}} response(s) exported",
    "error": "Export failed"
  },
  "errors": {
    "loadFailed": "Failed to load",
    "saveFailed": "Failed to save"
  }
}
```

- [ ] **Step 3: Create the public-page locales**

`frontend/public/locales/fr/questionnaire.json`:

```json
{
  "loading": "Chargement…",
  "notFound": "Questionnaire introuvable ou lien invalide.",
  "alreadyCompleted": "Vous avez déjà répondu à ce questionnaire. Merci pour votre participation !",
  "form": {
    "nameLabel": "Votre nom (optionnel)",
    "namePlaceholder": "Jean Dupont",
    "required": "Cette question est obligatoire",
    "openPlaceholder": "Votre réponse…",
    "submit": "Envoyer mes réponses",
    "submitting": "Envoi…"
  },
  "success": {
    "title": "Merci pour vos réponses !",
    "message": "Vos réponses ont bien été enregistrées. Vous pouvez fermer cette page."
  },
  "error": "Une erreur s'est produite. Veuillez réessayer."
}
```

`frontend/public/locales/en/questionnaire.json`:

```json
{
  "loading": "Loading…",
  "notFound": "Questionnaire not found or invalid link.",
  "alreadyCompleted": "You have already answered this questionnaire. Thank you!",
  "form": {
    "nameLabel": "Your name (optional)",
    "namePlaceholder": "John Smith",
    "required": "This question is required",
    "openPlaceholder": "Your answer…",
    "submit": "Submit my answers",
    "submitting": "Submitting…"
  },
  "success": {
    "title": "Thank you for your answers!",
    "message": "Your answers have been saved. You can close this page."
  },
  "error": "Something went wrong. Please try again."
}
```

- [ ] **Step 4: Add the navigation key to common.json**

In `frontend/public/locales/fr/common.json`, inside `"navigation"` (after `"templates": "Templates",`): add `"automations": "Automatisations",`.
In `frontend/public/locales/en/common.json`, same place: add `"automations": "Automations",`.

- [ ] **Step 5: Add the nav item in `frontend/components/Sidebar.js`**

Add `Zap` to the lucide-react import, then in `NAV_ITEMS` insert after the templates entry:

```js
  { href: '/automations',  labelKey: 'navigation.automations',  Icon: Zap },
```

- [ ] **Step 6: Create `frontend/components/automations/questionnaire/constants.js`**

```js
export const QUESTION_TYPES = ['open', 'single_choice', 'multiple_choice', 'rating'];

export const STATUS_BADGE_CLASSES = {
  pending: 'bg-amber-50 text-amber-700',
  completed: 'bg-green-50 text-green-700',
};

export const EXPORTABLE_AGENT_TYPES = ['conversationnel', 'actionnable'];
```

- [ ] **Step 7: Create `frontend/pages/automations.js`**

```jsx
import { useState } from 'react';
import { Toaster } from 'react-hot-toast';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { ClipboardList } from 'lucide-react';
import Layout from '../components/Layout';
import { useAuth } from '../hooks/useAuth';
import QuestionnairesTab from '../components/automations/questionnaire/QuestionnairesTab';

const TABS = [
  { key: 'questionnaires', labelKey: 'tabs.questionnaires', Icon: ClipboardList },
];

export default function AutomationsPage() {
  const { t } = useTranslation(['automations', 'common', 'errors']);
  const { loading: authLoading, authenticated } = useAuth();
  const [activeTab, setActiveTab] = useState('questionnaires');

  if (authLoading || !authenticated) return null;

  return (
    <Layout title={t('title')}>
      <Toaster position="top-right" />
      <div className="px-8 py-6 max-w-5xl">
        <p className="text-sm text-gray-500 mb-6">{t('subtitle')}</p>

        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {TABS.map(({ key, labelKey, Icon }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                activeTab === key
                  ? 'border-primary-600 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon className="w-4 h-4" />
              {t(labelKey)}
            </button>
          ))}
        </div>

        {activeTab === 'questionnaires' && <QuestionnairesTab />}
      </div>
    </Layout>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['automations', 'common', 'errors'])),
    },
  };
}
```

(`QuestionnairesTab` does not exist yet — Task 11 creates it. To keep this commit green, create a placeholder now:)

`frontend/components/automations/questionnaire/QuestionnairesTab.js` (placeholder, replaced in Task 11):

```jsx
export default function QuestionnairesTab() {
  return null;
}
```

- [ ] **Step 8: Lint and commit**

```bash
cd frontend && npm run lint
git add frontend/public/locales frontend/components/Sidebar.js frontend/pages/automations.js frontend/components/automations
git commit -m "feat(ui): Automations page shell with nav entry and i18n"
```

---

## Task 11: Frontend — QuestionCard, QuestionnaireEditor, QuestionnaireList, QuestionnairesTab

**Files:**
- Create: `frontend/components/automations/questionnaire/QuestionCard.js`
- Create: `frontend/components/automations/questionnaire/QuestionnaireEditor.js`
- Create: `frontend/components/automations/questionnaire/QuestionnaireList.js`
- Modify (replace placeholder): `frontend/components/automations/questionnaire/QuestionnairesTab.js`

- [ ] **Step 1: Create `QuestionCard.js`**

Same UX as the old card (text input, type select, options editor, rating bounds, required toggle), `automations` namespace, options handled as a JSON string in component state:

```jsx
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { GripVertical, Trash2, ChevronDown, ChevronUp, Plus, X, Star, ToggleLeft, ToggleRight } from 'lucide-react';
import { QUESTION_TYPES } from './constants';

export default function QuestionCard({ question, index, onChange, onDelete, disabled = false }) {
  const { t } = useTranslation('automations');
  const [expanded, setExpanded] = useState(true);

  const parsedOptions = (() => {
    if (!question.options) return [];
    try { return JSON.parse(question.options); } catch { return []; }
  })();

  const ratingConfig = (() => {
    if (question.question_type !== 'rating' || !question.options) return { min: 1, max: 5 };
    try { return JSON.parse(question.options); } catch { return { min: 1, max: 5 }; }
  })();

  const updateField = (field, value) => onChange({ ...question, [field]: value });
  const updateOptions = (opts) => updateField('options', JSON.stringify(opts));
  const updateRatingConfig = (key, value) => {
    const cfg = { ...ratingConfig, [key]: parseInt(value, 10) || 1 };
    updateField('options', JSON.stringify(cfg));
  };

  const addOption = () => updateOptions([...parsedOptions, '']);
  const removeOption = (idx) => updateOptions(parsedOptions.filter((_, i) => i !== idx));
  const setOptionValue = (idx, value) => {
    const next = [...parsedOptions];
    next[idx] = value;
    updateOptions(next);
  };

  const changeType = (newType) => {
    const update = { ...question, question_type: newType };
    if (newType === 'rating') {
      update.options = JSON.stringify({ min: 1, max: 5 });
    } else if (newType === 'open') {
      update.options = null;
    } else if (!Array.isArray(parsedOptions) || !parsedOptions.length) {
      update.options = JSON.stringify(['']);
    }
    onChange(update);
  };

  return (
    <div className="border border-gray-200 rounded-card bg-white shadow-subtle">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100">
        <GripVertical className="w-4 h-4 text-gray-300" />
        <span className="text-sm font-semibold text-gray-500 w-6">{index + 1}.</span>
        <span className="flex-1 text-sm font-medium text-gray-800 truncate">
          {question.question_text || t('builder.questionPlaceholder')}
        </span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-primary-50 text-primary-700 font-medium">
          {t(`builder.types.${question.question_type}`)}
        </span>
        <button onClick={() => setExpanded(!expanded)} className="p-1 text-gray-400 hover:text-gray-600">
          {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {!disabled && (
          <button onClick={onDelete} className="p-1 text-gray-400 hover:text-red-500">
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {expanded && (
        <div className="px-4 py-4 space-y-4">
          <input
            type="text"
            value={question.question_text}
            disabled={disabled}
            onChange={(e) => updateField('question_text', e.target.value)}
            placeholder={t('builder.questionPlaceholder')}
            className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
          />

          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-600 font-medium">{t('builder.questionType')}</label>
            <select
              value={question.question_type}
              disabled={disabled}
              onChange={(e) => changeType(e.target.value)}
              className="px-3 py-1.5 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500"
            >
              {QUESTION_TYPES.map((qt) => (
                <option key={qt} value={qt}>{t(`builder.types.${qt}`)}</option>
              ))}
            </select>

            <button
              onClick={() => !disabled && updateField('required', !question.required)}
              className="ml-auto flex items-center gap-1.5 text-sm text-gray-600"
            >
              {question.required ? (
                <ToggleRight className="w-5 h-5 text-primary-600" />
              ) : (
                <ToggleLeft className="w-5 h-5 text-gray-400" />
              )}
              {t('builder.required')}
            </button>
          </div>

          {(question.question_type === 'single_choice' || question.question_type === 'multiple_choice') && (
            <div className="space-y-2">
              {parsedOptions.map((opt, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-5">{idx + 1}.</span>
                  <input
                    type="text"
                    value={opt}
                    disabled={disabled}
                    onChange={(e) => setOptionValue(idx, e.target.value)}
                    placeholder={t('builder.optionPlaceholder', { n: idx + 1 })}
                    className="flex-1 px-3 py-1.5 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500"
                  />
                  {!disabled && (
                    <button onClick={() => removeOption(idx)} className="p-1 text-gray-400 hover:text-red-500">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              ))}
              {!disabled && (
                <button onClick={addOption} className="flex items-center gap-1 text-sm text-primary-600 hover:text-primary-700 font-medium">
                  <Plus className="w-3.5 h-3.5" />
                  {t('builder.addOption')}
                </button>
              )}
            </div>
          )}

          {question.question_type === 'rating' && (
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMin')}</label>
                <input
                  type="number"
                  value={ratingConfig.min}
                  disabled={disabled}
                  onChange={(e) => updateRatingConfig('min', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="0" max="10"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-600">{t('builder.ratingMax')}</label>
                <input
                  type="number"
                  value={ratingConfig.max}
                  disabled={disabled}
                  onChange={(e) => updateRatingConfig('max', e.target.value)}
                  className="w-16 px-2 py-1.5 border border-gray-200 rounded-input text-sm text-center"
                  min="1" max="10"
                />
              </div>
              <div className="flex items-center gap-1 ml-4">
                {Array.from({ length: Math.max(0, ratingConfig.max - ratingConfig.min + 1) }, (_, i) => (
                  <Star key={i} className="w-5 h-5 text-yellow-400 fill-yellow-400" />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create `QuestionnaireEditor.js`**

```jsx
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Plus, Save, Lock } from 'lucide-react';
import api from '../../../lib/api';
import QuestionCard from './QuestionCard';

export default function QuestionnaireEditor({ questionnaire = null, onSaved, onCancel }) {
  const { t } = useTranslation('automations');
  const isEdit = Boolean(questionnaire?.id);
  const locked = isEdit && (questionnaire.completed_count || 0) > 0;

  const [title, setTitle] = useState(questionnaire?.title || '');
  const [description, setDescription] = useState(questionnaire?.description || '');
  const [questions, setQuestions] = useState(
    (questionnaire?.questions || []).map((q) => ({
      ...q,
      options:
        q.options != null && typeof q.options !== 'string'
          ? JSON.stringify(q.options)
          : q.options,
    }))
  );
  const [saving, setSaving] = useState(false);

  const addQuestion = () =>
    setQuestions((qs) => [
      ...qs,
      { question_text: '', question_type: 'open', options: null, required: true },
    ]);
  const updateQuestion = (idx, next) =>
    setQuestions((qs) => qs.map((q, i) => (i === idx ? next : q)));
  const deleteQuestion = (idx) => setQuestions((qs) => qs.filter((_, i) => i !== idx));

  const save = async () => {
    if (!title.trim()) {
      toast.error(t('editor.titleRequired'));
      return;
    }
    if (!questions.length || questions.some((q) => !q.question_text.trim())) {
      toast.error(questions.length ? t('editor.questionTextRequired') : t('editor.noQuestions'));
      return;
    }
    const payload = {
      title: title.trim(),
      description: description.trim() || null,
      questions: questions.map((q, idx) => ({
        question_text: q.question_text.trim(),
        question_type: q.question_type,
        options: q.options ? JSON.parse(q.options) : null,
        position: idx,
        required: Boolean(q.required),
      })),
    };
    setSaving(true);
    try {
      const res = isEdit
        ? await api.put(`/api/automations/questionnaires/${questionnaire.id}`, payload)
        : await api.post('/api/automations/questionnaires', payload);
      toast.success(t('editor.saved'));
      onSaved?.(res.data.questionnaire);
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : t('errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {!isEdit && <h2 className="text-lg font-bold text-gray-900">{t('editor.createTitle')}</h2>}

      {locked && (
        <div className="flex items-center gap-2 px-4 py-3 bg-amber-50 border border-amber-200 rounded-card text-sm text-amber-800">
          <Lock className="w-4 h-4 shrink-0" />
          {t('editor.lockedByResponses')}
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('editor.titleLabel')}</label>
        <input
          type="text"
          value={title}
          disabled={locked}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('editor.titlePlaceholder')}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1.5">{t('editor.descriptionLabel')}</label>
        <textarea
          value={description}
          disabled={locked}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('editor.descriptionPlaceholder')}
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 disabled:bg-gray-50"
        />
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{t('editor.questionsTitle')}</h3>
        {questions.length === 0 && (
          <p className="text-sm text-gray-400 mb-3">{t('editor.noQuestions')}</p>
        )}
        <div className="space-y-3">
          {questions.map((q, idx) => (
            <QuestionCard
              key={q.id ?? `new-${idx}`}
              question={q}
              index={idx}
              disabled={locked}
              onChange={(next) => updateQuestion(idx, next)}
              onDelete={() => deleteQuestion(idx)}
            />
          ))}
        </div>
        {!locked && (
          <button
            onClick={addQuestion}
            className="mt-3 flex items-center gap-1.5 text-sm text-primary-600 hover:text-primary-700 font-medium"
          >
            <Plus className="w-4 h-4" />
            {t('editor.addQuestion')}
          </button>
        )}
      </div>

      <div className="flex items-center gap-3 pt-2">
        {!locked && (
          <button
            onClick={save}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {t('editor.save')}
          </button>
        )}
        {onCancel && (
          <button
            onClick={onCancel}
            className="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-800"
          >
            {t('editor.cancel')}
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `QuestionnaireList.js`**

```jsx
import { useTranslation } from 'next-i18next';
import { Plus, Trash2, ClipboardList } from 'lucide-react';

export default function QuestionnaireList({ questionnaires, onOpen, onCreate, onDelete }) {
  const { t } = useTranslation('automations');

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm text-gray-500">
          {questionnaires.length > 0 && `${questionnaires.length} questionnaire(s)`}
        </span>
        <button
          onClick={onCreate}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          {t('list.create')}
        </button>
      </div>

      {questionnaires.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-gray-200 rounded-card">
          <ClipboardList className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-sm font-medium text-gray-600">{t('list.empty')}</p>
          <p className="text-xs text-gray-400 mt-1">{t('list.emptyHint')}</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {questionnaires.map((q) => (
            <div
              key={q.id}
              onClick={() => onOpen(q.id)}
              className="flex items-center gap-4 px-5 py-4 bg-white border border-gray-200 rounded-card shadow-subtle hover:border-primary-300 cursor-pointer transition-colors"
            >
              <div className="w-10 h-10 rounded-sm bg-primary-50 flex items-center justify-center shrink-0">
                <ClipboardList className="w-5 h-5 text-primary-600" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-gray-900 truncate">{q.title}</p>
                {q.description && (
                  <p className="text-xs text-gray-400 truncate">{q.description}</p>
                )}
              </div>
              <div className="text-xs text-gray-500 text-right shrink-0">
                <p>{t('list.questionCount', { count: q.question_count })}</p>
                <p>{t('list.responseCount', { completed: q.completed_count, invited: q.invited_count })}</p>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(q.id);
                }}
                className="p-1.5 text-gray-300 hover:text-red-500 transition-colors"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Replace the `QuestionnairesTab.js` placeholder**

```jsx
import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import api from '../../../lib/api';
import QuestionnaireList from './QuestionnaireList';
import QuestionnaireEditor from './QuestionnaireEditor';
import QuestionnaireDetail from './QuestionnaireDetail';

export default function QuestionnairesTab() {
  const { t } = useTranslation('automations');
  const router = useRouter();
  const [questionnaires, setQuestionnaires] = useState([]);
  const [loading, setLoading] = useState(true);

  const selectedId = router.query.questionnaire
    ? parseInt(router.query.questionnaire, 10)
    : null;
  const creating = router.query.create === '1';

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/automations/questionnaires');
      setQuestionnaires(res.data.questionnaires || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const setQuery = (query) =>
    router.push({ pathname: '/automations', query }, undefined, { shallow: true });

  const handleDelete = async (id) => {
    if (!window.confirm(t('list.deleteConfirm'))) return;
    try {
      await api.delete(`/api/automations/questionnaires/${id}`);
      toast.success(t('list.deleted'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  if (loading) {
    return <div className="py-16 text-center text-sm text-gray-400">…</div>;
  }

  if (creating) {
    return (
      <QuestionnaireEditor
        onSaved={(q) => {
          load();
          setQuery({ questionnaire: q.id });
        }}
        onCancel={() => setQuery({})}
      />
    );
  }

  if (selectedId) {
    return (
      <QuestionnaireDetail
        questionnaireId={selectedId}
        onBack={() => {
          load();
          setQuery({});
        }}
      />
    );
  }

  return (
    <QuestionnaireList
      questionnaires={questionnaires}
      onOpen={(id) => setQuery({ questionnaire: id })}
      onCreate={() => setQuery({ create: '1' })}
      onDelete={handleDelete}
    />
  );
}
```

(`QuestionnaireDetail` arrives in Task 12 — create a placeholder now so lint passes:)

`frontend/components/automations/questionnaire/QuestionnaireDetail.js` (placeholder, replaced in Task 12):

```jsx
export default function QuestionnaireDetail() {
  return null;
}
```

- [ ] **Step 5: Lint and commit**

```bash
cd frontend && npm run lint
git add frontend/components/automations
git commit -m "feat(ui): questionnaire list, builder and editor in Automations tab"
```

---

## Task 12: Frontend — QuestionnaireDetail, InvitationsTab, ResponsesTab, ExportModal

**Files:**
- Modify (replace placeholder): `frontend/components/automations/questionnaire/QuestionnaireDetail.js`
- Create: `frontend/components/automations/questionnaire/InvitationsTab.js`
- Create: `frontend/components/automations/questionnaire/ResponsesTab.js`
- Create: `frontend/components/automations/questionnaire/ExportModal.js`

- [ ] **Step 1: Replace `QuestionnaireDetail.js`**

```jsx
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { ArrowLeft } from 'lucide-react';
import api from '../../../lib/api';
import QuestionnaireEditor from './QuestionnaireEditor';
import InvitationsTab from './InvitationsTab';
import ResponsesTab from './ResponsesTab';

const SUB_TABS = ['questions', 'invitations', 'responses'];

export default function QuestionnaireDetail({ questionnaireId, onBack }) {
  const { t } = useTranslation('automations');
  const [questionnaire, setQuestionnaire] = useState(null);
  const [subTab, setSubTab] = useState('questions');

  const load = useCallback(async () => {
    try {
      const res = await api.get(`/api/automations/questionnaires/${questionnaireId}`);
      setQuestionnaire(res.data.questionnaire);
    } catch {
      toast.error(t('errors.loadFailed'));
      onBack?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionnaireId]);

  useEffect(() => {
    load();
  }, [load]);

  if (!questionnaire) {
    return <div className="py-16 text-center text-sm text-gray-400">…</div>;
  }

  return (
    <div>
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-4 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        {t('detail.back')}
      </button>

      <h2 className="text-xl font-bold text-gray-900 mb-4">{questionnaire.title}</h2>

      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {SUB_TABS.map((key) => (
          <button
            key={key}
            onClick={() => setSubTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              subTab === key
                ? 'border-primary-600 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {t(`detail.tabs.${key}`)}
          </button>
        ))}
      </div>

      {subTab === 'questions' && (
        <QuestionnaireEditor questionnaire={questionnaire} onSaved={() => load()} />
      )}
      {subTab === 'invitations' && <InvitationsTab questionnaireId={questionnaire.id} />}
      {subTab === 'responses' && <ResponsesTab questionnaireId={questionnaire.id} />}
    </div>
  );
}
```

- [ ] **Step 2: Create `InvitationsTab.js`**

```jsx
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { Send, RefreshCw, AlertTriangle } from 'lucide-react';
import api from '../../../lib/api';
import { STATUS_BADGE_CLASSES } from './constants';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function parseRecipients(raw) {
  return raw
    .split(/[\n;]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [email, ...nameParts] = line.split(',').map((s) => s.trim());
      return { email: email.toLowerCase(), name: nameParts.join(', ') || null };
    })
    .filter((r) => EMAIL_RE.test(r.email));
}

export default function InvitationsTab({ questionnaireId }) {
  const { t } = useTranslation('automations');
  const [raw, setRaw] = useState('');
  const [sending, setSending] = useState(false);
  const [invitations, setInvitations] = useState([]);

  const load = useCallback(async () => {
    try {
      const res = await api.get(
        `/api/automations/questionnaires/${questionnaireId}/responses?limit=200`
      );
      setInvitations(res.data.responses || []);
    } catch {
      toast.error(t('errors.loadFailed'));
    }
  }, [questionnaireId, t]);

  useEffect(() => {
    load();
  }, [load]);

  const send = async () => {
    const recipients = parseRecipients(raw);
    if (!recipients.length) {
      toast.error(t('invitations.noEmails'));
      return;
    }
    setSending(true);
    try {
      const res = await api.post(
        `/api/automations/questionnaires/${questionnaireId}/invite`,
        { recipients }
      );
      toast.success(t('invitations.sent', { count: res.data.invited }));
      if (res.data.skipped > 0) {
        toast(t('invitations.skipped', { count: res.data.skipped }));
      }
      setRaw('');
      load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : t('errors.saveFailed'));
    } finally {
      setSending(false);
    }
  };

  const resend = async (responseId) => {
    try {
      await api.post(
        `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}/resend`
      );
      toast.success(t('invitations.resent'));
      load();
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  return (
    <div className="space-y-8">
      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-1">{t('invitations.title')}</h3>
        <p className="text-xs text-gray-400 mb-3">{t('invitations.hint')}</p>
        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder={t('invitations.placeholder')}
          rows={4}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
        <button
          onClick={send}
          disabled={sending}
          className="mt-3 flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
        >
          <Send className="w-4 h-4" />
          {t('invitations.send')}
        </button>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-gray-800 mb-3">{t('invitations.listTitle')}</h3>
        {invitations.length === 0 ? (
          <p className="text-sm text-gray-400">{t('invitations.empty')}</p>
        ) : (
          <div className="border border-gray-200 rounded-card divide-y divide-gray-100 bg-white">
            {invitations.map((inv) => (
              <div key={inv.id} className="flex items-center gap-3 px-4 py-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">{inv.respondent_email}</p>
                  {inv.respondent_name && (
                    <p className="text-xs text-gray-400">{inv.respondent_name}</p>
                  )}
                </div>
                {!inv.email_sent && inv.status === 'pending' && (
                  <span
                    className="flex items-center gap-1 text-xs text-amber-600"
                    title={t('invitations.emailFailed')}
                  >
                    <AlertTriangle className="w-3.5 h-3.5" />
                    {t('invitations.emailFailed')}
                  </span>
                )}
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE_CLASSES[inv.status] || 'bg-gray-50 text-gray-600'}`}
                >
                  {t(`invitations.status.${inv.status}`)}
                </span>
                {inv.status === 'pending' && (
                  <button
                    onClick={() => resend(inv.id)}
                    className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 font-medium"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    {t('invitations.resend')}
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create `ResponsesTab.js`**

```jsx
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { ChevronDown, ChevronUp, Trash2, Upload } from 'lucide-react';
import api from '../../../lib/api';
import ExportModal from './ExportModal';
import { STATUS_BADGE_CLASSES } from './constants';

const PAGE_SIZE = 50;

export default function ResponsesTab({ questionnaireId }) {
  const { t } = useTranslation('automations');
  const [responses, setResponses] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState(null); // null | 'pending' | 'completed'
  const [details, setDetails] = useState({}); // responseId -> answers[]
  const [expanded, setExpanded] = useState(null);
  const [selected, setSelected] = useState([]);
  const [showExport, setShowExport] = useState(false);

  const load = useCallback(
    async (offset = 0, append = false) => {
      try {
        const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
        if (statusFilter) params.set('status', statusFilter);
        const res = await api.get(
          `/api/automations/questionnaires/${questionnaireId}/responses?${params}`
        );
        setResponses((prev) => (append ? [...prev, ...res.data.responses] : res.data.responses));
        setTotal(res.data.total);
      } catch {
        toast.error(t('errors.loadFailed'));
      }
    },
    [questionnaireId, statusFilter, t]
  );

  useEffect(() => {
    setSelected([]);
    setExpanded(null);
    load(0);
  }, [load]);

  const toggleExpand = async (responseId) => {
    if (expanded === responseId) {
      setExpanded(null);
      return;
    }
    setExpanded(responseId);
    if (!details[responseId]) {
      try {
        const res = await api.get(
          `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}`
        );
        setDetails((d) => ({ ...d, [responseId]: res.data.response.answers || [] }));
      } catch {
        toast.error(t('errors.loadFailed'));
      }
    }
  };

  const toggleSelect = (responseId) => {
    setSelected((sel) =>
      sel.includes(responseId) ? sel.filter((id) => id !== responseId) : [...sel, responseId]
    );
  };

  const handleDelete = async (responseId) => {
    if (!window.confirm(t('responses.deleteConfirm'))) return;
    try {
      await api.delete(
        `/api/automations/questionnaires/${questionnaireId}/responses/${responseId}`
      );
      toast.success(t('responses.deleted'));
      load(0);
    } catch {
      toast.error(t('errors.saveFailed'));
    }
  };

  const formatAnswer = (answer) => {
    if (answer.question_type === 'multiple_choice' && answer.answer_text) {
      try {
        return JSON.parse(answer.answer_text).join(', ');
      } catch {
        return answer.answer_text;
      }
    }
    return answer.answer_text || '—';
  };

  const FILTERS = [
    { value: null, label: t('responses.filterAll') },
    { value: 'completed', label: t('responses.filterCompleted') },
    { value: 'pending', label: t('responses.filterPending') },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={String(f.value)}
              onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1.5 text-xs font-medium rounded-full transition-colors ${
                statusFilter === f.value
                  ? 'bg-primary-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => setShowExport(true)}
          disabled={!selected.length}
          title={t('responses.selectHint')}
          className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-40"
        >
          <Upload className="w-4 h-4" />
          {t('responses.export')}
        </button>
      </div>

      {responses.length === 0 ? (
        <p className="text-sm text-gray-400 py-8 text-center">{t('responses.empty')}</p>
      ) : (
        <div className="border border-gray-200 rounded-card divide-y divide-gray-100 bg-white">
          {responses.map((r) => (
            <div key={r.id}>
              <div className="flex items-center gap-3 px-4 py-3">
                <input
                  type="checkbox"
                  checked={selected.includes(r.id)}
                  disabled={r.status !== 'completed'}
                  onChange={() => toggleSelect(r.id)}
                  className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 disabled:opacity-30"
                />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">
                    {r.respondent_name || r.respondent_email}
                  </p>
                  {r.completed_at && (
                    <p className="text-xs text-gray-400">
                      {new Date(r.completed_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE_CLASSES[r.status] || 'bg-gray-50 text-gray-600'}`}
                >
                  {t(`invitations.status.${r.status}`)}
                </span>
                {r.status === 'completed' && (
                  <button
                    onClick={() => toggleExpand(r.id)}
                    className="p-1 text-gray-400 hover:text-gray-600"
                  >
                    {expanded === r.id ? (
                      <ChevronUp className="w-4 h-4" />
                    ) : (
                      <ChevronDown className="w-4 h-4" />
                    )}
                  </button>
                )}
                <button
                  onClick={() => handleDelete(r.id)}
                  className="p-1 text-gray-300 hover:text-red-500"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
              {expanded === r.id && (
                <div className="px-12 pb-4 space-y-3">
                  {(details[r.id] || []).map((a) => (
                    <div key={a.question_id}>
                      <p className="text-xs font-semibold text-gray-600">{a.question_text}</p>
                      <p className="text-sm text-gray-800">{formatAnswer(a)}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {responses.length < total && (
        <button
          onClick={() => load(responses.length, true)}
          className="mt-4 text-sm text-primary-600 hover:text-primary-700 font-medium"
        >
          {t('responses.loadMore')}
        </button>
      )}

      {showExport && (
        <ExportModal
          questionnaireId={questionnaireId}
          responseIds={selected}
          onClose={() => setShowExport(false)}
          onExported={() => {
            setSelected([]);
            load(0);
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create `ExportModal.js`**

```jsx
import { useState, useEffect } from 'react';
import { useTranslation } from 'next-i18next';
import toast from 'react-hot-toast';
import { X, Upload } from 'lucide-react';
import api from '../../../lib/api';
import { EXPORTABLE_AGENT_TYPES } from './constants';

export default function ExportModal({ questionnaireId, responseIds, onClose, onExported }) {
  const { t } = useTranslation('automations');
  const [agents, setAgents] = useState([]);
  const [targetAgentId, setTargetAgentId] = useState('');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    api
      .get('/agents')
      .then((res) =>
        setAgents(
          (res.data.agents || []).filter((a) => EXPORTABLE_AGENT_TYPES.includes(a.type))
        )
      )
      .catch(() => setAgents([]));
  }, []);

  const doExport = async () => {
    setExporting(true);
    try {
      const res = await api.post(`/api/automations/questionnaires/${questionnaireId}/export`, {
        response_ids: responseIds,
        target_agent_id: parseInt(targetAgentId, 10),
      });
      toast.success(t('export.success', { count: res.data.exported }));
      onExported?.();
      onClose();
    } catch {
      toast.error(t('export.error'));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-card shadow-lg w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold text-gray-900">{t('export.title')}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-gray-500 mb-4">{t('export.description')}</p>

        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {t('export.targetLabel')}
        </label>
        <select
          value={targetAgentId}
          onChange={(e) => setTargetAgentId(e.target.value)}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm bg-white focus:ring-2 focus:ring-primary-500 mb-6"
        >
          <option value="">{t('export.selectAgent')}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>

        <div className="flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800"
          >
            {t('export.cancel')}
          </button>
          <button
            onClick={doExport}
            disabled={exporting || !targetAgentId}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
          >
            <Upload className="w-4 h-4" />
            {t('export.confirm', { count: responseIds.length })}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Lint and commit**

```bash
cd frontend && npm run lint
git add frontend/components/automations
git commit -m "feat(ui): questionnaire detail with invitations, responses and RAG export"
```

---

## Task 13: Public form page + final sweep

**Files:**
- Create: `frontend/pages/questionnaire/[token].js`

- [ ] **Step 1: Create `frontend/pages/questionnaire/[token].js`**

```jsx
import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import Head from 'next/head';
import { useTranslation } from 'next-i18next';
import { serverSideTranslations } from 'next-i18next/serverSideTranslations';
import { Star, CheckCircle, Send, AlertTriangle } from 'lucide-react';
import api from '../../lib/api';

function QuestionField({ question, value, error, onChange, t }) {
  const options = question.options;

  return (
    <div className={`bg-white rounded-card border p-5 ${error ? 'border-red-300' : 'border-gray-200'}`}>
      <p className="text-sm font-semibold text-gray-800 mb-3">
        {question.question_text}
        {question.required && <span className="text-red-500 ml-1">*</span>}
      </p>

      {question.question_type === 'open' && (
        <textarea
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={t('form.openPlaceholder')}
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      )}

      {question.question_type === 'single_choice' && (
        <div className="space-y-2">
          {(options || []).map((opt) => (
            <label key={opt} className="flex items-center gap-2.5 cursor-pointer">
              <input
                type="radio"
                name={`q-${question.id}`}
                checked={value === opt}
                onChange={() => onChange(opt)}
                className="w-4 h-4 border-gray-300 text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-gray-700">{opt}</span>
            </label>
          ))}
        </div>
      )}

      {question.question_type === 'multiple_choice' && (
        <div className="space-y-2">
          {(options || []).map((opt) => {
            const list = Array.isArray(value) ? value : [];
            return (
              <label key={opt} className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={list.includes(opt)}
                  onChange={() =>
                    onChange(
                      list.includes(opt) ? list.filter((v) => v !== opt) : [...list, opt]
                    )
                  }
                  className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                />
                <span className="text-sm text-gray-700">{opt}</span>
              </label>
            );
          })}
        </div>
      )}

      {question.question_type === 'rating' && (
        <div className="flex items-center gap-1">
          {(() => {
            const min = options?.min ?? 1;
            const max = options?.max ?? 5;
            return Array.from({ length: max - min + 1 }, (_, i) => min + i).map((n) => (
              <button key={n} type="button" onClick={() => onChange(n)} className="p-0.5">
                <Star
                  className={`w-7 h-7 transition-colors ${
                    value != null && n <= value
                      ? 'text-yellow-400 fill-yellow-400'
                      : 'text-gray-200'
                  }`}
                />
              </button>
            ));
          })()}
        </div>
      )}

      {error && <p className="text-xs text-red-500 mt-2">{t('form.required')}</p>}
    </div>
  );
}

export default function PublicQuestionnairePage() {
  const router = useRouter();
  const { token } = router.query;
  const { t } = useTranslation('questionnaire');

  // loading | form | completed | success | notFound | error
  const [state, setState] = useState('loading');
  const [questionnaire, setQuestionnaire] = useState(null);
  const [answers, setAnswers] = useState({});
  const [errors, setErrors] = useState({});
  const [respondentName, setRespondentName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .get(`/questionnaire/${token}`)
      .then((res) => {
        if (res.data.completed) {
          setState('completed');
        } else {
          setQuestionnaire(res.data);
          setState('form');
        }
      })
      .catch((err) => setState(err.response?.status === 404 ? 'notFound' : 'error'));
  }, [token]);

  const setAnswer = (questionId, value) => {
    setAnswers((a) => ({ ...a, [questionId]: value }));
    setErrors((e) => ({ ...e, [questionId]: false }));
  };

  const submit = async () => {
    const missing = {};
    for (const q of questionnaire.questions) {
      const v = answers[q.id];
      if (q.required && (v === undefined || v === '' || (Array.isArray(v) && !v.length))) {
        missing[q.id] = true;
      }
    }
    if (Object.keys(missing).length) {
      setErrors(missing);
      return;
    }
    setSubmitting(true);
    setSubmitError(false);
    try {
      await api.post(`/questionnaire/${token}/submit`, {
        respondent_name: respondentName.trim() || null,
        answers: Object.entries(answers).map(([qid, value]) => ({
          question_id: parseInt(qid, 10),
          value,
        })),
      });
      setState('success');
    } catch (err) {
      if (err.response?.status === 409) setState('completed');
      else setSubmitError(true);
    } finally {
      setSubmitting(false);
    }
  };

  const Shell = ({ children }) => (
    <div className="min-h-screen bg-slate-50 py-10 px-4">
      <Head>
        <title>{questionnaire?.title || 'Questionnaire'} — TAIC</title>
      </Head>
      <div className="max-w-2xl mx-auto">{children}</div>
    </div>
  );

  const CenteredMessage = ({ icon, text }) => (
    <div className="bg-white rounded-card border border-gray-200 p-10 text-center">
      {icon}
      <p className="text-sm text-gray-600">{text}</p>
    </div>
  );

  if (state === 'loading') {
    return (
      <Shell>
        <CenteredMessage icon={null} text={t('loading')} />
      </Shell>
    );
  }
  if (state === 'notFound' || state === 'error') {
    return (
      <Shell>
        <CenteredMessage
          icon={<AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-3" />}
          text={state === 'notFound' ? t('notFound') : t('error')}
        />
      </Shell>
    );
  }
  if (state === 'completed') {
    return (
      <Shell>
        <CenteredMessage
          icon={<CheckCircle className="w-10 h-10 text-green-500 mx-auto mb-3" />}
          text={t('alreadyCompleted')}
        />
      </Shell>
    );
  }
  if (state === 'success') {
    return (
      <Shell>
        <div className="bg-white rounded-card border border-gray-200 p-10 text-center">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h1 className="text-lg font-bold text-gray-900 mb-2">{t('success.title')}</h1>
          <p className="text-sm text-gray-500">{t('success.message')}</p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">{questionnaire.title}</h1>
        {questionnaire.description && (
          <p className="text-sm text-gray-500">{questionnaire.description}</p>
        )}
      </div>

      <div className="bg-white rounded-card border border-gray-200 p-5 mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-1.5">
          {t('form.nameLabel')}
        </label>
        <input
          type="text"
          value={respondentName}
          onChange={(e) => setRespondentName(e.target.value)}
          placeholder={t('form.namePlaceholder')}
          className="w-full px-3 py-2 border border-gray-200 rounded-input text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        />
      </div>

      <div className="space-y-4">
        {questionnaire.questions.map((q) => (
          <QuestionField
            key={q.id}
            question={q}
            value={answers[q.id]}
            error={errors[q.id]}
            onChange={(v) => setAnswer(q.id, v)}
            t={t}
          />
        ))}
      </div>

      {submitError && (
        <div className="flex items-center gap-2 mt-4 px-4 py-3 bg-red-50 border border-red-200 rounded-card text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {t('error')}
        </div>
      )}

      <button
        onClick={submit}
        disabled={submitting}
        className="mt-6 w-full flex items-center justify-center gap-2 px-5 py-3 bg-primary-600 text-white text-sm font-semibold rounded-button hover:bg-primary-700 transition-colors disabled:opacity-50"
      >
        <Send className="w-4 h-4" />
        {submitting ? t('form.submitting') : t('form.submit')}
      </button>
    </Shell>
  );
}

export async function getServerSideProps({ locale }) {
  return {
    props: {
      ...(await serverSideTranslations(locale, ['questionnaire'])),
    },
  };
}
```

- [ ] **Step 2: Full verification sweep**

```bash
cd frontend && npm run lint && npm run build
```
Expected: lint and build pass.

```bash
cd backend && python -m pytest tests/ -q && ruff check .
```
Expected: full suite green (DB tests skip without local PG).

```bash
grep -rin "welcome_message\|closing_message" backend/ frontend/ --include="*.py" --include="*.js" --include="*.json"
```
Expected: ZERO matches.

```bash
grep -rin "type == \"questionnaire\"\|type === 'questionnaire'\|'questionnaire'" backend/ frontend/pages/agents.js frontend/pages/index.js --include="*.py" --include="*.js"
```
Expected: no agent-type questionnaire references (the word "questionnaire" itself is fine in the new automations code, email service, locales, and the public page).

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/questionnaire
git commit -m "feat(ui): public questionnaire form page (classic single-submit form)"
```

- [ ] **Step 4: Manual smoke test (requires local stack)**

With `docker-compose up` (or local PG + `npm run dev` + uvicorn):
1. Log in → "Automatisations" appears in the sidebar.
2. Create a questionnaire with the 4 question types → it appears in the list with correct counts.
3. Invite your own email → check the email arrives (or check `email_sent` is false and the resend button appears if SMTP isn't configured locally).
4. Open the `/questionnaire/{token}` link in a private window → fill and submit the form → success screen; reopening shows "already completed".
5. In Réponses, expand the completed response, select it, export to a conversationnel companion → ask that companion a question about the answers.
