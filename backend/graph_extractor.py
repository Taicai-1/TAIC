"""
Extract entities and relations from text using Mistral LLM.

Produces an ExtractionResult that can be ingested into Neo4j.
"""

import json
import logging
import re
from typing import Optional

from schemas.graph import (
    ExtractionResult,
    ExtractedPerson,
    ExtractedProjet,
    ExtractedClient,
    ExtractedCompetence,
    ExtractedDepartement,
    ExtractedRelation,
)

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """Tu es un extracteur d'entites et de relations pour un graphe de connaissances d'entreprise.

Analyse le texte fourni et extrais les entites et relations suivantes.

## Types d'entites

- **Person** : nom, role, description, skills (liste), departement
- **Projet** : nom, description, statut (en_cours/termine/planifie/suspendu), date_debut, date_fin
- **Client** : nom, secteur, description
- **Competence** : nom, categorie (tech/metier/outil)
- **Departement** : nom, description

## Types de relations autorisees

- Person -> Person : SUPERVISE, COLLABORE_AVEC
- Person -> Projet : TRAVAILLE_SUR (properties: role, implication parmi lead/contributeur/consultant)
- Person -> Competence : MAITRISE (properties: niveau parmi debutant/intermediaire/avance/expert)
- Person -> Departement : APPARTIENT_A
- Projet -> Client : POUR_CLIENT
- Projet -> Competence : REQUIERT
- Projet -> Departement : GERE_PAR

## Regles

1. Extrais UNIQUEMENT les entites et relations explicitement mentionnees dans le texte.
2. Ne deduis PAS de relations qui ne sont pas clairement indiquees.
3. Normalise les noms propres (majuscule initiale).
4. Pour les competences, determine la categorie (tech pour technologies, metier pour savoir-faire metier, outil pour logiciels/outils).
5. Si une information est absente, utilise null.

## Format de sortie (JSON strict)

{
  "personnes": [{"nom": "...", "role": "...", "description": "...", "skills": [...], "departement": "..."}],
  "projets": [{"nom": "...", "description": "...", "statut": "...", "date_debut": "...", "date_fin": "..."}],
  "clients": [{"nom": "...", "secteur": "...", "description": "..."}],
  "competences": [{"nom": "...", "categorie": "..."}],
  "departements": [{"nom": "...", "description": "..."}],
  "relations": [{"source_type": "...", "source_nom": "...", "relation": "...", "target_type": "...", "target_nom": "...", "properties": {...}}]
}

## Texte a analyser

"""

_MAX_CHUNK_CHARS = 6000
_OVERLAP_CHARS = 500


def extract_entities(
    text: str,
    model_name: str = "mistral-small-latest",
) -> ExtractionResult:
    """Extract entities and relations from text.

    For texts longer than _MAX_CHUNK_CHARS, splits into overlapping chunks,
    extracts from each, and merges with deduplication.
    """
    if not text or not text.strip():
        return ExtractionResult()

    text = text.strip()

    if len(text) <= _MAX_CHUNK_CHARS:
        return _extract_single(text, model_name)

    chunks = _split_text(text, _MAX_CHUNK_CHARS, _OVERLAP_CHARS)
    logger.info(f"Text split into {len(chunks)} chunks for extraction")

    result = ExtractionResult()
    for i, chunk in enumerate(chunks):
        logger.info(f"Extracting from chunk {i + 1}/{len(chunks)} ({len(chunk)} chars)")
        chunk_result = _extract_single(chunk, model_name)
        result = _merge_results(result, chunk_result)

    return result


def _extract_single(text: str, model_name: str = "mistral-small-latest") -> ExtractionResult:
    """Single extraction call to Mistral using the existing generate_text helper."""
    from mistral_client import generate_text

    prompt = _EXTRACTION_PROMPT + text + "\n\nReponds UNIQUEMENT avec du JSON valide."

    try:
        raw = generate_text(
            prompt=prompt,
            model_name=model_name,
            temperature=0.1,
            max_tokens=8000,
        )

        if not raw:
            logger.warning("Empty response from Mistral extraction")
            return ExtractionResult()

        logger.info(f"Mistral extraction raw response ({len(raw)} chars): {raw[:300]}")
        result = _parse_extraction(raw)
        total = (
            len(result.personnes)
            + len(result.projets)
            + len(result.clients)
            + len(result.competences)
            + len(result.departements)
        )
        logger.info(f"Extraction parsed: {total} entities, {len(result.relations)} relations")
        return result

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Mistral extraction failed: {e}", exc_info=True)
        raise RuntimeError(f"Extraction LLM echouee: {str(e)}")


