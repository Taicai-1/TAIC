"""
Write extracted entities and relations into Neo4j using idempotent MERGE operations.

All Cypher queries use parameterized values ($nom, $cid, etc.) to prevent injection.
Node labels and relation types are interpolated only from a hardcoded whitelist.
"""

import logging
from typing import Dict

from schemas.graph import ExtractionResult

logger = logging.getLogger(__name__)

# Whitelist of valid (source_label, relation_type, target_label) triples
_VALID_RELATIONS = {
    ("Person", "SUPERVISE", "Person"),
    ("Person", "COLLABORE_AVEC", "Person"),
    ("Person", "TRAVAILLE_SUR", "Projet"),
    ("Person", "MAITRISE", "Competence"),
    ("Person", "APPARTIENT_A", "Departement"),
    ("Projet", "POUR_CLIENT", "Client"),
    ("Projet", "REQUIERT", "Competence"),
    ("Projet", "GERE_PAR", "Departement"),
}

# Valid node labels for Source MENTIONNE relationships
_NODE_LABELS = {"Person", "Projet", "Client", "Competence", "Departement", "Source"}

# Map from label to the MERGE query for that label
_MERGE_QUERIES = {
    "Person": """
        MERGE (n:Person {nom: $nom, company_id: $cid})
        ON CREATE SET n.name = $nom, n.role = $role, n.description = $description,
                      n.skills = $skills, n.departement = $departement
        ON MATCH SET n.name = $nom,
                     n.role = COALESCE($role, n.role),
                     n.description = COALESCE($description, n.description),
                     n.skills = CASE WHEN $skills IS NOT NULL AND size($skills) > 0 THEN $skills ELSE n.skills END,
                     n.departement = COALESCE($departement, n.departement)
    """,
    "Projet": """
        MERGE (n:Projet {nom: $nom, company_id: $cid})
        ON CREATE SET n.description = $description, n.statut = $statut,
                      n.date_debut = $date_debut, n.date_fin = $date_fin
        ON MATCH SET n.description = COALESCE($description, n.description),
                     n.statut = COALESCE($statut, n.statut),
                     n.date_debut = COALESCE($date_debut, n.date_debut),
                     n.date_fin = COALESCE($date_fin, n.date_fin)
    """,
    "Client": """
        MERGE (n:Client {nom: $nom, company_id: $cid})
        ON CREATE SET n.secteur = $secteur, n.description = $description
        ON MATCH SET n.secteur = COALESCE($secteur, n.secteur),
                     n.description = COALESCE($description, n.description)
    """,
    "Competence": """
        MERGE (n:Competence {nom: $nom, company_id: $cid})
        ON CREATE SET n.categorie = $categorie
        ON MATCH SET n.categorie = COALESCE($categorie, n.categorie)
    """,
    "Departement": """
        MERGE (n:Departement {nom: $nom, company_id: $cid})
        ON CREATE SET n.description = $description
        ON MATCH SET n.description = COALESCE($description, n.description)
    """,
}

# Map relation type to its allowed properties
_RELATION_PROPERTIES = {
    "TRAVAILLE_SUR": ["role", "implication"],
    "MAITRISE": ["niveau"],
}


def ensure_indexes(company_id: int) -> None:
    """Create composite indexes (nom, company_id) per label. Idempotent."""
    from neo4j_client import _get_driver

    driver = _get_driver(company_id=company_id)
    if driver is None:
        return

    try:
        with driver.session() as session:
            for label in _NODE_LABELS:
                session.run(
                    f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.nom, n.company_id)"
                )
            # Also index Person.name for backward compat with get_person_context
            session.run(
                "CREATE INDEX IF NOT EXISTS FOR (n:Person) ON (n.name, n.company_id)"
            )
        logger.info(f"Graph indexes ensured for company {company_id}")
    except Exception as e:
        logger.warning(f"Failed to create graph indexes for company {company_id}: {e}")


