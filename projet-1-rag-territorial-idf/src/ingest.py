"""Pipeline d'ingestion : PDF → filtre RGPD → chunks (800/150) → embeddings Ollama → ChromaDB.

Usage :
    python -m src.ingest                 # indexe tous les PDF de data/docs/
    python -m src.ingest --reset         # vide la collection puis ré-indexe
    python -m src.ingest fichier.pdf     # indexe uniquement les fichiers cités

Chaque chunk conserve sa traçabilité (nom du fichier, numéro de page) afin que le
moteur RAG puisse citer ``[Source : fichier - Page X]``. La ré-indexation d'un
document remplace ses anciens chunks (idempotence).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .config import settings, setup_logging
from .ollama_client import OllamaClient, OllamaEmbeddingFunction, OllamaUnavailableError
from .rgpd_filter import RGPDFilter, get_filter
from .vector_store import get_client, get_collection

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]
_PAGINATION_RE = re.compile(r"^(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?$", re.IGNORECASE)


class FileReport(BaseModel):
    source: str
    pages: int = 0
    chunks: int = 0
    pii_masked: dict[str, int] = Field(default_factory=dict)
    status: str = "ok"
    error: str | None = None


class IngestReport(BaseModel):
    files: list[FileReport] = Field(default_factory=list)

    @property
    def total_chunks(self) -> int:
        return sum(f.chunks for f in self.files)

    @property
    def total_pii(self) -> int:
        return sum(sum(f.pii_masked.values()) for f in self.files)

    @property
    def ok(self) -> bool:
        return all(f.status == "ok" for f in self.files)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _normalize(text: str) -> str:
    """Nettoyage léger de l'extraction PDF (césures, espaces multiples)."""
    text = text.replace("­", "").replace("-\n", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    # Retire les pieds de page de pagination ("Page 3", "3 / 12") qui bruitent les extraits.
    return "\n".join(l for l in lines if l and not _PAGINATION_RE.match(l))


def load_pdf_pages(path: Path, rgpd: RGPDFilter) -> tuple[list[Document], dict[str, int]]:
    """Lit un PDF page par page et applique le filtre RGPD AVANT tout découpage."""
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, OSError) as exc:
        raise ValueError(f"PDF illisible : {exc}") from exc
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("PDF chiffré : déchiffrement impossible") from exc

    pages: list[Document] = []
    pii: dict[str, int] = {}
    for idx, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - une page corrompue ne bloque pas le document
            logger.warning("%s p.%d : extraction impossible (%s)", path.name, idx, exc)
            continue
        text = _normalize(raw)
        if not text.strip():
            continue
        filtered = rgpd.filter(text)
        for cat, n in filtered.counts.items():
            pii[cat] = pii.get(cat, 0) + n
        pages.append(Document(page_content=filtered.text,
                              metadata={"source": path.name, "page": idx}))
    if not pages:
        raise ValueError("aucun texte extractible (PDF scanné ? un OCR est nécessaire)")
    return pages, pii


def split_pages(pages: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        add_start_index=True,
    )
    chunks = splitter.split_documents(pages)
    for i, c in enumerate(chunks):
        c.metadata["chunk_index"] = i
    return chunks


