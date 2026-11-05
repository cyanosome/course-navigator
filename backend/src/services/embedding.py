"""Embedding Service with Gemini API integration and deterministic fallback."""

import hashlib
import logging
import math
import os
import random
from typing import List, Optional

import httpx

try:
    import numpy as np
except ImportError:
    np = None

from course_core import config

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "models/text-embedding-004"
DEFAULT_DIMENSION = 768


def generate_deterministic_mock_embedding(text: str, dimension: int = DEFAULT_DIMENSION) -> List[float]:
    """Generate a deterministic unit-norm pseudo-random vector based on text SHA-256 hash.

    Identical to ingestion fallback (ingestion/src/transformers/kansai/embedding_generator.py)
    when numpy is present.
    """
    h = hashlib.sha256(text.encode("utf-8")).digest()
    seed = int.from_bytes(h[:8], byteorder="big") % (2**32)
    if np is not None:
        rng = np.random.RandomState(seed)
        raw_vec = rng.randn(dimension).astype(np.float32)
        norm = np.linalg.norm(raw_vec)
        if norm > 0:
            normalized_vec = raw_vec / norm
        else:
            normalized_vec = raw_vec
        return [round(float(v), 6) for v in normalized_vec]

    rng = random.Random(seed)
    raw_vec = [rng.gauss(0, 1) for _ in range(dimension)]
    norm = math.sqrt(sum(v * v for v in raw_vec))
    if norm > 0:
        normalized_vec = [v / norm for v in raw_vec]
    else:
        normalized_vec = raw_vec
    return [round(float(v), 6) for v in normalized_vec]


class EmbeddingService:
    """Async embedding generator with deterministic fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
        force_mock: bool = False,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "")
        self.model = model
        self.dimension = dimension
        self.force_mock = force_mock

        if not self.api_key or self.api_key in ("gemini", "your_gemini_api_key_here", ""):
            self.force_mock = True

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a single query text."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        if self.force_mock:
            return generate_deterministic_mock_embedding(text, self.dimension)

        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model}:embedContent?key={self.api_key}"
        payload = {
            "model": self.model,
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_QUERY",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    embedding_data = data.get("embedding", {})
                    values = embedding_data.get("values", [])
                    if values and len(values) == self.dimension:
                        return values
                logger.warning(
                    "Gemini Embedding API returned status %s: %s. Falling back to deterministic mock.",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.warning("Gemini Embedding API call failed (%s). Falling back to deterministic mock.", e)

        return generate_deterministic_mock_embedding(text, self.dimension)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts."""
        if not texts:
            return []

        if self.force_mock:
            return [generate_deterministic_mock_embedding(t, self.dimension) for t in texts]

        url = f"https://generativelanguage.googleapis.com/v1beta/{self.model}:batchEmbedContents?key={self.api_key}"
        requests = [
            {
                "model": self.model,
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            }
            for t in texts
        ]
        payload = {"requests": requests}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and len(embeddings) == len(texts):
                        return [e["values"] for e in embeddings]
                logger.warning(
                    "Gemini Batch Embedding API returned status %s: %s. Falling back to deterministic mock.",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.warning("Gemini Batch Embedding API call failed (%s). Falling back to deterministic mock.", e)

        return [generate_deterministic_mock_embedding(t, self.dimension) for t in texts]


default_embedding_service = EmbeddingService()


async def get_embedding(text: str) -> List[float]:
    return await default_embedding_service.get_embedding(text)


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    return await default_embedding_service.get_embeddings(texts)
