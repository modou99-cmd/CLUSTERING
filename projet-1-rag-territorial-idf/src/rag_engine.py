"""Moteur RAG souverain : recherche sémantique ChromaDB + génération Ollama (``mistral``).

Garanties :
    * la question de l'usager est pseudonymisée AVANT embedding et génération ;
    * le modèle ne répond qu'à partir des extraits retrouvés (prompt système strict) ;
    * chaque affirmation doit citer ``[Source : nom_du_fichier - Page X]`` ; si le
      modèle omet les citations, elles sont ajoutées automatiquement en fin de réponse ;
    * mode dégradé (fallback) : si Ollama n'est pas démarré ou si un modèle manque,
      le moteur bascule sur une recherche lexicale locale et restitue les extraits
      pertinents, sans jamais inventer de réponse.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field

from .config import settings
from .ollama_client import OllamaClient, OllamaEmbeddingFunction, OllamaUnavailableError
from .rgpd_filter import get_filter
from .vector_store import get_collection

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es l'assistant documentaire souverain des collectivités territoriales \
d'Île-de-France. Tu aides des agents publics à interpréter des documents réglementaires \
(SDRIF-E, PLUi, PCAET).

RÈGLES IMPÉRATIVES :
1. Réponds UNIQUEMENT à partir des EXTRAITS fournis. N'utilise aucune connaissance externe.
2. Après CHAQUE phrase ou affirmation, cite sa provenance au format exact :
   [Source : nom_du_fichier - Page X]
3. Si les extraits ne permettent pas de répondre, réponds exactement :
   "Les documents indexés ne permettent pas de répondre à cette question."
   puis suggère le type de document à consulter. N'invente jamais de chiffre, de date ou de règle.
4. Les jetons entre crochets ([NOM_xxxx], [EMAIL_xxxx], [ADRESSE_xxxx]...) sont des données \
pseudonymisées : ne tente jamais de les ré-identifier.
5. Réponds en français, de façon factuelle, structurée et concise (registre administratif). \
Signale les éventuelles divergences entre documents.
"""

USER_TEMPLATE = """EXTRAITS DOCUMENTAIRES :
{context}

QUESTION DE L'AGENT : {question}

Réponds en respectant strictement les règles, avec les citations [Source : fichier - Page X]."""

NO_ANSWER = "Les documents indexés ne permettent pas de répondre à cette question."
CITATION_RE = re.compile(r"\[Source\s*:\s*[^\]]+?-\s*Page\s*\d+\s*\]", re.IGNORECASE)
ANY_CITATION_RE = re.compile(r"\s*\[Source\s*:(?P<body>[^\]]*)\]", re.IGNORECASE)
CITATION_PARTS_RE = re.compile(r"^\s*(?P<src>.+?)\s*-\s*Page\s*(?P<page>\d+)\s*$", re.IGNORECASE)


class SourceChunk(BaseModel):
    source: str
    page: int
    text: str
    score: float = Field(description="Pertinence normalisée 0-1 (1 = très pertinent)")

    @property
    def citation(self) -> str:
        return f"[Source : {self.source} - Page {self.page}]"


class RAGAnswer(BaseModel):
    question: str
    filtered_question: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    mode: Literal["llm", "fallback_lexical", "fallback_extractive", "empty_index", "no_match"]
    pii_in_question: dict[str, int] = Field(default_factory=dict)
    warning: str | None = None


# ---------------------------------------------------------------------------
# Recherche lexicale de secours (BM25 simplifié, 100 % local)
# ---------------------------------------------------------------------------
_STOP = set(
    "le la les de des du un une et en à au aux pour par sur dans est sont que qui quoi quel "
    "quelle quels quelles ce ces cette il elle on nous vous ils ou où comment pourquoi avec "
    "pas plus ne se sa son ses leur leurs d l y a être avoir faire peut doit".split()
)


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9]{2,}", text) if t not in _STOP]


def _bm25(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q = _tokens(query)
    tokenized = [_tokens(d) for d in docs]
    n = len(docs)
    avgdl = (sum(len(t) for t in tokenized) / n) if n else 0.0
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    scores: list[float] = []
    for toks in tokenized:
        tf = Counter(toks)
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(toks) / (avgdl or 1)))
        scores.append(s)
    return scores