def ingest_to_neo4j(
    company_id: int,
    extraction: ExtractionResult,
    source_name: str,
    source_type: str,
    source_id: str | None = None,
) -> Dict[str, int]:
    """Ingest extracted entities into Neo4j. Returns {nodes_created, relations_created}."""
    from neo4j_client import _get_driver

    driver = _get_driver(company_id=company_id)
    if driver is None:
        raise RuntimeError(f"No Neo4j driver available for company {company_id}")

    nodes_created = 0
    relations_created = 0

    try:
        with driver.session() as session:
            # 1. Create Source node
            session.run(
                """
                MERGE (s:Source {nom: $nom, company_id: $cid})
                ON CREATE SET s.type = $type, s.source_id = $source_id
                ON MATCH SET s.type = COALESCE($type, s.type),
                             s.source_id = COALESCE($source_id, s.source_id)
                """,
                nom=source_name,
                cid=company_id,
                type=source_type,
                source_id=source_id,
            )
            nodes_created += 1

            # 2. Create entity nodes + Source-[:MENTIONNE]->entity
            # Persons
            for p in extraction.personnes:
                result = session.run(
                    _MERGE_QUERIES["Person"],
                    nom=p.nom,
                    cid=company_id,
                    role=p.role,
                    description=p.description,
                    skills=p.skills if p.skills else [],
                    departement=p.departement,
                )
                summary = result.consume()
                nodes_created += summary.counters.nodes_created
                # Link Source -> Person
                session.run(
                    """
                    MATCH (s:Source {nom: $source, company_id: $cid})
                    MATCH (n:Person {nom: $nom, company_id: $cid})
                    MERGE (s)-[:MENTIONNE]->(n)
                    """,
                    source=source_name, cid=company_id, nom=p.nom,
                )

            # Projets
            for p in extraction.projets:
                result = session.run(
                    _MERGE_QUERIES["Projet"],
                    nom=p.nom,
                    cid=company_id,
                    description=p.description,
                    statut=p.statut.value if p.statut else None,
                    date_debut=p.date_debut,
                    date_fin=p.date_fin,
                )
                summary = result.consume()
                nodes_created += summary.counters.nodes_created
                session.run(
                    """
                    MATCH (s:Source {nom: $source, company_id: $cid})
                    MATCH (n:Projet {nom: $nom, company_id: $cid})
                    MERGE (s)-[:MENTIONNE]->(n)
                    """,
                    source=source_name, cid=company_id, nom=p.nom,
                )

            # Clients
            for c in extraction.clients:
                result = session.run(
                    _MERGE_QUERIES["Client"],
                    nom=c.nom,
                    cid=company_id,
                    secteur=c.secteur,
                    description=c.description,
                )
                summary = result.consume()
                nodes_created += summary.counters.nodes_created
                session.run(
                    """
                    MATCH (s:Source {nom: $source, company_id: $cid})
                    MATCH (n:Client {nom: $nom, company_id: $cid})
                    MERGE (s)-[:MENTIONNE]->(n)
                    """,
                    source=source_name, cid=company_id, nom=c.nom,
                )

            # Competences
            for c in extraction.competences:
                result = session.run(
                    _MERGE_QUERIES["Competence"],
                    nom=c.nom,
                    cid=company_id,
                    categorie=c.categorie.value if c.categorie else None,
                )
                summary = result.consume()
                nodes_created += summary.counters.nodes_created
                session.run(
                    """
                    MATCH (s:Source {nom: $source, company_id: $cid})
                    MATCH (n:Competence {nom: $nom, company_id: $cid})
                    MERGE (s)-[:MENTIONNE]->(n)
                    """,
                    source=source_name, cid=company_id, nom=c.nom,
                )

            # Departements
            for d in extraction.departements:
                result = session.run(
                    _MERGE_QUERIES["Departement"],
                    nom=d.nom,
                    cid=company_id,
                    description=d.description,
                )
                summary = result.consume()
                nodes_created += summary.counters.nodes_created
                session.run(
                    """
                    MATCH (s:Source {nom: $source, company_id: $cid})
                    MATCH (n:Departement {nom: $nom, company_id: $cid})
                    MERGE (s)-[:MENTIONNE]->(n)
                    """,
                    source=source_name, cid=company_id, nom=d.nom,
                )

            # 3. Create inter-entity relations (validated against whitelist)
            for rel in extraction.relations:
                triple = (rel.source_type, rel.relation, rel.target_type)
                if triple not in _VALID_RELATIONS:
                    logger.warning(
                        f"Skipping invalid relation: {rel.source_type}-[{rel.relation}]->{rel.target_type}"
                    )
                    continue

                # Build property SET clause from whitelisted properties only
                allowed_props = _RELATION_PROPERTIES.get(rel.relation, [])
                prop_params = {}
                set_clause = ""
                if allowed_props and rel.properties:
                    prop_sets = []
                    for prop_name in allowed_props:
                        if prop_name in rel.properties and rel.properties[prop_name]:
                            param_key = f"rel_{prop_name}"
                            prop_params[param_key] = rel.properties[prop_name]
                            prop_sets.append(f"r.{prop_name} = ${param_key}")
                    if prop_sets:
                        set_clause = "ON CREATE SET " + ", ".join(prop_sets)

                # Use label/relation from the validated whitelist triple (not user input)
                src_label, rel_type, tgt_label = triple

                cypher = f"""
                    MATCH (a:{src_label} {{nom: $src_nom, company_id: $cid}})
                    MATCH (b:{tgt_label} {{nom: $tgt_nom, company_id: $cid}})
                    MERGE (a)-[r:{rel_type}]->(b)
                    {set_clause}
                """
                params = {
                    "src_nom": rel.source_nom,
                    "tgt_nom": rel.target_nom,
                    "cid": company_id,
                    **prop_params,
                }
                result = session.run(cypher, **params)
                summary = result.consume()
                relations_created += summary.counters.relationships_created

    except Exception as e:
        logger.error(f"Neo4j ingestion failed for company {company_id}: {e}")
        raise

    return {"nodes_created": nodes_created, "relations_created": relations_created}
