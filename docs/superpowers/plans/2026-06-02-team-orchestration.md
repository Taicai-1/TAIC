# Team Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace simple semantic-routing teams with LLM-based hierarchical orchestration where the leader delegates to specialized sub-agents in parallel and synthesizes their responses.

**Architecture:** New `TeamMember` model replaces JSON field. New `orchestrator.py` module handles routing/execution/synthesis. Frontend gets multi-step team creation form and contribution display in chat.

**Tech Stack:** FastAPI, SQLAlchemy, asyncio, Mistral/OpenAI LLM APIs, Next.js/React, Tailwind CSS

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `backend/orchestrator.py` | Orchestration engine: routing LLM call, parallel agent execution, synthesis LLM call, auto-detection |
| `backend/tests/test_orchestrator.py` | Unit tests for orchestrator logic |
| `backend/tests/test_endpoints_teams.py` | Integration tests for team CRUD + orchestration endpoints |

### Modified files
| File | Changes |
|------|---------|
| `backend/database.py` | Add `TeamMember` model, `orchestration_prompt` on `Team`, `contributions_json` on `Message`, migration function |
| `backend/validation.py` | Add `TeamCreateV2Validated`, `TeamMemberSchema`, `SuggestSpecializationRequest` |
| `backend/routers/agents.py` | Rewrite team CRUD to use `TeamMember`, add `suggest-specialization` + `PUT members` + `PATCH member` |
| `backend/routers/ask.py` | Replace semantic matching with orchestrator calls in `/ask` and `/ask-stream` |
| `backend/tests/factories.py` | Add `TeamFactory`, `TeamMemberFactory` |
| `backend/tests/conftest.py` | Add `test_team`, `test_team_with_members` fixtures |
| `frontend/pages/teams.js` | Multi-step creation form with specializations |
| `frontend/pages/chat/team/[id].js` | Handle `routing`/`contribution` SSE events, show contributions |
| `frontend/components/TeamContributions.js` | New: accordion showing agent contributions |
| `frontend/components/TeamRoutingBanner.js` | New: animated banner during agent consultation |
| `frontend/lib/streamingFetch.js` | Handle new SSE event types (`routing`, `contribution`) |
| `frontend/public/locales/fr/teams.json` | New translation keys |
| `frontend/public/locales/en/teams.json` | New translation keys |

---

## Task 1: Add `TeamMember` model and DB migration

**Files:**
- Modify: `backend/database.py`

- [ ] **Step 1: Add TeamMember model to database.py**

Add after the `Team` class definition (around line 467):

```python
class TeamMember(Base):
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, default="member")  # "leader" or "member"
    specialization = Column(Text, nullable=True)
    auto_specialization = Column(Text, nullable=True)
    position = Column(Integer, nullable=False, default=0)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("team_id", "agent_id", name="uq_team_member"),)
```

- [ ] **Step 2: Add orchestration_prompt to Team model**

Add to the `Team` class:

```python
orchestration_prompt = Column(Text, nullable=True)
```

- [ ] **Step 3: Add contributions_json to Message model**

Add to the `Message` class:

```python
contributions_json = Column(Text, nullable=True)
```

- [ ] **Step 4: Add ensure_columns entries for new fields**

In the `ensure_columns` dict (around line 530+), add:

```python
"teams": [
    ("orchestration_prompt", "TEXT"),
],
"messages": [
    ("contributions_json", "TEXT"),
],
```

