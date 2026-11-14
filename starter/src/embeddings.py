"""Real embedding provider: local Sentence Transformers (multilingual E5)."""
from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class E5Embedder:
    """intfloat/multilingual-e5-* expects "query: " / "passage: " prefixes.

    Vectors are L2-normalised so cosine distance in pgvector is meaningful.
    Any loading error is raised: there is no mock / random fallback.
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base",
                 batch_size: int = 32, device: str | None = None) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        if device is None:
            device = "mps" if torch.backends.mps.is_available() else "cpu"
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=device)
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dimensions = get_dim()
        self.max_seq_length = self._model.max_seq_length

    def count_tokens(self, texts: list[str], prefix: str = "passage: ") -> list[int]:
        tok = self._model.tokenizer
        return [len(tok(prefix + t, add_special_tokens=True)["input_ids"]) for t in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode([f"passage: {t}" for t in texts], batch_size=self.batch_size,
                                     normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        return self._model.encode(f"query: {question}", normalize_embeddings=True).tolist()
