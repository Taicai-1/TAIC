"""
Neo4j Knowledge Graph client for TAIC Companion.
Provides person-centric context retrieval with Redis caching.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Singleton driver
_driver = None


def _get_driver(company_id: int = None):
    """Get Neo4j driver using org-level credentials only.
    No global env var fallback - Neo4j must be configured at the org level."""
    if not company_id:
        return None

    try:
        org_driver = _get_org_driver(company_id)
        if org_driver:
            return org_driver
    except Exception as e:
        logger.warning(f"Failed to get org Neo4j driver for company {company_id}: {e}")

    return None


# Cache org-level drivers keyed by company_id
_org_drivers = {}


def _get_org_driver(company_id: int):
    """Get a Neo4j driver using org-level credentials from the Company record."""
    if company_id in _org_drivers:
        return _org_drivers[company_id]

    try:
        from database import SessionLocal, Company

        db = SessionLocal()
        company = db.query(Company).filter(Company.id == company_id).first()
        db.close()

        if not company:
            logger.warning(f"Company {company_id} not found in database")
            return None
        if not company._neo4j_uri:
            logger.warning(f"Company {company_id} has no neo4j_uri stored (raw field is empty/null)")
            return None

        uri = company.org_neo4j_uri
        user = company.org_neo4j_user or "neo4j"
        password = company.org_neo4j_password

        logger.info(f"Neo4j credentials for company {company_id}: uri={'set' if uri else 'EMPTY'}, user={user}, password={'set' if password else 'EMPTY'}")

        if not uri or not password:
            logger.warning(f"Neo4j decrypted credentials incomplete for company {company_id}")
            return None

        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(uri, auth=(user, password))
        driver.verify_connectivity()
        _org_drivers[company_id] = driver
        logger.info(f"Org Neo4j driver initialized for company {company_id}")
        return driver
    except Exception as e:
        logger.error(f"Failed to init org Neo4j driver for company {company_id}: {type(e).__name__}: {e}", exc_info=True)
        return None


def _format_results(records: list) -> str:
    """Convert Neo4j records into readable French text for RAG context."""
    if not records:
        return ""

    lines = []
    for rec in records:
        source = rec.get("source_name", "?")
        source_role = rec.get("source_role", "")
        rel = rec.get("rel_type", "")
        target = rec.get("target_name", "?")
        target_label = rec.get("target_label", "")
        props = rec.get("rel_props", {})

        # Human-readable relation mapping
        rel_map = {
            "WORKS_AT": "travaille chez",
            "SUPERVISE": "supervise",
            "COLLABORE_AVEC": "collabore avec",
            "PARTICIPE_A": "participe a",
            "RESPONSABLE_DE": "est responsable de",
            "DEVELOPPE": "developpe",
            "TRAVAILLE_SUR": "travaille sur",
            "MAITRISE": "maitrise",
            "APPARTIENT_A": "appartient a",
            "POUR_CLIENT": "pour le client",
            "REQUIERT": "requiert",
            "GERE_PAR": "est gere par",
            "MENTIONNE": "mentionne",
        }
        rel_text = rel_map.get(rel, rel.lower().replace("_", " "))

        detail = ""
        if props:
            filtered = {k: v for k, v in props.items() if k not in ("company_id",)}
            if filtered:
                detail = " (" + ", ".join(f"{k}: {v}" for k, v in filtered.items()) + ")"

        role_info = f" ({source_role})" if source_role else ""
        type_info = f" [{target_label}]" if target_label else ""

        lines.append(f"- {source}{role_info} {rel_text} {target}{type_info}{detail}")

    return "\n".join(lines)


def get_person_context(company_id: int, person_name: str, depth: int = 1) -> str:
    """
    Query Neo4j for person-centric context.
    Depth 1: direct relations only.
    Depth 2: direct + second-degree relations.
    """
    driver = _get_driver(company_id=company_id)
    if driver is None:
        return ""

    try:
        with driver.session() as session:
            # Depth 1: direct relations
            result_d1 = session.run(
                """
                MATCH (p:Person {name: $name, company_id: $cid})-[r]-(connected)
                RETURN p.name AS source_name,
                       p.role AS source_role,
                       type(r) AS rel_type,
                       properties(r) AS rel_props,
                       connected.name AS target_name,
                       labels(connected)[0] AS target_label
            """,
                name=person_name,
                cid=company_id,
            )

            records_d1 = [dict(record) for record in result_d1]

            if not records_d1:
                logger.info(f"No Neo4j data for person '{person_name}' in company {company_id}")
                return ""

            # Also get person description
            desc_result = session.run(
                """
                MATCH (p:Person {name: $name, company_id: $cid})
                RETURN p.description AS description, p.role AS role, p.skills AS skills
            """,
                name=person_name,
                cid=company_id,
            )
            desc_record = desc_result.single()

            sections = []

            # Person header
            if desc_record:
                desc = desc_record.get("description", "")
                role = desc_record.get("role", "")
                skills = desc_record.get("skills", [])
                header = f"Personne cible : {person_name}"
                if role:
                    header += f" ({role})"
                if desc:
                    header += f"\nDescription : {desc}"
                if skills:
                    skill_list = skills if isinstance(skills, list) else [skills]
                    header += f"\nCompetences : {', '.join(skill_list)}"
                sections.append(header)

            # Direct relations
            sections.append("\nRelations directes :")
            sections.append(_format_results(records_d1))

            # Depth 2: second-degree
            if depth >= 2:
                result_d2 = session.run(
                    """
                    MATCH (p:Person {name: $name, company_id: $cid})-[r1]-(mid)-[r2]-(far)
                    WHERE far <> p AND NOT (p)-[]-(far)
                    RETURN mid.name AS source_name,
                           mid.role AS source_role,
                           type(r2) AS rel_type,
                           properties(r2) AS rel_props,
                           far.name AS target_name,
                           labels(far)[0] AS target_label
                    LIMIT 30
                """,
                    name=person_name,
                    cid=company_id,
                )

                records_d2 = [dict(record) for record in result_d2]
                if records_d2:
                    sections.append("\nRelations de second degre :")
                    sections.append(_format_results(records_d2))

            return "\n".join(sections)

    except Exception as e:
        logger.error(f"Neo4j query error for person '{person_name}': {e}")
        return ""


def get_person_context_cached(company_id: int, person_name: str, depth: int = 1) -> str:
    """
    Redis-cached wrapper around get_person_context.
    TTL: 10 minutes. Falls back to direct call if Redis unavailable.
    """
    cache_key = f"neo4j:{company_id}:{person_name}:{depth}"

    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            raise ConnectionError("Redis unavailable")

        cached = r.get(cache_key)
        if cached is not None:
            logger.info(f"Neo4j cache hit for {cache_key}")
            return cached

        context = get_person_context(company_id, person_name, depth)
        if context:
            r.setex(cache_key, 600, context)  # TTL 10 min
            logger.info(f"Neo4j cache set for {cache_key}")
        return context

    except Exception as e:
        logger.warning(f"Redis unavailable for Neo4j cache, direct query: {e}")
        return get_person_context(company_id, person_name, depth)


def get_persons_for_company(company_id: int) -> list:
    """List all Person nodes for a given company_id (for frontend dropdown)."""
    driver = _get_driver(company_id=company_id)
    if driver is None:
        return []

    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (p:Person {company_id: $cid})
                RETURN p.name AS name, p.role AS role
                ORDER BY p.name
            """,
                cid=company_id,
            )
            return [{"name": record["name"], "role": record["role"]} for record in result]
    except Exception as e:
        logger.error(f"Failed to list Neo4j persons for company {company_id}: {e}")
        return []