def ingest_file(
    path: Path,
    embedder: OllamaEmbeddingFunction,
    rgpd: RGPDFilter,
) -> FileReport:
    report = FileReport(source=path.name)
    try:
        pages, pii = load_pdf_pages(path, rgpd)
        chunks = split_pages(pages)
        report.pages, report.pii_masked = len(pages), pii

        texts = [c.page_content for c in chunks]
        vectors = embedder(texts)  # peut lever OllamaUnavailableError

        doc_hash = _sha256(path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        ids, metas = [], []
        for c in chunks:
            key = f"{path.name}|{c.metadata['page']}|{c.metadata['chunk_index']}|{doc_hash}"
            ids.append(hashlib.sha256(key.encode()).hexdigest()[:32])
            metas.append({
                "source": path.name,
                "page": int(c.metadata["page"]),
                "chunk_index": int(c.metadata["chunk_index"]),
                "start_index": int(c.metadata.get("start_index", 0)),
                "doc_sha256": doc_hash,
                "ingested_at": now,
                "rgpd_filtered": True,
                "embedding_model": settings.embedding_model,
            })

        col = get_collection()
        col.delete(where={"source": path.name})  # remplace une version antérieure
        col.upsert(ids=ids, documents=texts, embeddings=vectors, metadatas=metas)
        report.chunks = len(chunks)
        logger.info("Indexé %s : %d pages, %d chunks, PII masquées %s",
                    path.name, report.pages, report.chunks, pii or "aucune")
    except OllamaUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - un fichier en échec n'arrête pas le lot
        report.status, report.error = "erreur", str(exc)
        logger.error("Échec d'indexation de %s : %s", path.name, exc)
    return report


def discover_pdfs(docs_dir: Path, only: Iterable[str] | None = None) -> list[Path]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(p for p in docs_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf")
    if only:
        wanted = {Path(o).name for o in only}
        pdfs = [p for p in pdfs if p.name in wanted]
    return pdfs


def reset_collection() -> None:
    try:
        get_client().delete_collection(settings.collection_name)
        logger.info("Collection '%s' supprimée.", settings.collection_name)
    except Exception:  # noqa: BLE001 - collection inexistante
        pass


def run_ingestion(
    only: Iterable[str] | None = None,
    reset: bool = False,
    progress: ProgressCallback | None = None,
) -> IngestReport:
    """Point d'entrée programmatique (utilisé par la CLI et par Streamlit).

    Lève ``OllamaUnavailableError`` si le service d'embeddings n'est pas prêt.
    """
    client = OllamaClient()
    health = client.health()
    if not health["server"]:
        raise OllamaUnavailableError(
            f"{health['error']} Démarrez-le avec : docker compose up -d"
        )
    if not health["embed"]:
        raise OllamaUnavailableError(
            f"Modèle '{settings.embedding_model}' absent. "
            f"Lancez : docker exec ollama ollama pull {settings.embedding_model}"
        )

    if reset:
        reset_collection()

    pdfs = discover_pdfs(settings.docs_dir, only)
    report = IngestReport()
    if not pdfs:
        logger.warning("Aucun PDF trouvé dans %s", settings.docs_dir)
        return report

    embedder = OllamaEmbeddingFunction(client)
    rgpd = get_filter("pseudonymize")
    for i, pdf in enumerate(pdfs):
        if progress:
            progress(f"Indexation de {pdf.name}…", i / len(pdfs))
        report.files.append(ingest_file(pdf, embedder, rgpd))
    if progress:
        progress("Indexation terminée", 1.0)
    logger.info("Ingestion terminée : %d fichier(s), %d chunks, %d PII masquées.",
                len(report.files), report.total_chunks, report.total_pii)
    return report


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Indexation RGPD-compatible du corpus territorial.")
    parser.add_argument("files", nargs="*", help="Noms de fichiers PDF de data/docs/ (défaut : tous)")
    parser.add_argument("--reset", action="store_true", help="Vider la collection avant indexation")
    parser.add_argument("--no-samples", action="store_true",
                        help="Ne pas générer les PDF de démonstration si data/docs/ est vide")
    args = parser.parse_args(argv)

    if not args.no_samples:
        from .create_sample_docs import create_sample_docs
        create_sample_docs()

    try:
        report = run_ingestion(only=args.files or None, reset=args.reset)
    except OllamaUnavailableError as exc:
        logger.error("%s", exc)
        return 2
    for f in report.files:
        status = "OK " if f.status == "ok" else "ERR"
        print(f"[{status}] {f.source:<45} pages={f.pages:<3} chunks={f.chunks:<4} "
              f"PII={f.pii_masked or '-'}{'  → ' + f.error if f.error else ''}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
