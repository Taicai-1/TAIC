"""Graph ingestion, querying, and stats endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import verify_token
from database import get_db, Company
from helpers.tenant import _get_caller_company_id
from permissions import require_role
from schemas.graph import (
    GraphIngestRequest,
    GraphIngestResponse,
    GraphQueryRequest,
    GraphQueryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_company_neo4j(company_id: int, db: Session) -> Company:
    """Verify the company exists and has Neo4j enabled + configured."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if not company.neo4j_enabled:
        raise HTTPException(status_code=400, detail="Neo4j is not enabled for this organization")
    if not company._neo4j_uri:
        raise HTTPException(status_code=400, detail="Neo4j is not configured for this organization")
    return company


@router.post("/api/graph/ingest", response_model=GraphIngestResponse)
async def graph_ingest(
    body: GraphIngestRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Extract entities from text via Mistral and ingest into Neo4j. Requires admin role."""
    membership = require_role(user_id, db, "admin")
    company_id = membership.company_id

    _get_company_neo4j(company_id, db)

    try:
        from graph_extractor import extract_entities
        from graph_ingest import ingest_to_neo4j, ensure_indexes

        # Ensure indexes exist
        ensure_indexes(company_id)

        # Extract entities
        extraction = extract_entities(body.text)

        total_entities = (
            len(extraction.personnes)
            + len(extraction.projets)
            + len(extraction.clients)
            + len(extraction.competences)
            + len(extraction.departements)
        )
        if total_entities == 0:
            return GraphIngestResponse(
                success=True,
                nodes_created=0,
                relations_created=0,
                extraction=extraction,
                message="Aucune entite extraite du texte fourni.",
            )

        # Ingest into Neo4j
        counts = ingest_to_neo4j(
            company_id=company_id,
            extraction=extraction,
            source_name=body.source_name,
            source_type=body.source_type.value,
            source_id=body.source_id,
        )

        # Invalidate graph Redis cache for this company
        try:
            from redis_client import get_redis

            r = get_redis()
            if r is not None:
                # Delete all graph cache keys for this company
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor, match=f"graph:{company_id}:*", count=100)
                    if keys:
                        r.delete(*keys)
                    if cursor == 0:
                        break
                logger.info(f"Graph cache invalidated for company {company_id}")
        except Exception as e:
            logger.warning(f"Failed to invalidate graph cache: {e}")

        return GraphIngestResponse(
            success=True,
            nodes_created=counts["nodes_created"],
            relations_created=counts["relations_created"],
            extraction=extraction,
            message=f"{total_entities} entites extraites, {counts['nodes_created']} noeuds crees, {counts['relations_created']} relations creees.",
        )

    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Graph ingest error: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ingestion: {str(e)}")


@router.post("/api/graph/query", response_model=GraphQueryResponse)
async def graph_query(
    body: GraphQueryRequest,
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Search the knowledge graph by keyword. Requires member role."""
    membership = require_role(user_id, db, "member")
    company_id = membership.company_id

    _get_company_neo4j(company_id, db)

    try:
        from neo4j_client import get_graph_context_by_keyword_cached, get_graph_context_by_keyword

        if body.depth == 1 and not body.node_types:
            context = get_graph_context_by_keyword_cached(company_id, body.keyword, body.depth)
            # Get counts separately (cached version only returns context string)
            _, node_count, rel_count = get_graph_context_by_keyword(
                company_id, body.keyword, body.depth, body.node_types
            )
        else:
            context, node_count, rel_count = get_graph_context_by_keyword(
                company_id, body.keyword, body.depth, body.node_types
            )

        return GraphQueryResponse(
            context=context,
            node_count=node_count,
            relation_count=rel_count,
        )

    except Exception as e:
        logger.error(f"Graph query error: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la requete: {str(e)}")


@router.get("/api/graph/stats")
async def graph_stats(
    user_id: int = Depends(verify_token),
    db: Session = Depends(get_db),
):
    """Get node/relation counts for the company graph. Requires member role."""
    membership = require_role(user_id, db, "member")
    company_id = membership.company_id

    _get_company_neo4j(company_id, db)

    try:
        from neo4j_client import get_graph_stats

        stats = get_graph_stats(company_id)
        return stats

    except Exception as e:
        logger.error(f"Graph stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la recuperation des stats: {str(e)}")