# Fixed list of searchable node labels (never interpolated from user input)
_SEARCHABLE_LABELS = ["Person", "Projet", "Client", "Competence", "Departement", "Source"]


def get_graph_context_by_keyword(
    company_id: int,
    keyword: str,
    depth: int = 1,
    node_types: list = None,
) -> tuple:
    """Search the graph by keyword (case-insensitive CONTAINS on nom, name, description, role).

    Returns (context_str, node_count, rel_count).
    Labels are iterated from _SEARCHABLE_LABELS, never from user input.
    """
    driver = _get_driver(company_id=company_id)
    if driver is None:
        return ("", 0, 0)

    allowed_labels = _SEARCHABLE_LABELS
    if node_types:
        # Filter to requested types, but only from the fixed list
        allowed_labels = [l for l in _SEARCHABLE_LABELS if l in node_types]
        if not allowed_labels:
            allowed_labels = _SEARCHABLE_LABELS

    try:
        with driver.session() as session:
            all_records = []
            matched_nodes = set()

            for label in allowed_labels:
                # Find nodes matching keyword
                result = session.run(
                    f"""
                    MATCH (n:{label} {{company_id: $cid}})
                    WHERE toLower(n.nom) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.name, '')) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.description, '')) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.role, '')) CONTAINS toLower($kw)
                    RETURN n, labels(n)[0] AS label, elementId(n) AS nid
                    LIMIT 20
                    """,
                    cid=company_id,
                    kw=keyword,
                )

                for record in result:
                    node = record["n"]
                    nid = record["nid"]
                    if nid in matched_nodes:
                        continue
                    matched_nodes.add(nid)

                # Get direct relations for matched nodes of this label
                rel_result = session.run(
                    f"""
                    MATCH (n:{label} {{company_id: $cid}})-[r]-(connected)
                    WHERE toLower(n.nom) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.name, '')) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.description, '')) CONTAINS toLower($kw)
                       OR toLower(COALESCE(n.role, '')) CONTAINS toLower($kw)
                    RETURN COALESCE(n.nom, n.name, '?') AS source_name,
                           n.role AS source_role,
                           type(r) AS rel_type,
                           properties(r) AS rel_props,
                           COALESCE(connected.nom, connected.name, '?') AS target_name,
                           labels(connected)[0] AS target_label
                    LIMIT 50
                    """,
                    cid=company_id,
                    kw=keyword,
                )
                all_records.extend([dict(r) for r in rel_result])

            if not matched_nodes and not all_records:
                return ("", 0, 0)

            # Optional depth 2
            if depth >= 2 and matched_nodes:
                for label in allowed_labels:
                    d2_result = session.run(
                        f"""
                        MATCH (n:{label} {{company_id: $cid}})-[r1]-(mid)-[r2]-(far)
                        WHERE (toLower(n.nom) CONTAINS toLower($kw)
                               OR toLower(COALESCE(n.name, '')) CONTAINS toLower($kw)
                               OR toLower(COALESCE(n.description, '')) CONTAINS toLower($kw)
                               OR toLower(COALESCE(n.role, '')) CONTAINS toLower($kw))
                              AND far <> n AND NOT (n)-[]-(far)
                        RETURN COALESCE(mid.nom, mid.name, '?') AS source_name,
                               mid.role AS source_role,
                               type(r2) AS rel_type,
                               properties(r2) AS rel_props,
                               COALESCE(far.nom, far.name, '?') AS target_name,
                               labels(far)[0] AS target_label
                        LIMIT 30
                        """,
                        cid=company_id,
                        kw=keyword,
                    )
                    all_records.extend([dict(r) for r in d2_result])

            # Dedup records by (source_name, rel_type, target_name)
            seen = set()
            unique_records = []
            for rec in all_records:
                key = (rec.get("source_name"), rec.get("rel_type"), rec.get("target_name"))
                if key not in seen:
                    seen.add(key)
                    unique_records.append(rec)

            context = _format_results(unique_records)
            if context:
                context = f"Contexte graphe pour '{keyword}' :\n{context}"

            return (context, len(matched_nodes), len(unique_records))

    except Exception as e:
        logger.error(f"Neo4j keyword search error for '{keyword}': {e}")
        return ("", 0, 0)


