"""Gemini の埋め込み（prereg_retrieval_seed.md §3.1）。

参照した公式文書: https://ai.google.dev/gemini-api/docs/embeddings （Last updated 2026-10-09 UTC）
- gemini-embedding-2 は task_type を受け付けないので、検索（非対称）の接頭辞をテキストに付ける。
  質問: "task: search result | query: {content}"、文書: "title: {title} | text: {content}"
- gemini-embedding-2 は 3072 以外の次元でも自動で正規化し直す。ここでは返ってきた L2 ノルムを記録し、
  念のため L2 正規化してから使う（単位長なら値は変わらない。コサイン距離の順位にも影響しない）。
- 複数の入力をそのまま並べると1本に集約されるので、各入力を types.Content に包む。
"""

import asyncio
import math
import time
from collections.abc import Sequence

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

__all__ = [
    "DOCUMENT_TEMPLATE",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_MODEL",
    "QUERY_TEMPLATE",
    "EmbeddingBudgetExhausted",
    "EmbeddedText",
    "Embedder",
    "format_document",
    "format_query",
    "l2_normalize",
    "vector_literal",
]

EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 1536  # Yuto の DDL の vector(1536)。暫定
QUERY_TEMPLATE = "task: search result | query: {content}"
DOCUMENT_TEMPLATE = "title: {title} | text: {content}"
NO_TITLE = "none"

RETRYABLE_STATUS = (429, 503)
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 30


class EmbeddingBudgetExhausted(RuntimeError):
    """埋め込みリクエストの予算に達した（次のリクエストは送っていない）。"""


class EmbeddedText(BaseModel):
    vector: list[float]  # L2 正規化後
    raw_norm: float  # API が返したベクトルの L2 ノルム


def format_query(text: str) -> str:
    return QUERY_TEMPLATE.format(content=text)


def format_document(title: str | None, body: str) -> str:
    return DOCUMENT_TEMPLATE.format(title=title or NO_TITLE, content=body)


def l2_normalize(values: Sequence[float]) -> tuple[list[float], float]:
    """(単位長にしたベクトル, 元のノルム)。ノルムが0なら止める（黙ってゼロ除算しない）。"""
    norm = math.sqrt(math.fsum(value * value for value in values))
    if norm == 0:
        raise ValueError("ノルムが0のベクトルは正規化できません")
    return [value / norm for value in values], norm


def vector_literal(values: Sequence[float]) -> str:
    """pgvector のテキスト表現（'[0.1,0.2,...]'）。asyncpg に vector 型のコーデックが無いので文字列で渡す。"""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


class Embedder:
    """埋め込み API の呼び出しを数え、予算と 429 / 503 のやり直しを扱う。

    requests は試行ごとに数える（429 で失敗した呼び出しも予算に入れる）。
    """

    def __init__(
        self,
        client: genai.Client,
        budget: int,
        model: str = EMBEDDING_MODEL,
        dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> None:
        self.client = client
        self.budget = budget
        self.model = model
        self.dimensions = dimensions
        self.requests = 0
        self.texts = 0
        self.retry_reasons: list[str] = []

    async def embed(self, texts: Sequence[str]) -> tuple[list[EmbeddedText], int]:
        """texts を1回の呼び出しで埋め込む。戻り値は (結果, 成功した試行の所要時間 ms)。"""
        if not texts:
            return [], 0
        contents = [types.Content(parts=[types.Part.from_text(text=text)]) for text in texts]
        config = types.EmbedContentConfig(output_dimensionality=self.dimensions)
        attempt = 0
        while True:
            attempt += 1
            if self.requests >= self.budget:
                raise EmbeddingBudgetExhausted(f"埋め込みリクエストの予算 {self.budget} 回に達しました")
            self.requests += 1
            started = time.perf_counter()
            try:
                result = await self.client.aio.models.embed_content(
                    model=self.model, contents=contents, config=config
                )
            except genai_errors.APIError as error:
                if error.code not in RETRYABLE_STATUS or attempt > MAX_RETRIES:
                    raise
                self.retry_reasons.append(f"HTTP {error.code}（試行 {attempt}）")
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)
            break
        self.texts += len(texts)
        embeddings = result.embeddings or []
        if len(embeddings) != len(texts):
            raise RuntimeError(f"埋め込みの本数が入力と違います: {len(embeddings)} / {len(texts)}")
        out = []
        for embedding in embeddings:
            values = embedding.values or []
            if len(values) != self.dimensions:
                raise RuntimeError(f"埋め込みの次元が {self.dimensions} ではありません: {len(values)}")
            vector, norm = l2_normalize(values)
            out.append(EmbeddedText(vector=vector, raw_norm=norm))
        return out, latency_ms
