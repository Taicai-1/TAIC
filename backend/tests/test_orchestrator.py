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
            result = select_agents_for_question(
                "Quel est le chiffre d'affaires?", mock_members, model_id="mistral:mistral-small-latest"
            )
        assert result["agent_ids"] == [5]
        assert result["reasoning"] == "Question financiere"

    def test_returns_empty_when_no_agent_matches(self):
        mock_members = [
            {"agent_id": 5, "name": "Finance", "role": "member", "specialization": "comptabilite"},
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.return_value = {"agent_ids": [], "reasoning": "Hors perimetre"}
            result = select_agents_for_question(
                "Quelle heure est-il?", mock_members, model_id="mistral:mistral-small-latest"
            )
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
            {"agent_id": i, "name": f"Agent{i}", "role": "member", "specialization": f"spec{i}"} for i in range(10)
        ]
        with patch("orchestrator._call_llm_for_routing") as mock_llm:
            mock_llm.return_value = {"agent_ids": [1, 2, 3, 4, 5], "reasoning": "Many agents"}
            result = select_agents_for_question(
                "Complex question", mock_members, model_id="mistral:mistral-small-latest"
            )
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