def get_graph_context_by_keyword_cached(
    company_id: int,
    keyword: str,
    depth: int = 1,
    node_types: list = None,
) -> str:
    """Redis-cached wrapper around get_graph_context_by_keyword.
    TTL: 10 minutes. Falls back to direct call if Redis unavailable.
    """
    types_key = ",".join(sorted(node_types)) if node_types else "all"
    cache_key = f"graph:{company_id}:{keyword}:{depth}:{types_key}"

    try:
        from redis_client import get_redis

        r = get_redis()
        if r is None:
            raise ConnectionError("Redis unavailable")

        cached = r.get(cache_key)
        if cached is not None:
            logger.info(f"Graph keyword cache hit for {cache_key}")
            return cached

        context, _, _ = get_graph_context_by_keyword(company_id, keyword, depth, node_types)
        if context:
            r.setex(cache_key, 600, context)  # TTL 10 min
            logger.info(f"Graph keyword cache set for {cache_key}")
        return context

    except Exception as e:
        logger.warning(f"Redis unavailable for graph keyword cache, direct query: {e}")
        context, _, _ = get_graph_context_by_keyword(company_id, keyword, depth, node_types)
        return context


def get_graph_stats(company_id: int) -> dict:
    """Count nodes by label and total relations for a company_id."""
    driver = _get_driver(company_id=company_id)
    if driver is None:
        return {"nodes": {}, "total_relations": 0}

    try:
        with driver.session() as session:
            node_counts = {}
            for label in _SEARCHABLE_LABELS:
                result = session.run(
                    f"MATCH (n:{label} {{company_id: $cid}}) RETURN count(n) AS cnt",
                    cid=company_id,
                )
                record = result.single()
                node_counts[label] = record["cnt"] if record else 0

            # Total relations
            rel_result = session.run(
                """
                MATCH (a {company_id: $cid})-[r]->(b {company_id: $cid})
                RETURN count(r) AS cnt
                """,
                cid=company_id,
            )
            rel_record = rel_result.single()
            total_rels = rel_record["cnt"] if rel_record else 0

            return {"nodes": node_counts, "total_relations": total_rels}

    except Exception as e:
        logger.error(f"Failed to get graph stats for company {company_id}: {e}")
        return {"nodes": {}, "total_relations": 0}
