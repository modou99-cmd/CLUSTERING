"""Accès à la base vectorielle ChromaDB persistante (``data/chroma_db/``)."""

from __future__ import annotations

import logging
from functools import lru_cache

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings as ChromaSettings

from .config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    # Télémétrie désactivée : aucune donnée ne sort du poste (souveraineté).
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
    )


def get_collection() -> Collection:
    """Collection en similarité cosinus ; les embeddings sont fournis explicitement."""
    return get_client().get_or_create_collection(
        name=settings.collection_name,
        metadata={
            "hnsw:space": "cosine",
            "description": "Corpus réglementaire territorial IDF (SDRIF-E, PLUi, PCAET) - pseudonymisé",
            "embedding_model": settings.embedding_model,
        },
    )


def collection_stats() -> dict[str, object]:
    """Nombre de chunks et liste des documents indexés."""
    try:
        col = get_collection()
        count = col.count()
        sources: dict[str, int] = {}
        if count:
            metas = col.get(include=["metadatas"])["metadatas"] or []
            for m in metas:
                src = str(m.get("source", "?"))
                sources[src] = sources.get(src, 0) + 1
        return {"chunks": count, "documents": dict(sorted(sources.items()))}
    except Exception as exc:  # noqa: BLE001 - affichage UI tolérant
        logger.error("Lecture des statistiques ChromaDB impossible : %s", exc)
        return {"chunks": 0, "documents": {}, "error": str(exc)}
