"""Client HTTP minimal pour l'API Ollama locale (embeddings + génération).

Aucune dépendance cloud : toutes les requêtes partent vers ``OLLAMA_HOST``
(par défaut http://localhost:11434, exposé par docker-compose sur 127.0.0.1).
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import requests
from chromadb import Documents, EmbeddingFunction, Embeddings

from .config import Settings, settings

logger = logging.getLogger(__name__)


class OllamaUnavailableError(RuntimeError):
    """Ollama n'est pas joignable ou le modèle requis n'est pas installé."""


class OllamaClient:
    """Encapsule les appels REST à Ollama avec gestion d'erreurs explicite."""

    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self.base_url = cfg.ollama_host.rstrip("/")
        self._session = requests.Session()

    # -- santé ------------------------------------------------------------
    def list_models(self) -> list[str]:
        try:
            r = self._session.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaUnavailableError(
                f"Ollama injoignable sur {self.base_url} ({exc.__class__.__name__})."
            ) from exc
        return [m.get("name", "") for m in r.json().get("models", [])]

    def has_model(self, model: str, available: Sequence[str] | None = None) -> bool:
        names = available if available is not None else self.list_models()
        return any(n == model or n.split(":")[0] == model.split(":")[0] for n in names)

    def health(self) -> dict[str, Any]:
        """État synthétique : serveur joignable, modèles présents."""
        try:
            models = self.list_models()
        except OllamaUnavailableError as exc:
            return {"server": False, "llm": False, "embed": False, "error": str(exc), "models": []}
        return {
            "server": True,
            "llm": self.has_model(self.cfg.llm_model, models),
            "embed": self.has_model(self.cfg.embedding_model, models),
            "error": None,
            "models": models,
        }

    # -- embeddings -------------------------------------------------------
    def embed(self, texts: Sequence[str], model: str | None = None) -> list[list[float]]:
        model = model or self.cfg.embedding_model
        if not texts:
            return []
        try:
            r = self._session.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": list(texts)},
                timeout=self.cfg.request_timeout_s,
            )
            if r.status_code == 404 and "model" not in r.text.lower():
                return self._embed_legacy(texts, model)  # anciennes versions d'Ollama
            if r.status_code == 404:
                raise OllamaUnavailableError(
                    f"Modèle d'embedding '{model}' absent. Lancez : ollama pull {model}"
                )
            r.raise_for_status()
            vectors = r.json().get("embeddings")
        except requests.RequestException as exc:
            raise OllamaUnavailableError(f"Échec embeddings Ollama : {exc}") from exc
        if not vectors or len(vectors) != len(texts):
            raise OllamaUnavailableError("Réponse d'embedding Ollama invalide.")
        return vectors

    def _embed_legacy(self, texts: Sequence[str], model: str) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            r = self._session.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": t},
                timeout=self.cfg.request_timeout_s,
            )
            r.raise_for_status()
            out.append(r.json()["embedding"])
        return out

    # -- génération -------------------------------------------------------
    def chat(self, system: str, user: str, model: str | None = None) -> str:
        model = model or self.cfg.llm_model
        payload = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "options": {
                "temperature": self.cfg.llm_temperature,
                "num_ctx": self.cfg.llm_num_ctx,
            },
        }
        try:
            r = self._session.post(
                f"{self.base_url}/api/chat", json=payload, timeout=self.cfg.request_timeout_s
            )
            if r.status_code == 404:
                raise OllamaUnavailableError(
                    f"Modèle '{model}' absent. Lancez : ollama pull {model}"
                )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaUnavailableError(f"Échec génération Ollama : {exc}") from exc
        return r.json().get("message", {}).get("content", "").strip()


class OllamaEmbeddingFunction(EmbeddingFunction[Documents]):
    """Fonction d'embedding ChromaDB adossée à Ollama (``nomic-embed-text``).

    ``nomic-embed-text`` attend des préfixes de tâche distincts pour les documents
    et les requêtes, ce qui améliore sensiblement la qualité de la recherche.
    """

    def __init__(self, client: OllamaClient | None = None, prefix: str = "search_document: "):
        self.client = client or OllamaClient()
        self.prefix = prefix

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 (signature Chroma)
        texts = [f"{self.prefix}{t}" for t in input]
        bs = self.client.cfg.embed_batch_size
        vectors: list[list[float]] = []
        for i in range(0, len(texts), bs):
            vectors.extend(self.client.embed(texts[i : i + bs]))
        return vectors  # type: ignore[return-value]

    def embed_query(self, text: str) -> list[float]:
        return self.client.embed([f"search_query: {text}"])[0]