# ---------------------------------------------------------------------------
# Moteur
# ---------------------------------------------------------------------------
class RAGEngine:
    def __init__(self, client: OllamaClient | None = None) -> None:
        self.client = client or OllamaClient()
        self.embedder = OllamaEmbeddingFunction(self.client)
        self.rgpd = get_filter("pseudonymize")

    # -- recherche --------------------------------------------------------
    def semantic_search(self, query: str, k: int) -> list[SourceChunk]:
        col = get_collection()
        vector = self.embedder.embed_query(query)
        res = col.query(query_embeddings=[vector], n_results=min(k, max(col.count(), 1)),
                        include=["documents", "metadatas", "distances"])
        out: list[SourceChunk] = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            if dist > settings.max_distance:
                continue
            out.append(SourceChunk(source=str(meta.get("source", "?")), page=int(meta.get("page", 0)),
                                   text=doc, score=round(max(0.0, 1 - dist), 3)))
        return out

    def lexical_search(self, query: str, k: int) -> list[SourceChunk]:
        col = get_collection()
        data = col.get(include=["documents", "metadatas"])
        docs, metas = data["documents"] or [], data["metadatas"] or []
        if not docs:
            return []
        scores = _bm25(query, docs)
        top = max(scores) or 1.0
        ranked = sorted(zip(scores, docs, metas), key=lambda x: x[0], reverse=True)[:k]
        return [SourceChunk(source=str(m.get("source", "?")), page=int(m.get("page", 0)),
                            text=d, score=round(s / top, 3)) for s, d, m in ranked if s > 0]

    # -- génération -------------------------------------------------------
    @staticmethod
    def _context(chunks: list[SourceChunk]) -> str:
        return "\n\n".join(
            f"--- Extrait {i} | {c.citation} ---\n{c.text}" for i, c in enumerate(chunks, start=1)
        )

    @staticmethod
    def _drop_unverified_citations(answer: str, chunks: list[SourceChunk]) -> str:
        """Supprime toute citation qui ne correspond pas à un extrait réellement retrouvé."""
        allowed = {(c.source.lower(), c.page) for c in chunks}

        def check(m: re.Match[str]) -> str:
            parts = CITATION_PARTS_RE.match(m.group("body"))
            if parts and (parts["src"].lower(), int(parts["page"])) in allowed:
                return m.group(0)
            logger.warning("Citation non vérifiable retirée de la réponse du modèle.")
            return ""

        return ANY_CITATION_RE.sub(check, answer).strip()

    @classmethod
    def _enforce_citations(cls, answer: str, chunks: list[SourceChunk]) -> str:
        """Garantit que la réponse ne contient que des citations vérifiables."""
        answer = cls._drop_unverified_citations(answer, chunks)
        if NO_ANSWER.lower() in answer.lower() or CITATION_RE.search(answer):
            return answer
        cites = list(dict.fromkeys(c.citation for c in chunks))
        return f"{answer}\n\n_Sources mobilisées :_ " + " ".join(cites)

    @staticmethod
    def _extractive_answer(chunks: list[SourceChunk], reason: str) -> str:
        lines = [f"⚠️ **Mode dégradé** — {reason}",
                 "Aucune synthèse générée : voici les extraits les plus pertinents, cités verbatim.\n"]
        for c in chunks:
            flat = " ".join(c.text.split())
            excerpt = flat if len(flat) <= 450 else flat[:450].rsplit(" ", 1)[0] + "…"
            lines.append(f"> {excerpt}\n>\n> {c.citation}\n")
        return "\n".join(lines)

    def ask(self, question: str, k: int | None = None) -> RAGAnswer:
        k = k or settings.top_k
        question = (question or "").strip()
        filtered = self.rgpd.filter(question)
        q = filtered.text
        base = dict(question=question, filtered_question=q, pii_in_question=filtered.counts)

        try:
            if get_collection().count() == 0:
                return RAGAnswer(**base, mode="empty_index", answer=(
                    "L'index documentaire est vide. Indexez des documents (onglet "
                    "« Indexation » ou `python -m src.ingest`) avant d'interroger l'assistant."))
        except Exception as exc:  # noqa: BLE001
            logger.error("ChromaDB inaccessible : %s", exc)
            return RAGAnswer(**base, mode="empty_index", answer="Base vectorielle inaccessible.",
                             warning=str(exc))

        health = self.client.health()

        # 1) Recherche : sémantique si possible, sinon lexicale.
        warning: str | None = None
        if health["server"] and health["embed"]:
            try:
                chunks = self.semantic_search(q, k)
            except OllamaUnavailableError as exc:
                warning = str(exc)
                chunks = self.lexical_search(q, k)
                health["llm"] = False
        else:
            warning = health["error"] or f"Modèle '{settings.embedding_model}' non installé."
            chunks = self.lexical_search(q, k)

        if not chunks:
            return RAGAnswer(**base, mode="no_match", warning=warning, answer=(
                f"{NO_ANSWER} Aucun extrait suffisamment pertinent n'a été trouvé ; "
                "reformulez la question ou indexez le document de référence (SDRIF-E, PLUi, PCAET)."))

        # 2) Génération : LLM local si disponible, sinon restitution extractive.
        if not (health["server"] and health["llm"]):
            reason = warning or f"modèle '{settings.llm_model}' non installé dans Ollama."
            mode = "fallback_lexical" if warning else "fallback_extractive"
            return RAGAnswer(**base, mode=mode, sources=chunks, warning=reason,
                             answer=self._extractive_answer(chunks, f"Ollama indisponible ({reason})"))
        try:
            raw = self.client.chat(SYSTEM_PROMPT, USER_TEMPLATE.format(context=self._context(chunks),
                                                                        question=q))
        except OllamaUnavailableError as exc:
            logger.warning("Génération impossible, bascule extractive : %s", exc)
            return RAGAnswer(**base, mode="fallback_extractive", sources=chunks, warning=str(exc),
                             answer=self._extractive_answer(chunks, str(exc)))

        # Défense en profondeur : la sortie du modèle est elle aussi filtrée.
        answer = self.rgpd.filter(raw or NO_ANSWER).text
        return RAGAnswer(**base, mode="llm", sources=chunks, warning=warning,
                         answer=self._enforce_citations(answer, chunks))


def main() -> None:
    import sys

    from .config import setup_logging

    setup_logging()
    question = " ".join(sys.argv[1:]) or "Quels sont les objectifs ZAN en Île-de-France ?"
    res = RAGEngine().ask(question)
    print(f"Mode : {res.mode}\n\n{res.answer}\n")
    for s in res.sources:
        print(f"  - {s.citation} (score {s.score})")


if __name__ == "__main__":
    main()
