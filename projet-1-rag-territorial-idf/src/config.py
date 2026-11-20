"""Configuration centralisée du POC (surchargeable par variables d'environnement).

Aucune valeur ne pointe vers un service cloud : tout est local (Ollama + ChromaDB).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


class Settings(BaseModel):
    """Paramètres applicatifs typés et validés."""

    # --- Chemins ---------------------------------------------------------
    docs_dir: Path = Field(default=PROJECT_ROOT / "data" / "docs")
    chroma_dir: Path = Field(default=PROJECT_ROOT / "data" / "chroma_db")
    collection_name: str = "corpus_territorial_idf"

    # --- Ollama (hébergement local, souverain) ---------------------------
    ollama_host: str = "http://localhost:11434"
    llm_model: str = "mistral"
    embedding_model: str = "nomic-embed-text"
    request_timeout_s: float = 180.0
    llm_temperature: float = 0.1
    llm_num_ctx: int = 8192

    # --- Découpage & recherche ------------------------------------------
    chunk_size: int = 800
    chunk_overlap: int = 150
    top_k: int = 5
    # Distance cosinus maximale pour considérer un extrait pertinent (0 = identique).
    max_distance: float = 0.65
    embed_batch_size: int = 16

    # --- Gouvernance -----------------------------------------------------
    max_upload_mb: int = 50
    # Sel de pseudonymisation (HMAC). À définir hors dépôt en production.
    rgpd_salt: str = "change-me-poc-local-salt"

    log_level: str = "INFO"


def load_settings() -> Settings:
    """Construit la configuration à partir de l'environnement."""
    return Settings(
        docs_dir=Path(_env("RAG_DOCS_DIR", str(PROJECT_ROOT / "data" / "docs"))),
        chroma_dir=Path(_env("RAG_CHROMA_DIR", str(PROJECT_ROOT / "data" / "chroma_db"))),
        collection_name=_env("RAG_COLLECTION", "corpus_territorial_idf"),
        ollama_host=_env("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
        llm_model=_env("OLLAMA_LLM_MODEL", "mistral"),
        embedding_model=_env("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        request_timeout_s=float(_env("OLLAMA_TIMEOUT_S", "180")),
        top_k=int(_env("RAG_TOP_K", "5")),
        max_distance=float(_env("RAG_MAX_DISTANCE", "0.65")),
        max_upload_mb=int(_env("RAG_MAX_UPLOAD_MB", "50")),
        rgpd_salt=_env("RGPD_SALT", "change-me-poc-local-salt"),
        log_level=_env("LOG_LEVEL", "INFO").upper(),
    )


settings: Settings = load_settings()


def setup_logging(level: str | None = None) -> None:
    """Initialise un logging homogène (idempotent).

    Politique RGPD : les journaux ne doivent JAMAIS contenir de données personnelles
    en clair — seuls des compteurs et des identifiants techniques sont journalisés.
    """
    root = logging.getLogger()
    if getattr(root, "_rag_configured", False):
        return
    logging.basicConfig(
        level=getattr(logging, (level or settings.log_level), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Bibliothèques bavardes
    for noisy in ("chromadb", "httpx", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._rag_configured = True  # type: ignore[attr-defined]
