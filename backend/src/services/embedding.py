"""Embedding Service using Google Gemini API (Fail-Fast, No Mock Fallback)."""

import asyncio
import logging
import os
from typing import List, Optional

import httpx

try:
    from google import genai
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    GENAI_AVAILABLE = False

from course_core import config

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSION = 768


class GeminiApiUnavailableError(RuntimeError):
    """Raised when Gemini Embedding API is unreachable or returns an error."""
    pass


def sanitize_key(key: Optional[str]) -> str:
    """Trim leading/trailing whitespaces, newlines, and single/double quotes."""
    if not key:
        return ""
    return key.strip().strip("'\"").strip()


def _clean_model_name(model: str) -> str:
    """Strip models/ prefix if present."""
    return model.removeprefix("models/")


class EmbeddingService:
    """Async embedding generator strictly using Gemini API (Fail-Fast)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
    ):
        if api_key is not None:
            raw_key = api_key
        else:
            raw_key = os.getenv("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", "")
        self.api_key = sanitize_key(raw_key)
        self.model = model
        self.dimension = dimension

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a single query text (SDK primary, REST fallback)."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        if not self.api_key:
            raise GeminiApiUnavailableError(
                "GEMINI_API_KEY が未設定です。環境変数を確認するか、"
                "python -m src.tools.verify_gemini で疎通を確認してください。"
            )

        last_error = "Unknown error"

        # 1. Try Google Official GenAI SDK first
        if GENAI_AVAILABLE and self.api_key:
            try:
                loop = asyncio.get_running_loop()
                raw_model = _clean_model_name(self.model)
                client = genai.Client(api_key=self.api_key)
                res = await loop.run_in_executor(
                    None,
                    lambda: client.models.embed_content(model=raw_model, contents=text),
                )
                if res.embeddings and len(res.embeddings[0].values) == self.dimension:
                    return res.embeddings[0].values
            except Exception as e:
                last_error = f"Official GenAI SDK failed: {e}"
                logger.warning("Official GenAI SDK embed failed (%s), falling back to REST.", e)

        # 2. Try REST with x-goog-api-key header
        clean_model = _clean_model_name(self.model)
        url = f"https://generativelanguage.googleapis.com/v1beta/{clean_model}:embedContent"
        payload = {
            "model": clean_model,
            "content": {"parts": [{"text": text}]},
            "taskType": "RETRIEVAL_QUERY",
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    embedding_data = data.get("embedding", {})
                    values = embedding_data.get("values", [])
                    if values and len(values) == self.dimension:
                        return values
                last_error = f"REST API error ({resp.status_code}): {resp.text[:200]}"
                logger.warning("Gemini Embedding API returned status %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            last_error = f"REST API call failed: {e}"
            logger.warning("Gemini Embedding REST call failed (%s)", e)

        # Fail-Fast: Never fabricate mock vectors!
        raise GeminiApiUnavailableError(
            f"Gemini Embedding API ({self.model}) との通信に失敗しました。詳細: {last_error}"
        )

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts (SDK primary, REST fallback)."""
        if not texts:
            return []

        if not self.api_key:
            raise GeminiApiUnavailableError(
                "GEMINI_API_KEY が未設定です。環境変数を確認するか、"
                "python -m src.tools.verify_gemini で疎通を確認してください。"
            )

        last_error = "Unknown error"

        # 1. Try Google Official GenAI SDK first
        if GENAI_AVAILABLE and self.api_key:
            try:
                loop = asyncio.get_running_loop()
                raw_model = _clean_model_name(self.model)
                client = genai.Client(api_key=self.api_key)
                res = await loop.run_in_executor(
                    None,
                    lambda: client.models.embed_content(model=raw_model, contents=texts),
                )
                if res.embeddings and len(res.embeddings) == len(texts):
                    return [emb.values for emb in res.embeddings]
            except Exception as e:
                last_error = f"Official GenAI SDK batch failed: {e}"
                logger.warning("Official GenAI SDK batch embed failed (%s), falling back to REST.", e)

        # 2. Try REST with x-goog-api-key header
        clean_model = _clean_model_name(self.model)
        url = f"https://generativelanguage.googleapis.com/v1beta/{clean_model}:batchEmbedContents"
        requests = [
            {
                "model": clean_model,
                "content": {"parts": [{"text": t}]},
                "taskType": "RETRIEVAL_DOCUMENT",
            }
            for t in texts
        ]
        payload = {"requests": requests}
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings and len(embeddings) == len(texts):
                        return [e["values"] for e in embeddings]
                last_error = f"REST Batch API error ({resp.status_code}): {resp.text[:200]}"
                logger.warning("Gemini Batch Embedding API returned status %s: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            last_error = f"REST Batch call failed: {e}"
            logger.warning("Gemini Batch Embedding API call failed (%s)", e)

        # Fail-Fast: Never fabricate mock vectors!
        raise GeminiApiUnavailableError(
            f"Gemini Batch Embedding API ({self.model}) との通信に失敗しました。詳細: {last_error}"
        )


default_embedding_service = EmbeddingService()


async def get_embedding(text: str) -> List[float]:
    return await default_embedding_service.get_embedding(text)


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    return await default_embedding_service.get_embeddings(texts)
