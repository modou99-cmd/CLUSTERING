"""Tests du contrôle des citations du moteur RAG (sans Ollama)."""

from __future__ import annotations

from src.rag_engine import RAGEngine, SourceChunk

CHUNKS = [SourceChunk(source="SDRIF_E_Synthese_IleDeFrance.pdf", page=1, text="…", score=1.0)]


def test_invented_citation_is_removed() -> None:
    out = RAGEngine._enforce_citations(
        "Les documents indexés ne permettent pas de répondre à cette question. "
        "[Source : Pas de document fourni]", CHUNKS)
    assert "[Source" not in out


def test_valid_citation_kept_and_wrong_page_removed() -> None:
    out = RAGEngine._enforce_citations(
        "A [Source : SDRIF_E_Synthese_IleDeFrance.pdf - Page 1]. "
        "B [Source : SDRIF_E_Synthese_IleDeFrance.pdf - Page 9].", CHUNKS)
    assert "Page 1]" in out and "Page 9" not in out


def test_missing_citations_are_appended() -> None:
    out = RAGEngine._enforce_citations("Réponse sans citation.", CHUNKS)
    assert out.endswith("[Source : SDRIF_E_Synthese_IleDeFrance.pdf - Page 1]")