And add the `team_members` table to the `Base.metadata.create_all()` call (it will be auto-created since it's in `Base`).

- [ ] **Step 5: Add migrate_teams_to_members function**

Add at the bottom of database.py, near other migration functions:

```python
def migrate_teams_to_members(db: Session):
    """Migrate existing teams from JSON action_agent_ids to team_members table.
    Idempotent: skips teams that already have entries in team_members."""
    try:
        teams = db.query(Team).all()
        for team in teams:
            existing = db.query(TeamMember).filter(TeamMember.team_id == team.id).first()
            if existing:
                continue

            # Migrate leader
            if team.leader_agent_id:
                leader_member = TeamMember(
                    team_id=team.id,
                    agent_id=team.leader_agent_id,
                    role="leader",
                    position=0,
                    company_id=team.company_id,
                )
                db.add(leader_member)

            # Migrate action agents
            action_ids = []
            if team.action_agent_ids:
                try:
                    action_ids = json.loads(team.action_agent_ids) if isinstance(team.action_agent_ids, str) else team.action_agent_ids
                except (json.JSONDecodeError, TypeError):
                    action_ids = []

            for i, aid in enumerate(action_ids):
                member = TeamMember(
                    team_id=team.id,
                    agent_id=int(aid),
                    role="member",
                    position=i + 1,
                    company_id=team.company_id,
                )
                db.add(member)

        db.commit()
        logger.info(f"Migrated {len(teams)} teams to team_members table")
    except Exception as e:
        db.rollback()
        logger.error(f"Error migrating teams to members: {e}")
```

- [ ] **Step 6: Add TeamMember to imports and __all__ exports**

Add `TeamMember` to the imports in database.py's public interface. Also add it to the import in `routers/agents.py`:

```python
from database import (
    get_db, User, Agent, AgentShare, Team, TeamMember, Company,
)
```

- [ ] **Step 7: Call migration at startup**

In `main.py`, locate where other startup migrations are called (e.g., `migrate_existing_company_memberships`) and add:

```python
migrate_teams_to_members(db)
```

- [ ] **Step 8: Commit**

```bash
git add backend/database.py backend/main.py
git commit -m "feat(teams): add TeamMember model, orchestration_prompt, contributions_json, migration"
```

---

## Task 2: Add validation schemas

**Files:**
- Modify: `backend/validation.py`

- [ ] **Step 1: Add TeamMemberSchema**

Add after the existing `TeamCreateValidated` class:

```python
class TeamMemberSchema(BaseModel):
    """Schema for a team member in create/update requests."""
    agent_id: int = Field(..., gt=0)
    role: str = Field(..., pattern="^(leader|member)$")
    specialization: Optional[str] = Field(None, max_length=MAX_TEAM_CONTEXTE_LENGTH)

    @validator("specialization")
    def sanitize_specialization(cls, v):
        if not v:
            return v
        v = SCRIPT_PATTERN.sub("", v)
        return sanitize_text(v, MAX_TEAM_CONTEXTE_LENGTH)
```

- [ ] **Step 2: Add TeamCreateV2Validated**

```python
class TeamCreateV2Validated(BaseModel):
    """Team creation V2 with members array."""
    name: str = Field(..., min_length=1, max_length=MAX_TEAM_NAME_LENGTH)
    contexte: Optional[str] = Field(None, max_length=MAX_TEAM_CONTEXTE_LENGTH)
    orchestration_prompt: Optional[str] = Field(None, max_length=MAX_TEAM_CONTEXTE_LENGTH)
    members: list[TeamMemberSchema] = Field(...)

    @validator("name")
    def validate_name(cls, v):
        v = sanitize_text(v, MAX_TEAM_NAME_LENGTH)
        if not v:
            raise ValueError("Team name cannot be empty")
        return v

    @validator("contexte", "orchestration_prompt")
    def sanitize_text_field(cls, v):
        if not v:
            return v
        v = SCRIPT_PATTERN.sub("", v)
        return sanitize_text(v, MAX_TEAM_CONTEXTE_LENGTH)

    @validator("members")
    def validate_members(cls, v):
        if len(v) < 2:
            raise ValueError("Team must have at least a leader and one member")
        if len(v) > 51:
            raise ValueError("Too many members (max 51)")
        leaders = [m for m in v if m.role == "leader"]
        if len(leaders) != 1:
            raise ValueError("Team must have exactly one leader")
        members = [m for m in v if m.role == "member"]
        if len(members) < 1:
            raise ValueError("Team must have at least one member")
        agent_ids = [m.agent_id for m in v]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Duplicate agent IDs in members")
        return v
```

- [ ] **Step 3: Add SuggestSpecializationRequest**

```python
class SuggestSpecializationRequest(BaseModel):
    """Request to suggest specialization for an agent."""
    agent_id: int = Field(..., gt=0)
```

- [ ] **Step 4: Commit**

```bash
git add backend/validation.py
git commit -m "feat(teams): add TeamCreateV2Validated, TeamMemberSchema, SuggestSpecializationRequest"
```

---

## Task 3: Add test factories and fixtures

**Files:**
- Modify: `backend/tests/factories.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Add TeamFactory and TeamMemberFactory to factories.py**

```python
from database import (
    Base, User, Agent, Document, DocumentChunk, Conversation, Message,
    Company, CompanyMembership, AgentShare, AgentTemplate,
    AgentTemplateDocument, Team, TeamMember,
)

class TeamFactory(factory.Factory):
    class Meta:
        model = Team

    name = factory.Sequence(lambda n: f"team-{n}")
    contexte = "Equipe de test"

class TeamMemberFactory(factory.Factory):
    class Meta:
        model = TeamMember

    role = "member"
    specialization = None
    position = 0
```

- [ ] **Step 2: Add test_team and test_team_with_members fixtures to conftest.py**

```python
@pytest.fixture
def test_team(db_session, test_user):
    """Create a test team owned by test_user with a leader agent."""
    from tests.factories import AgentFactory, TeamFactory, TeamMemberFactory

    leader = AgentFactory.build(user_id=test_user.id, name="Leader Agent", company_id=getattr(test_user, 'company_id', None))
    db_session.add(leader)
    db_session.flush()

    team = TeamFactory.build(
        user_id=test_user.id,
        leader_agent_id=leader.id,
        action_agent_ids="[]",
        company_id=getattr(test_user, 'company_id', None),
    )
    db_session.add(team)
    db_session.flush()

    leader_member = TeamMemberFactory.build(
        team_id=team.id, agent_id=leader.id, role="leader", position=0,
        company_id=getattr(test_user, 'company_id', None),
    )
    db_session.add(leader_member)
    db_session.flush()

    return team


@pytest.fixture
def test_team_with_members(db_session, test_user):
    """Create a team with a leader + 2 member agents."""
    from tests.factories import AgentFactory, TeamFactory, TeamMemberFactory

    company_id = getattr(test_user, 'company_id', None)

    leader = AgentFactory.build(user_id=test_user.id, name="Leader", contexte="Coordinateur general", company_id=company_id)
    member1 = AgentFactory.build(user_id=test_user.id, name="Expert Finance", contexte="Expert en comptabilite", company_id=company_id)
    member2 = AgentFactory.build(user_id=test_user.id, name="Analyste Marche", contexte="Veille concurrentielle", company_id=company_id)
    for a in [leader, member1, member2]:
        db_session.add(a)
    db_session.flush()

    team = TeamFactory.build(
        user_id=test_user.id,
        leader_agent_id=leader.id,
        action_agent_ids=json.dumps([member1.id, member2.id]),
        company_id=company_id,
    )
    db_session.add(team)
    db_session.flush()

    members_data = [
        (leader, "leader", 0),
        (member1, "member", 1),
        (member2, "member", 2),
    ]
    for agent, role, pos in members_data:
        m = TeamMemberFactory.build(
            team_id=team.id, agent_id=agent.id, role=role, position=pos,
            specialization=agent.contexte, company_id=company_id,
        )
        db_session.add(m)
    db_session.flush()

    return {"team": team, "leader": leader, "members": [member1, member2]}
```

- [ ] **Step 3: Commit**

```bash
git add backend/tests/factories.py backend/tests/conftest.py
git commit -m "test(teams): add TeamFactory, TeamMemberFactory, team fixtures"
```

---

## Task 4: Build orchestrator engine

**Files:**
- Create: `backend/orchestrator.py`
- Create: `backend/tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests for orchestrator routing**

Create `backend/tests/test_orchestrator.py`:

```python
"""Tests for the team orchestration engine."""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from orchestrator import (
    select_agents_for_question,
    execute_agents_parallel,
    synthesize_contributions,
    suggest_specialization,
    orchestrate_team_question,
    DEFAULT_ROUTING_PROMPT,
)


class TestSelectAgentsForQuestion:
    """Test the LLM-based routing decision."""

    def test_returns_agent_ids_from_llm_response(self):
        mock_members = [
            {"agent_id": 5, "name": "Finance", "role": "member", "specialization": "comptabilite"},
            {"agent_id": 8, "name": "Marche", "role": "member", "specialization": "veille"},
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.return_value = {"agent_ids": [5], "reasoning": "Question financiere"}
            result = select_agents_for_question("Quel est le chiffre d'affaires?", mock_members, model_id="mistral:mistral-small-latest")
        assert result["agent_ids"] == [5]
        assert result["reasoning"] == "Question financiere"

    def test_returns_empty_when_no_agent_matches(self):
        mock_members = [
            {"agent_id": 5, "name": "Finance", "role": "member", "specialization": "comptabilite"},
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.return_value = {"agent_ids": [], "reasoning": "Hors perimetre"}
            result = select_agents_for_question("Quelle heure est-il?", mock_members, model_id="mistral:mistral-small-latest")
        assert result["agent_ids"] == []

    def test_fallback_on_malformed_json(self):
        mock_members = [
            {"agent_id": 5, "name": "Finance", "role": "member", "specialization": "comptabilite"},
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.side_effect = ValueError("Malformed JSON")
            result = select_agents_for_question("test", mock_members, model_id="mistral:mistral-small-latest")
        assert result["agent_ids"] == []
        assert "fallback" in result["reasoning"].lower() or "error" in result["reasoning"].lower()

    def test_caps_at_3_agents(self):
        mock_members = [
            {"agent_id": i, "name": f"Agent{i}", "role": "member", "specialization": f"spec{i}"}
            for i in range(10)
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.return_value = {"agent_ids": [1, 2, 3, 4, 5], "reasoning": "Many agents"}
            result = select_agents_for_question("Complex question", mock_members, model_id="mistral:mistral-small-latest")
        assert len(result["agent_ids"]) <= 3


class TestSuggestSpecialization:
    """Test auto-detection of agent specialization."""

    def test_returns_specialization_text(self):
        with patch("orchestrator._call_llm_for_specialization") as mock_llm:
            mock_llm.return_value = "Expert en analyse financiere et comptabilite"
            result = suggest_specialization(
                agent_name="Finance Bot",
                agent_contexte="Tu es un expert comptable",
                agent_biographie="Assistant financier",
                document_names=["bilan_2024.pdf", "compte_resultat.xlsx"],
            )
        assert "financiere" in result.lower() or "comptabilite" in result.lower()

    def test_handles_empty_context(self):
        with patch("orchestrator._call_llm_for_specialization") as mock_llm:
            mock_llm.return_value = "Assistant general"
            result = suggest_specialization(
                agent_name="Bot",
                agent_contexte="",
                agent_biographie="",
                document_names=[],
            )
        assert isinstance(result, str)
        assert len(result) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'orchestrator'`

- [ ] **Step 3: Write orchestrator.py implementation**

Create `backend/orchestrator.py`:

```python
"""Team orchestration engine.

Handles LLM-based routing, parallel agent execution, response synthesis,
and auto-detection of agent specializations.
"""

import asyncio
import json
import logging
import os
from typing import Any

from mistral_client import generate_text
from rag_engine import get_answer
from helpers.agent_helpers import resolve_model_id

logger = logging.getLogger(__name__)

DEFAULT_ROUTING_PROMPT = """Tu es le coordinateur d'une equipe d'agents specialises.
Analyse la question suivante et determine quel(s) agent(s) consulter.

Agents disponibles:
{agent_list}

Regles:
- Selectionne 1 a 3 agents maximum
- Si la question est transverse, selectionne plusieurs agents
- Si aucun agent n'est pertinent, retourne une liste vide (tu repondras toi-meme)

Retourne UNIQUEMENT un JSON: {{"agent_ids": [5, 8], "reasoning": "..."}}"""

DEFAULT_SYNTHESIS_PROMPT = """Tu es le coordinateur de l'equipe "{team_name}". {team_contexte}

Voici les contributions de tes agents specialises:

{contributions_text}

Synthetise ces contributions en une reponse claire et complete pour l'utilisateur.
Integre naturellement les informations sans repetition."""

SPECIALIZATION_PROMPT = """Analyse les informations suivantes sur un agent IA et genere une description courte (1-2 phrases) de sa specialite/expertise.

Nom: {name}
Contexte systeme: {contexte}
Biographie: {biographie}
Documents: {documents}

Retourne UNIQUEMENT la description de specialite, rien d'autre."""


def _call_llm_for_routing(prompt: str, model_id: str) -> dict:
    """Call LLM and parse JSON routing response."""
    raw = generate_text(prompt, model_name=model_id, temperature=0.1, max_tokens=500)
    # Extract JSON from response (may be wrapped in markdown code block)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    parsed = json.loads(text)
    if not isinstance(parsed.get("agent_ids"), list):
        raise ValueError("Missing or invalid agent_ids in routing response")
    return parsed


def _call_llm_for_specialization(prompt: str) -> str:
    """Call LLM to generate specialization description."""
    return generate_text(prompt, model_name="mistral-small-latest", temperature=0.3, max_tokens=200).strip()


def select_agents_for_question(
    question: str,
    members: list[dict],
    model_id: str,
    custom_routing_prompt: str | None = None,
) -> dict:
    """Use LLM to decide which agents should answer this question.

    Args:
        question: The user's question.
        members: List of dicts with agent_id, name, role, specialization.
        model_id: LLM model to use for routing.
        custom_routing_prompt: Optional override for the routing prompt template.

    Returns:
        Dict with "agent_ids" (list[int]) and "reasoning" (str).
    """
    agent_list = "\n".join(
        f'- Agent #{m["agent_id"]} "{m["name"]}" -- Specialite: {m.get("specialization") or "non definie"}'
        for m in members
        if m["role"] == "member"
    )

    template = custom_routing_prompt or DEFAULT_ROUTING_PROMPT
    prompt = template.format(agent_list=agent_list) + f"\n\nQuestion de l'utilisateur: {question}"

    try:
        result = _call_llm_for_routing(prompt, model_id)
        # Cap at 3 agents
        result["agent_ids"] = result["agent_ids"][:3]
        # Filter to valid member IDs only
        valid_ids = {m["agent_id"] for m in members if m["role"] == "member"}
        result["agent_ids"] = [aid for aid in result["agent_ids"] if aid in valid_ids]
        return result
    except Exception as e:
        logger.warning(f"Routing LLM failed, returning empty: {e}")
        return {"agent_ids": [], "reasoning": f"Fallback: routing error ({e})"}


def execute_agent(
    agent_id: int,
    question: str,
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    model_id: str,
    company_id: int | None,
    use_rag: bool = True,
    use_graph: bool = True,
) -> dict:
    """Execute a single agent's get_answer call. Returns contribution dict."""
    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {question}"
    try:
        result = get_answer(
            prompt, user_id, db,
            selected_doc_ids=selected_doc_ids,
            agent_id=agent_id,
            history=history,
            model_id=model_id,
            company_id=company_id,
            use_rag=use_rag,
            use_graph=use_graph,
        )
        answer = result["answer"] if isinstance(result, dict) else result
        sources = result.get("sources", []) if isinstance(result, dict) else []
        return {"agent_id": agent_id, "content": answer, "sources": sources, "status": "ok"}
    except Exception as e:
        logger.error(f"Agent {agent_id} execution failed: {e}")
        return {"agent_id": agent_id, "content": "", "sources": [], "status": "error", "error": str(e)}


def execute_agents_parallel(
    agent_configs: list[dict],
    question: str,
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    use_rag: bool = True,
    use_graph: bool = True,
) -> list[dict]:
    """Execute multiple agents sequentially (sync context, no async DB session).

    Each agent_config is: {"agent_id": int, "model_id": str, "company_id": int|None,
                           "name": str, "specialization": str}
    Returns list of contribution dicts.
    """
    contributions = []
    for config in agent_configs:
        result = execute_agent(
            agent_id=config["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=config["model_id"],
            company_id=config.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        result["agent_name"] = config["name"]
        result["specialization"] = config.get("specialization", "")
        contributions.append(result)
    return contributions


def synthesize_contributions(
    question: str,
    contributions: list[dict],
    team_name: str,
    team_contexte: str,
    leader_model_id: str,
) -> str:
    """Use leader LLM to synthesize agent contributions into a unified response."""
    successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
    if not successful:
        return ""

    contributions_text = "\n\n".join(
        f'[Agent "{c["agent_name"]}" -- {c.get("specialization", "general")}]:\n{c["content"]}'
        for c in successful
    )

    prompt = DEFAULT_SYNTHESIS_PROMPT.format(
        team_name=team_name,
        team_contexte=team_contexte or "",
        contributions_text=contributions_text,
    ) + f"\n\nQuestion originale: {question}"

    try:
        return generate_text(prompt, model_name=leader_model_id, temperature=0.3, max_tokens=4000).strip()
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        # Fallback: concatenate contributions
        return "\n\n---\n\n".join(
            f"**{c['agent_name']}**: {c['content']}" for c in successful
        )


def suggest_specialization(
    agent_name: str,
    agent_contexte: str,
    agent_biographie: str,
    document_names: list[str],
) -> str:
    """Auto-detect agent specialization from its context and documents."""
    prompt = SPECIALIZATION_PROMPT.format(
        name=agent_name,
        contexte=(agent_contexte or "")[:500],
        biographie=(agent_biographie or "")[:200],
        documents=", ".join(document_names[:10]) if document_names else "Aucun",
    )
    try:
        return _call_llm_for_specialization(prompt)
    except Exception as e:
        logger.error(f"Specialization suggestion failed: {e}")
        return ""


def orchestrate_team_question(
    question: str,
    team,
    members_with_agents: list[dict],
    user_id: int,
    db,
    selected_doc_ids: list[int],
    history: list,
    use_rag: bool = True,
    use_graph: bool = True,
) -> dict:
    """Full orchestration pipeline: route -> execute -> synthesize.

    Args:
        question: User's question.
        team: Team SQLAlchemy object.
        members_with_agents: List of dicts with keys:
            agent_id, name, role, specialization, model_id, company_id, agent (SQLAlchemy obj)
        user_id: Authenticated user ID.
        db: DB session.
        selected_doc_ids: Selected document IDs.
        history: Conversation history.
        use_rag: Whether to use RAG.
        use_graph: Whether to use graph.

    Returns:
        Dict with: answer, contributions, routing_reasoning, sources
    """
    leader_info = next((m for m in members_with_agents if m["role"] == "leader"), None)
    if not leader_info:
        raise ValueError("Team has no leader")

    leader_model_id = leader_info["model_id"]

    # Phase 1: Routing
    routing_result = select_agents_for_question(
        question=question,
        members=members_with_agents,
        model_id=leader_model_id,
        custom_routing_prompt=team.orchestration_prompt,
    )

    selected_ids = routing_result["agent_ids"]

    # If no agents selected, leader responds alone
    if not selected_ids:
        leader_result = execute_agent(
            agent_id=leader_info["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=leader_model_id,
            company_id=leader_info.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        return {
            "answer": leader_result["content"],
            "contributions": [],
            "routing_reasoning": routing_result["reasoning"],
            "sources": leader_result.get("sources", []),
        }

    # Phase 2: Parallel execution
    agent_configs = [
        m for m in members_with_agents if m["agent_id"] in selected_ids
    ]
    contributions = execute_agents_parallel(
        agent_configs=agent_configs,
        question=question,
        user_id=user_id,
        db=db,
        selected_doc_ids=selected_doc_ids,
        history=history,
        use_rag=use_rag,
        use_graph=use_graph,
    )

    # If all agents failed, leader responds alone
    successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
    if not successful:
        leader_result = execute_agent(
            agent_id=leader_info["agent_id"],
            question=question,
            user_id=user_id,
            db=db,
            selected_doc_ids=selected_doc_ids,
            history=history,
            model_id=leader_model_id,
            company_id=leader_info.get("company_id"),
            use_rag=use_rag,
            use_graph=use_graph,
        )
        return {
            "answer": leader_result["content"],
            "contributions": contributions,
            "routing_reasoning": routing_result["reasoning"],
            "sources": leader_result.get("sources", []),
        }

    # Phase 3: Synthesis
    answer = synthesize_contributions(
        question=question,
        contributions=contributions,
        team_name=team.name,
        team_contexte=team.contexte or "",
        leader_model_id=leader_model_id,
    )

    all_sources = []
    for c in successful:
        all_sources.extend(c.get("sources", []))

    return {
        "answer": answer,
        "contributions": [
            {
                "agent_id": c["agent_id"],
                "agent_name": c["agent_name"],
                "specialization": c.get("specialization", ""),
                "content": c["content"],
            }
            for c in contributions
        ],
        "routing_reasoning": routing_result["reasoning"],
        "sources": all_sources,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat(teams): add orchestrator engine with routing, execution, synthesis"
```

---

## Task 5: Rewrite team CRUD endpoints

**Files:**
- Modify: `backend/routers/agents.py`

- [ ] **Step 1: Write failing tests for new team endpoints**

Create `backend/tests/test_endpoints_teams.py`:

```python
"""Integration tests for team CRUD endpoints with orchestration."""

import json
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_create_team_v2(client, test_user, auth_cookies, db_session):
    """POST /teams with members array format."""
    from tests.factories import AgentFactory

    leader = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add_all([leader, member])
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Test Team V2",
        "contexte": "Team context",
        "members": [
            {"agent_id": leader.id, "role": "leader", "specialization": "Coordination"},
            {"agent_id": member.id, "role": "member", "specialization": "Expert finance"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 200
    data = res.json()["team"]
    assert data["name"] == "Test Team V2"
    assert len(data["members"]) == 2
    assert any(m["role"] == "leader" for m in data["members"])


@pytest.mark.asyncio
async def test_create_team_legacy_format(client, test_user, auth_cookies, db_session):
    """POST /teams with old leader_agent_id format still works."""
    from tests.factories import AgentFactory

    leader = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add_all([leader, member])
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Legacy Team",
        "leader_agent_id": leader.id,
        "action_agent_ids": [member.id],
    }, cookies=auth_cookies)
    assert res.status_code == 200


@pytest.mark.asyncio
async def test_create_team_no_leader_fails(client, test_user, auth_cookies, db_session):
    """POST /teams without a leader should fail validation."""
    from tests.factories import AgentFactory

    member = AgentFactory.build(user_id=test_user.id, company_id=getattr(test_user, 'company_id', None))
    db_session.add(member)
    db_session.flush()

    res = await client.post("/teams", json={
        "name": "Bad Team",
        "members": [
            {"agent_id": member.id, "role": "member", "specialization": "test"},
        ]
    }, cookies=auth_cookies)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_list_teams_includes_members(client, test_user, auth_cookies, test_team_with_members):
    """GET /teams returns members array."""
    res = await client.get("/teams", cookies=auth_cookies)
    assert res.status_code == 200
    teams = res.json()["teams"]
    assert len(teams) >= 1
    team = next(t for t in teams if t["id"] == test_team_with_members["team"].id)
    assert "members" in team
    assert len(team["members"]) == 3


@pytest.mark.asyncio
async def test_get_team_includes_members(client, test_user, auth_cookies, test_team_with_members):
    """GET /teams/{id} returns members."""
    team_id = test_team_with_members["team"].id
    res = await client.get(f"/teams/{team_id}", cookies=auth_cookies)
    assert res.status_code == 200
    data = res.json()["team"]
    assert "members" in data
    assert len(data["members"]) == 3


@pytest.mark.asyncio
async def test_suggest_specialization(client, test_user, auth_cookies, test_agent):
    """POST /teams/suggest-specialization returns a specialization string."""
    with patch("orchestrator.suggest_specialization", return_value="Expert en tests unitaires"):
        res = await client.post("/teams/suggest-specialization", json={
            "agent_id": test_agent.id,
        }, cookies=auth_cookies)
    assert res.status_code == 200
    assert "specialization" in res.json()
    assert len(res.json()["specialization"]) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_endpoints_teams.py -v`
Expected: FAIL (endpoints don't support new format yet)

- [ ] **Step 3: Rewrite team endpoints in routers/agents.py**

Replace the three team endpoint functions (`list_teams`, `create_team`, `get_team`) and add new endpoints. The full replacement code for lines 336-492:

```python
@router.get("/teams")
async def list_teams(user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """List teams for the current user, including members."""
    try:
        teams = db.query(Team).filter(Team.user_id == int(user_id)).order_by(Team.created_at.desc()).all()
        team_ids = [t.id for t in teams]

        # Batch-load all members
        members_by_team = {}
        if team_ids:
            all_members = db.query(TeamMember).filter(TeamMember.team_id.in_(team_ids)).order_by(TeamMember.position).all()
            all_agent_ids = {m.agent_id for m in all_members}
            agent_lookup = {}
            if all_agent_ids:
                agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
                agent_lookup = {a.id: a for a in agents}

            for m in all_members:
                members_by_team.setdefault(m.team_id, []).append({
                    "agent_id": m.agent_id,
                    "role": m.role,
                    "name": agent_lookup[m.agent_id].name if m.agent_id in agent_lookup else None,
                    "specialization": m.specialization,
                    "auto_specialization": m.auto_specialization,
                    "position": m.position,
                })

        out = []
        for t in teams:
            t_members = members_by_team.get(t.id, [])
            leader = next((m for m in t_members if m["role"] == "leader"), None)
            action_members = [m for m in t_members if m["role"] == "member"]
            out.append({
                "id": t.id,
                "name": t.name,
                "contexte": t.contexte,
                "orchestration_prompt": t.orchestration_prompt,
                "members": t_members,
                # Legacy fields for backward compat
                "leader_agent_id": leader["agent_id"] if leader else t.leader_agent_id,
                "leader_name": leader["name"] if leader else None,
                "action_agent_ids": [m["agent_id"] for m in action_members],
                "action_agent_names": [m["name"] for m in action_members if m["name"]],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return {"teams": out}
    except Exception as e:
        logger.exception(f"Error listing teams: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teams")
async def create_team(
    payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Create a team. Supports V2 (members array) and legacy (leader_agent_id) formats."""
    try:
        # Detect format
        is_v2 = "members" in payload

        if is_v2:
            from validation import TeamCreateV2Validated
            validated = TeamCreateV2Validated(**payload)
            name = validated.name
            contexte = validated.contexte
            orchestration_prompt = validated.orchestration_prompt
            members_data = validated.members
        else:
            from validation import TeamCreateValidated
            validated = TeamCreateValidated(**payload)
            name = validated.name
            contexte = validated.contexte
            orchestration_prompt = None
            # Convert legacy to V2 member format
            from validation import TeamMemberSchema
            members_data = [TeamMemberSchema(agent_id=validated.leader_agent_id, role="leader")]
            for aid in validated.action_agent_ids:
                members_data.append(TeamMemberSchema(agent_id=aid, role="member"))

        # Validate all agents belong to user and are conversationnel
        uid = int(user_id)
        for m in members_data:
            a = db.query(Agent).filter(Agent.id == m.agent_id, Agent.user_id == uid).first()
            if not a or getattr(a, "type", "conversationnel") != "conversationnel":
                raise HTTPException(
                    status_code=400,
                    detail=f"Agent {m.agent_id} doit etre un agent conversationnel appartenant a vous"
                )

        caller_company_id = _get_caller_company_id(user_id, db)
        leader_data = next(m for m in members_data if m.role == "leader")

        team = Team(
            name=name,
            contexte=contexte,
            orchestration_prompt=orchestration_prompt,
            leader_agent_id=leader_data.agent_id,
            action_agent_ids=json.dumps([m.agent_id for m in members_data if m.role == "member"]),
            user_id=uid,
            company_id=caller_company_id,
        )
        db.add(team)
        db.flush()

        # Create TeamMember entries
        for i, m in enumerate(members_data):
            tm = TeamMember(
                team_id=team.id,
                agent_id=m.agent_id,
                role=m.role,
                specialization=m.specialization,
                position=i,
                company_id=caller_company_id,
            )
            db.add(tm)

        db.commit()
        db.refresh(team)

        # Build response
        all_agent_ids = [m.agent_id for m in members_data]
        agents = db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()
        agent_lookup = {a.id: a.name for a in agents}

        resp_members = []
        for i, m in enumerate(members_data):
            resp_members.append({
                "agent_id": m.agent_id,
                "role": m.role,
                "name": agent_lookup.get(m.agent_id),
                "specialization": m.specialization,
                "position": i,
            })

        leader = next(m for m in resp_members if m["role"] == "leader")
        action_members = [m for m in resp_members if m["role"] == "member"]

        return {
            "team": {
                "id": team.id,
                "name": team.name,
                "contexte": team.contexte,
                "orchestration_prompt": team.orchestration_prompt,
                "members": resp_members,
                # Legacy compat
                "leader_agent_id": leader["agent_id"],
                "leader_name": leader["name"],
                "member_agent_ids": [m["agent_id"] for m in action_members],
                "member_agent_names": [m["name"] for m in action_members],
                "created_at": team.created_at.isoformat() if team.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating team: {e}")
        if 'relation "teams"' in str(e) or "does not exist" in str(e):
            raise HTTPException(status_code=500, detail="teams table not found in database.")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/teams/{team_id}")
async def get_team(team_id: int, user_id: str = Depends(verify_token), db: Session = Depends(get_db)):
    """Get a single team with members."""
    try:
        t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Team not found")

        members = db.query(TeamMember).filter(TeamMember.team_id == t.id).order_by(TeamMember.position).all()
        agent_ids = {m.agent_id for m in members}
        agent_lookup = {}
        if agent_ids:
            agents = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
            agent_lookup = {a.id: a for a in agents}

        resp_members = []
        for m in members:
            a = agent_lookup.get(m.agent_id)
            resp_members.append({
                "agent_id": m.agent_id,
                "role": m.role,
                "name": a.name if a else None,
                "specialization": m.specialization,
                "auto_specialization": m.auto_specialization,
                "position": m.position,
            })

        leader = next((m for m in resp_members if m["role"] == "leader"), None)
        action_members = [m for m in resp_members if m["role"] == "member"]

        return {
            "team": {
                "id": t.id,
                "name": t.name,
                "contexte": t.contexte,
                "orchestration_prompt": t.orchestration_prompt,
                "members": resp_members,
                # Legacy compat
                "leader_agent_id": leader["agent_id"] if leader else t.leader_agent_id,
                "leader_name": leader["name"] if leader else None,
                "action_agent_ids": [m["agent_id"] for m in action_members],
                "action_agent_names": [m["name"] for m in action_members if m["name"]],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching team {team_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teams/suggest-specialization")
async def suggest_specialization_endpoint(
    payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Auto-detect specialization for an agent."""
    from validation import SuggestSpecializationRequest
    validated = SuggestSpecializationRequest(**payload)

    agent = db.query(Agent).filter(Agent.id == validated.agent_id, Agent.user_id == int(user_id)).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from database import Document
    docs = db.query(Document).filter(Document.agent_id == agent.id).limit(10).all()
    doc_names = [d.filename for d in docs if d.filename]

    from orchestrator import suggest_specialization
    spec = suggest_specialization(
        agent_name=agent.name,
        agent_contexte=agent.contexte or "",
        agent_biographie=agent.biographie or "",
        document_names=doc_names,
    )
    return {"specialization": spec}


@router.put("/teams/{team_id}/members")
async def update_team_members(
    team_id: int, payload: dict, user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Replace full team composition."""
    from validation import TeamMemberSchema

    t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")

    members_raw = payload.get("members", [])
    members_data = [TeamMemberSchema(**m) for m in members_raw]

    # Validate
    leaders = [m for m in members_data if m.role == "leader"]
    if len(leaders) != 1:
        raise HTTPException(status_code=400, detail="Must have exactly one leader")
    non_leaders = [m for m in members_data if m.role == "member"]
    if len(non_leaders) < 1:
        raise HTTPException(status_code=400, detail="Must have at least one member")

    uid = int(user_id)
    for m in members_data:
        a = db.query(Agent).filter(Agent.id == m.agent_id, Agent.user_id == uid).first()
        if not a or getattr(a, "type", "conversationnel") != "conversationnel":
            raise HTTPException(status_code=400, detail=f"Agent {m.agent_id} invalid")

    # Delete old members
    db.query(TeamMember).filter(TeamMember.team_id == team_id).delete()

    caller_company_id = _get_caller_company_id(user_id, db)
    for i, m in enumerate(members_data):
        tm = TeamMember(
            team_id=team_id,
            agent_id=m.agent_id,
            role=m.role,
            specialization=m.specialization,
            position=i,
            company_id=caller_company_id,
        )
        db.add(tm)

    # Update legacy fields on Team
    leader = next(m for m in members_data if m.role == "leader")
    t.leader_agent_id = leader.agent_id
    t.action_agent_ids = json.dumps([m.agent_id for m in members_data if m.role == "member"])

    db.commit()
    return {"status": "ok"}


@router.patch("/teams/{team_id}/members/{agent_id}")
async def patch_team_member(
    team_id: int, agent_id: int, payload: dict,
    user_id: str = Depends(verify_token), db: Session = Depends(get_db)
):
    """Update specialization or position of a team member."""
    t = db.query(Team).filter(Team.id == team_id, Team.user_id == int(user_id)).first()
    if not t:
        raise HTTPException(status_code=404, detail="Team not found")

    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id, TeamMember.agent_id == agent_id
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    if "specialization" in payload:
        member.specialization = payload["specialization"]
    if "position" in payload:
        member.position = payload["position"]

    db.commit()
    return {"status": "ok"}
```

Also add `TeamMember` to the imports at the top of `routers/agents.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_endpoints_teams.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/agents.py backend/tests/test_endpoints_teams.py
git commit -m "feat(teams): rewrite team CRUD with members, add suggest-specialization endpoint"
```

---

## Task 6: Integrate orchestrator into /ask and /ask-stream

**Files:**
- Modify: `backend/routers/ask.py`

- [ ] **Step 1: Replace team logic in POST /ask (lines 91-185)**

Replace the `elif request.team_id:` block in the `ask_question` function with:

```python
        elif request.team_id:
            from database import TeamMember
            from orchestrator import orchestrate_team_question
            from helpers.agent_helpers import resolve_model_id

            team = db.query(Team).filter(Team.id == request.team_id).first()
            if not team:
                raise HTTPException(status_code=404, detail="Team not found")
            if team.user_id != int(user_id):
                raise HTTPException(status_code=403, detail="Access denied to this team")

            # Load members with agent data
            members_db = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.position).all()
            agent_ids = [m.agent_id for m in members_db]
            agents_db = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
            agent_lookup = {a.id: a for a in agents_db}

            members_with_agents = []
            for m in members_db:
                a = agent_lookup.get(m.agent_id)
                if not a:
                    continue
                members_with_agents.append({
                    "agent_id": m.agent_id,
                    "name": a.name,
                    "role": m.role,
                    "specialization": m.specialization or m.auto_specialization or "",
                    "model_id": a.finetuned_model_id or resolve_model_id(a),
                    "company_id": a.company_id,
                    "agent": a,
                })

            result = orchestrate_team_question(
                question=request.question,
                team=team,
                members_with_agents=members_with_agents,
                user_id=int(user_id),
                db=db,
                selected_doc_ids=request.selected_documents,
                history=history,
                use_rag=request.use_rag,
                use_graph=request.use_graph,
            )

            answer = result["answer"]
            sources = result.get("sources", [])
            graph_data = None
            agent = agent_lookup.get(members_with_agents[0]["agent_id"]) if members_with_agents else None

            return {
                "answer": answer,
                "sources": sources,
                "graph_data": graph_data,
                "contributions": result.get("contributions", []),
                "routing_reasoning": result.get("routing_reasoning", ""),
            }
```

- [ ] **Step 2: Replace team logic in POST /ask-stream (lines 246-334)**

Replace the `elif request.team_id:` block in the `event_generator` with new orchestrated streaming. The routing + execution phases are buffered, then synthesis is streamed:

```python
            elif request.team_id:
                from database import TeamMember
                from orchestrator import (
                    select_agents_for_question,
                    execute_agents_parallel,
                    DEFAULT_SYNTHESIS_PROMPT,
                )
                from helpers.agent_helpers import resolve_model_id
                from mistral_client import generate_text_stream

                team = db.query(Team).filter(Team.id == request.team_id).first()
                if not team:
                    yield sse_event("error", {"message": "Team not found", "code": "not_found"})
                    return
                if team.user_id != int(user_id):
                    yield sse_event("error", {"message": "Access denied", "code": "forbidden"})
                    return

                members_db = db.query(TeamMember).filter(TeamMember.team_id == team.id).order_by(TeamMember.position).all()
                agent_ids = [m.agent_id for m in members_db]
                agents_db = db.query(Agent).filter(Agent.id.in_(agent_ids)).all()
                agent_lookup = {a.id: a for a in agents_db}

                members_with_agents = []
                for m in members_db:
                    a = agent_lookup.get(m.agent_id)
                    if not a:
                        continue
                    members_with_agents.append({
                        "agent_id": m.agent_id,
                        "name": a.name,
                        "role": m.role,
                        "specialization": m.specialization or m.auto_specialization or "",
                        "model_id": a.finetuned_model_id or resolve_model_id(a),
                        "company_id": a.company_id,
                    })

                leader_info = next((m for m in members_with_agents if m["role"] == "leader"), None)
                if not leader_info:
                    yield sse_event("error", {"message": "No leader in team", "code": "bad_config"})
                    return

                # Phase 1: Routing (buffered)
                routing_result = select_agents_for_question(
                    question=request.question,
                    members=members_with_agents,
                    model_id=leader_info["model_id"],
                    custom_routing_prompt=team.orchestration_prompt,
                )
                selected_ids = routing_result["agent_ids"]

                if not selected_ids:
                    # Leader responds alone, stream directly
                    model_id = leader_info["model_id"]
                    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {request.question}"
                    yield from get_answer_stream(
                        prompt, int(user_id), db,
                        selected_doc_ids=request.selected_documents,
                        agent_id=leader_info["agent_id"],
                        history=history,
                        model_id=model_id,
                        company_id=leader_info.get("company_id"),
                        use_rag=request.use_rag,
                        use_graph=request.use_graph,
                    )
                    return

                # Emit routing event
                routed_agents = [
                    {"id": m["agent_id"], "name": m["name"], "specialization": m.get("specialization", "")}
                    for m in members_with_agents if m["agent_id"] in selected_ids
                ]
                yield sse_event("routing", {"agents": routed_agents})

                # Phase 2: Execution (buffered)
                agent_configs = [m for m in members_with_agents if m["agent_id"] in selected_ids]
                contributions = execute_agents_parallel(
                    agent_configs=agent_configs,
                    question=request.question,
                    user_id=int(user_id),
                    db=db,
                    selected_doc_ids=request.selected_documents,
                    history=history,
                    use_rag=request.use_rag,
                    use_graph=request.use_graph,
                )

                # Emit contribution events
                for c in contributions:
                    yield sse_event("contribution", {
                        "agent_id": c["agent_id"],
                        "agent_name": c.get("agent_name", ""),
                        "specialization": c.get("specialization", ""),
                        "content": c["content"],
                        "status": c["status"],
                    })

                # Phase 3: Synthesis (streamed)
                successful = [c for c in contributions if c["status"] == "ok" and c["content"]]
                if not successful:
                    # All failed, leader responds alone
                    prompt = f"Sachant le contexte et la discussion en cours, reponds a cette question : {request.question}"
                    yield from get_answer_stream(
                        prompt, int(user_id), db,
                        selected_doc_ids=request.selected_documents,
                        agent_id=leader_info["agent_id"],
                        history=history,
                        model_id=leader_info["model_id"],
                        company_id=leader_info.get("company_id"),
                        use_rag=request.use_rag,
                        use_graph=request.use_graph,
                    )
                    return

                contributions_text = "\n\n".join(
                    f'[Agent "{c["agent_name"]}" -- {c.get("specialization", "")}]:\n{c["content"]}'
                    for c in successful
                )
                synthesis_prompt = DEFAULT_SYNTHESIS_PROMPT.format(
                    team_name=team.name,
                    team_contexte=team.contexte or "",
                    contributions_text=contributions_text,
                ) + f"\n\nQuestion originale: {request.question}"

                full_text = ""
                for chunk in generate_text_stream(synthesis_prompt, model_name=leader_info["model_id"], temperature=0.3, max_tokens=4000):
                    full_text += chunk
                    yield sse_event("token", {"t": chunk})

                yield sse_event("done", {
                    "full_text": full_text,
                    "contributions": [
                        {"agent_id": c["agent_id"], "agent_name": c.get("agent_name", ""), "specialization": c.get("specialization", ""), "content": c["content"]}
                        for c in contributions
                    ],
                })
```

- [ ] **Step 3: Run existing ask tests + new team tests**

Run: `cd backend && python -m pytest tests/test_endpoints_ask.py tests/test_endpoints_teams.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/routers/ask.py
git commit -m "feat(teams): integrate orchestrator into /ask and /ask-stream endpoints"
```

---

## Task 7: Update frontend translations

**Files:**
- Modify: `frontend/public/locales/fr/teams.json`
- Modify: `frontend/public/locales/en/teams.json`

- [ ] **Step 1: Update French translations**

Replace the full content of `fr/teams.json` with the existing keys plus new keys for orchestration:

Add the following new keys to the existing file (merge into current structure):

```json
{
  "form": {
    "step1Title": "Informations de base",
    "step2Title": "Composition de l'equipe",
    "step3Title": "Apercu et confirmation",
    "orchestrationPrompt": "Instructions de routage personnalisees (optionnel)",
    "leaderSpecialization": "Specialite du leader",
    "memberSpecialization": "Specialite",
    "addMember": "Ajouter un companion",
    "removeMember": "Retirer",
    "regenerateSpec": "Regenerer",
    "autoDetected": "Auto-detecte",
    "customized": "Personnalise",
    "nextStep": "Suivant",
    "previousStep": "Precedent",
    "preview": "Apercu de l'equipe",
    "selectAgent": "Selectionner un companion",
    "noAgentsAvailable": "Aucun companion disponible",
    "editTeam": "Modifier l'equipe"
  },
  "chat": {
    "consultingAgents": "Consultation en cours...",
    "agentConsulted": "Agent consulte",
    "agentUnavailable": "Indisponible",
    "contributions": "Contributions",
    "contribution": "Contribution",
    "synthesizing": "Synthese en cours...",
    "routingTo": "Consultation de"
  },
  "errors": {
    "suggestSpecialization": "Erreur lors de la suggestion de specialite",
    "updateMembers": "Erreur lors de la mise a jour des membres"
  },
  "success": {
    "teamUpdated": "Equipe mise a jour avec succes !",
    "membersUpdated": "Membres mis a jour"
  }
}
```

- [ ] **Step 2: Update English translations similarly**

Add matching keys to `en/teams.json`:

```json
{
  "form": {
    "step1Title": "Basic information",
    "step2Title": "Team composition",
    "step3Title": "Preview and confirmation",
    "orchestrationPrompt": "Custom routing instructions (optional)",
    "leaderSpecialization": "Leader specialization",
    "memberSpecialization": "Specialization",
    "addMember": "Add a companion",
    "removeMember": "Remove",
    "regenerateSpec": "Regenerate",
    "autoDetected": "Auto-detected",
    "customized": "Customized",
    "nextStep": "Next",
    "previousStep": "Previous",
    "preview": "Team preview",
    "selectAgent": "Select a companion",
    "noAgentsAvailable": "No companions available",
    "editTeam": "Edit team"
  },
  "chat": {
    "consultingAgents": "Consulting agents...",
    "agentConsulted": "Agent consulted",
    "agentUnavailable": "Unavailable",
    "contributions": "Contributions",
    "contribution": "Contribution",
    "synthesizing": "Synthesizing...",
    "routingTo": "Consulting"
  },
  "errors": {
    "suggestSpecialization": "Error suggesting specialization",
    "updateMembers": "Error updating members"
  },
  "success": {
    "teamUpdated": "Team updated successfully!",
    "membersUpdated": "Members updated"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/public/locales/fr/teams.json frontend/public/locales/en/teams.json
git commit -m "feat(teams): add orchestration translation keys for FR and EN"
```

---

## Task 8: Add streaming event handling to streamingFetch.js

**Files:**
- Modify: `frontend/lib/streamingFetch.js`

- [ ] **Step 1: Add routing and contribution event types**

In `streamingFetch.js`, in the event parsing loop (around line 106), extend the `if/else if` chain to handle new event types:

```javascript
        if (eventType === 'token') {
          onToken?.(data.t || '');
        } else if (eventType === 'done') {
          onDone?.(data);
        } else if (eventType === 'error') {
          onError?.(data);
        } else if (eventType === 'routing') {
          callbacks.onRouting?.(data);
        } else if (eventType === 'contribution') {
          callbacks.onContribution?.(data);
        }
```

Update the destructuring at the top to accept the new callbacks:

```javascript
  const { onToken, onDone, onError, onRouting, onContribution } = callbacks;
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/streamingFetch.js
git commit -m "feat(teams): handle routing and contribution SSE events in streamingFetch"
```

---

## Task 9: Create TeamRoutingBanner component

**Files:**
- Create: `frontend/components/TeamRoutingBanner.js`

- [ ] **Step 1: Create the component**

```jsx
import { useTranslation } from 'next-i18next';
import { Bot, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

/**
 * Animated banner showing which agents are being consulted.
 *
 * Props:
 *   agents: Array of { id, name, specialization, status }
 *     status: "pending" | "done" | "error"
 *   visible: boolean
 */
export default function TeamRoutingBanner({ agents, visible }) {
  const { t } = useTranslation('teams');

  if (!visible || !agents || agents.length === 0) return null;

  return (
    <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-lg p-4 mb-3 animate-in fade-in">
      <div className="flex items-center gap-2 mb-3 text-sm font-medium text-blue-700">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('chat.consultingAgents')}
      </div>
      <div className="flex flex-wrap gap-3">
        {agents.map((agent) => (
          <div
            key={agent.id}
            className={`flex items-center gap-2 px-3 py-2 rounded-md border text-sm transition-all ${
              agent.status === 'done'
                ? 'bg-green-50 border-green-200 text-green-700'
                : agent.status === 'error'
                ? 'bg-red-50 border-red-200 text-red-600'
                : 'bg-white border-blue-200 text-blue-600 animate-pulse'
            }`}
          >
            <Bot className="w-4 h-4" />
            <div>
              <div className="font-medium">{agent.name}</div>
              {agent.specialization && (
                <div className="text-xs opacity-70">{agent.specialization}</div>
              )}
            </div>
            {agent.status === 'done' && <CheckCircle className="w-4 h-4 text-green-500" />}
            {agent.status === 'error' && <AlertCircle className="w-4 h-4 text-red-500" />}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/TeamRoutingBanner.js
git commit -m "feat(teams): add TeamRoutingBanner component for agent consultation display"
```

---

## Task 10: Create TeamContributions component

**Files:**
- Create: `frontend/components/TeamContributions.js`

- [ ] **Step 1: Create the component**

```jsx
import { useState } from 'react';
import { useTranslation } from 'next-i18next';
import { ChevronDown, ChevronUp, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Collapsible accordion showing individual agent contributions.
 *
 * Props:
 *   contributions: Array of { agent_id, agent_name, specialization, content }
 */
export default function TeamContributions({ contributions }) {
  const { t } = useTranslation('teams');
  const [open, setOpen] = useState(false);

  if (!contributions || contributions.length === 0) return null;

  const label = contributions.length === 1
    ? t('chat.contribution')
    : t('chat.contributions');

  return (
    <div className="mt-3 border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2 bg-gray-50 hover:bg-gray-100 transition-colors text-sm font-medium text-gray-600"
      >
        <span>{label} ({contributions.length})</span>
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>
      {open && (
        <div className="divide-y divide-gray-100">
          {contributions.map((c) => (
            <div key={c.agent_id} className="px-4 py-3">
              <div className="flex items-center gap-2 mb-2">
                <Bot className="w-4 h-4 text-blue-500" />
                <span className="font-medium text-sm text-gray-800">{c.agent_name}</span>
                {c.specialization && (
                  <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
                    {c.specialization}
                  </span>
                )}
              </div>
              <div className="text-sm text-gray-700 prose prose-sm max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {c.content}
                </ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/TeamContributions.js
git commit -m "feat(teams): add TeamContributions accordion component"
```

---

## Task 11: Update team chat page to use orchestration

**Files:**
- Modify: `frontend/pages/chat/team/[id].js`

- [ ] **Step 1: Add state for routing and contributions**

At the top of the `TeamChatPage` component, add:

```javascript
import TeamRoutingBanner from '../../../components/TeamRoutingBanner';
import TeamContributions from '../../../components/TeamContributions';

// Inside component, add state:
const [routingAgents, setRoutingAgents] = useState([]);
const [showRoutingBanner, setShowRoutingBanner] = useState(false);
const [lastContributions, setLastContributions] = useState(null);
```

- [ ] **Step 2: Update streamAsk callbacks in sendMessage**

In the `sendMessage` function, update the `streamAsk` call (around line 197) to handle new events:

```javascript
        await streamAsk('/ask-stream', {
          question: userMessage,
          team_id: teamId,
          history: history
        }, {
          onRouting: (data) => {
            const agents = (data.agents || []).map(a => ({
              ...a, status: 'pending'
            }));
            setRoutingAgents(agents);
            setShowRoutingBanner(true);
          },
          onContribution: (data) => {
            setRoutingAgents(prev => prev.map(a =>
              a.id === data.agent_id
                ? { ...a, status: data.status === 'ok' ? 'done' : 'error' }
                : a
            ));
          },
          onToken: (text) => {
            // Hide routing banner once synthesis starts
            setShowRoutingBanner(false);
            tokenBufferRef.current += text;
            if (!flushRafRef.current) {
              flushRafRef.current = requestAnimationFrame(() => {
                flushRafRef.current = null;
                const buffered = tokenBufferRef.current;
                tokenBufferRef.current = '';
                iaAnswer += buffered;
                setMessages(prev => prev.map((m, i) =>
                  i === streamingMsgIdx.current ? { ...m, content: iaAnswer } : m
                ));
              });
            }
          },
          onDone: (data) => {
            setShowRoutingBanner(false);
            if (flushRafRef.current) {
              cancelAnimationFrame(flushRafRef.current);
              flushRafRef.current = null;
            }
            iaAnswer += tokenBufferRef.current;
            tokenBufferRef.current = '';
            iaAnswer = data.full_text || iaAnswer;
            const contribs = data.contributions || null;
            setLastContributions(contribs);
            setMessages(prev => prev.map((m, i) =>
              i === streamingMsgIdx.current
                ? { ...m, content: iaAnswer, streaming: false, contributions: contribs }
                : m
            ));
            streamSuccess = true;
          },
          onError: () => {}
        }, controller.signal);
```

- [ ] **Step 3: Add routing banner and contributions to message rendering**

In the JSX where messages are rendered, add:

Before the message list:
```jsx
{showRoutingBanner && (
  <TeamRoutingBanner agents={routingAgents} visible={showRoutingBanner} />
)}
```

After each agent message that has contributions:
```jsx
{msg.contributions && msg.contributions.length > 0 && (
  <TeamContributions contributions={msg.contributions} />
)}
```

- [ ] **Step 4: Save contributions_json on agent message**

When saving the agent message to the backend (around line 286), include contributions:

```javascript
      try {
        await api.post(`/conversations/${selectedConv}/messages`, {
          conversation_id: selectedConv,
          role: "agent",
          content: iaAnswer,
          contributions_json: lastContributions ? JSON.stringify(lastContributions) : null,
        });
        setLastContributions(null);
      } catch (e) {}
```

- [ ] **Step 5: Load contributions from message history**

When loading messages from the backend, parse `contributions_json`:

```javascript
  const selectConversation = async (convId) => {
    // ... existing code ...
    try {
      const res = await api.get(`/conversations/${convId}/messages`);
      const loadedMessages = res.data.map(m => ({
        ...m,
        contributions: m.contributions_json ? JSON.parse(m.contributions_json) : null,
      }));
      setMessages(loadedMessages);
    }
    // ...
  };
```

- [ ] **Step 6: Verify the page renders correctly**

Run: `cd frontend && npm run build`
Expected: Build succeeds without errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/pages/chat/team/[id].js
git commit -m "feat(teams): integrate orchestration UI in team chat page"
```

---

## Task 12: Update teams.js with multi-step creation form

**Files:**
- Modify: `frontend/pages/teams.js`

- [ ] **Step 1: Replace the team creation modal**

This is the largest frontend change. Replace the current creation modal with a multi-step form. The implementation should:

1. Add state for `step` (1, 2, 3), `teamMembers` array, and per-member specialization
2. Step 1: Name + contexte (same as current)
3. Step 2: Leader select + member cards with specialization fields + auto-detection
4. Step 3: Preview tree of the team

Key changes to the existing form state:

```javascript
// Replace current form state
const [step, setStep] = useState(1);
const [teamMembers, setTeamMembers] = useState([]); // [{agent_id, role, specialization, autoSpec, name}]

// Auto-detect specialization when adding an agent
const handleAddMember = async (agentId) => {
  const agent = agents.find(a => a.id === agentId);
  if (!agent) return;
  // Check not already added
  if (teamMembers.some(m => m.agent_id === agentId)) return;

  const newMember = {
    agent_id: agentId,
    role: 'member',
    specialization: '',
    autoSpec: '',
    name: agent.name,
    loading: true,
  };
  setTeamMembers(prev => [...prev, newMember]);

  // Auto-detect
  try {
    const res = await api.post('/teams/suggest-specialization', { agent_id: agentId });
    setTeamMembers(prev => prev.map(m =>
      m.agent_id === agentId
        ? { ...m, specialization: res.data.specialization, autoSpec: res.data.specialization, loading: false }
        : m
    ));
  } catch {
    setTeamMembers(prev => prev.map(m =>
      m.agent_id === agentId ? { ...m, loading: false } : m
    ));
  }
};

// Submit uses new V2 format
const handleCreateTeam = async () => {
  const payload = {
    name: teamName,
    contexte: teamContext,
    members: teamMembers.map((m, i) => ({
      agent_id: m.agent_id,
      role: m.role,
      specialization: m.specialization || null,
    })),
  };
  await api.post('/teams', payload);
};
```

Step 2 UI pattern for each member card:

```jsx
<div className="flex items-center gap-3 p-3 bg-white rounded-lg border">
  <div className="flex-1">
    <div className="font-medium text-sm">{member.name}</div>
    <input
      type="text"
      value={member.specialization}
      onChange={(e) => updateMemberSpec(member.agent_id, e.target.value)}
      placeholder={t('teams:form.memberSpecialization')}
      className="mt-1 w-full text-sm border rounded px-2 py-1"
    />
    <span className="text-xs text-gray-400 mt-1">
      {member.specialization === member.autoSpec && member.autoSpec
        ? t('teams:form.autoDetected')
        : member.specialization
          ? t('teams:form.customized')
          : ''}
    </span>
  </div>
  <button onClick={() => handleRegenerateSpec(member.agent_id)}>
    {/* Refresh icon */}
  </button>
  <button onClick={() => removeMember(member.agent_id)}>
    {/* X icon */}
  </button>
</div>
```

- [ ] **Step 2: Add edit team functionality**

Add an edit button on each team card that opens the same multi-step form pre-populated with the team's current data:

```javascript
const handleEditTeam = async (teamId) => {
  const res = await api.get(`/teams/${teamId}`);
  const team = res.data.team;
  setTeamName(team.name);
  setTeamContext(team.contexte || '');
  setTeamMembers(team.members.map(m => ({
    agent_id: m.agent_id,
    role: m.role,
    specialization: m.specialization || '',
    autoSpec: m.auto_specialization || '',
    name: m.name,
    loading: false,
  })));
  setEditingTeamId(teamId);
  setStep(1);
  setShowCreateModal(true);
};
```

- [ ] **Step 3: Verify frontend builds**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/pages/teams.js
git commit -m "feat(teams): multi-step creation form with specializations and edit support"
```

---

## Task 13: Final integration test and cleanup

- [ ] **Step 1: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Run frontend lint**

Run: `cd frontend && npm run lint`
Expected: No errors or only pre-existing warnings.

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(teams): integration cleanup and final adjustments"
```