def _parse_extraction(raw_json: str) -> ExtractionResult:
    """Parse raw JSON string into ExtractionResult, tolerant of LLM quirks."""
    try:
        # Strip markdown code fences if present
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        # Try to extract JSON object if surrounded by text
        if not cleaned.startswith("{"):
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(0)

        data = json.loads(cleaned)

        # Parse relations with tolerance for field name variations from LLM
        parsed_relations = []
        for r in data.get("relations", []):
            try:
                normalized = {
                    "source_type": r.get("source_type", r.get("type_source", "")),
                    "source_nom": r.get("source_nom", r.get("nom_source", r.get("source", ""))),
                    "relation": r.get("relation", r.get("type", r.get("rel_type", ""))),
                    "target_type": r.get("target_type", r.get("type_cible", r.get("cible_type", ""))),
                    "target_nom": r.get(
                        "target_nom", r.get("nom_cible", r.get("cible_nom", r.get("cible", r.get("target", ""))))
                    ),
                    "properties": r.get("properties", r.get("proprietes", {})),
                }
                if normalized["source_nom"] and normalized["target_nom"] and normalized["relation"]:
                    parsed_relations.append(ExtractedRelation(**normalized))
                else:
                    logger.warning(f"Skipping incomplete relation: {r}")
            except Exception as rel_err:
                logger.warning(f"Skipping unparseable relation: {r} — {rel_err}")

        return ExtractionResult(
            personnes=[ExtractedPerson(**p) for p in data.get("personnes", [])],
            projets=[ExtractedProjet(**p) for p in data.get("projets", [])],
            clients=[ExtractedClient(**c) for c in data.get("clients", [])],
            competences=[ExtractedCompetence(**c) for c in data.get("competences", [])],
            departements=[ExtractedDepartement(**d) for d in data.get("departements", [])],
            relations=parsed_relations,
        )
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.error(f"Failed to parse extraction JSON: {e}\nRaw: {raw_json[:1000]}")
        raise RuntimeError(f"JSON parsing echoue: {str(e)}. Debut de la reponse: {raw_json[:200]}")


def _split_text(text: str, max_chars: int, overlap: int) -> list:
    """Split text into chunks at sentence boundaries with overlap."""
    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to split at a sentence boundary (. ! ? followed by space or newline)
        search_region = text[end - 200 : end]
        last_sentence_end = -1
        for match in re.finditer(r"[.!?]\s", search_region):
            last_sentence_end = match.end()

        if last_sentence_end > 0:
            end = end - 200 + last_sentence_end

        chunks.append(text[start:end])
        start = end - overlap

    return chunks


def _merge_results(base: ExtractionResult, new: ExtractionResult) -> ExtractionResult:
    """Merge two ExtractionResults, deduplicating entities by nom (case-insensitive)."""

    def _dedup_by_nom(existing, additions):
        seen = {item.nom.lower() for item in existing}
        for item in additions:
            if item.nom.lower() not in seen:
                existing.append(item)
                seen.add(item.nom.lower())
        return existing

    base.personnes = _dedup_by_nom(list(base.personnes), new.personnes)
    base.projets = _dedup_by_nom(list(base.projets), new.projets)
    base.clients = _dedup_by_nom(list(base.clients), new.clients)
    base.competences = _dedup_by_nom(list(base.competences), new.competences)
    base.departements = _dedup_by_nom(list(base.departements), new.departements)

    # Dedup relations by (source_type, source_nom, relation, target_type, target_nom)
    existing_keys = {
        (r.source_type, r.source_nom.lower(), r.relation, r.target_type, r.target_nom.lower()) for r in base.relations
    }
    for r in new.relations:
        key = (r.source_type, r.source_nom.lower(), r.relation, r.target_type, r.target_nom.lower())
        if key not in existing_keys:
            base.relations.append(r)
            existing_keys.add(key)

    return base
