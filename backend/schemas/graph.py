"""Pydantic schemas for GraphRAG ingestion and querying."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --- Enums ---


class CompetenceCategorie(str, Enum):
    tech = "tech"
    metier = "metier"
    outil = "outil"


class ProjetStatut(str, Enum):
    en_cours = "en_cours"
    termine = "termine"
    planifie = "planifie"
    suspendu = "suspendu"


class ImplicationLevel(str, Enum):
    lead = "lead"
    contributeur = "contributeur"
    consultant = "consultant"


class NiveauMaitrise(str, Enum):
    debutant = "debutant"
    intermediaire = "intermediaire"
    avance = "avance"
    expert = "expert"


class SourceType(str, Enum):
    document = "document"
    email = "email"
    url = "url"


# --- Extracted entity models ---


class ExtractedPerson(BaseModel):
    nom: str
    role: Optional[str] = None
    description: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    departement: Optional[str] = None


class ExtractedProjet(BaseModel):
    nom: str
    description: Optional[str] = None
    statut: Optional[ProjetStatut] = None
    date_debut: Optional[str] = None
    date_fin: Optional[str] = None


class ExtractedClient(BaseModel):
    nom: str
    secteur: Optional[str] = None
    description: Optional[str] = None


class ExtractedCompetence(BaseModel):
    nom: str
    categorie: Optional[CompetenceCategorie] = None


class ExtractedDepartement(BaseModel):
    nom: str
    description: Optional[str] = None


class ExtractedRelation(BaseModel):
    source_type: str  # e.g. "Person", "Projet"
    source_nom: str
    relation: str  # e.g. "TRAVAILLE_SUR", "MAITRISE"
    target_type: str
    target_nom: str
    properties: dict = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    personnes: List[ExtractedPerson] = Field(default_factory=list)
    projets: List[ExtractedProjet] = Field(default_factory=list)
    clients: List[ExtractedClient] = Field(default_factory=list)
    competences: List[ExtractedCompetence] = Field(default_factory=list)
    departements: List[ExtractedDepartement] = Field(default_factory=list)
    relations: List[ExtractedRelation] = Field(default_factory=list)


# --- API request/response models ---


class GraphIngestRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=100000)
    source_name: str = Field(..., min_length=1, max_length=500)
    source_type: SourceType = SourceType.document
    source_id: Optional[str] = None


class GraphIngestResponse(BaseModel):
    success: bool
    nodes_created: int = 0
    relations_created: int = 0
    extraction: Optional[ExtractionResult] = None
    message: str = ""


class GraphQueryRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=500)
    depth: int = Field(default=1, ge=1, le=2)
    node_types: Optional[List[str]] = None


class GraphQueryResponse(BaseModel):
    context: str = ""
    node_count: int = 0
    relation_count: int = 0
