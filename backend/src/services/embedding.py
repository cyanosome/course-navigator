"""Embedding Service using Official Google GenAI SDK (Fail-Fast, No Mock Fallback).

Provides async embedding retrieval functions for search and agent components,
and integrates standalone CLI diagnostics.
"""

import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

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


def mask_key(key: str) -> str:
    """Safely mask API key showing only prefix and length."""
    if not key:
        return "<EMPTY>"
    if len(key) <= 8:
        return f"{key[:2]}*** (len={len(key)})"
    return f"{key[:6]}...{key[-4:]} (len={len(key)})"


def inspect_key_properties(key: str) -> Dict[str, Any]:
    """Diagnose basic structure of the key without leaking contents."""
    sanitized = sanitize_key(key)
    return {
        "raw_length": len(key),
        "sanitized_length": len(sanitized),
        "starts_with_aq": sanitized.startswith("AQ."),
        "starts_with_aiza": sanitized.startswith("AIza"),
        "is_ascii": sanitized.isascii(),
        "has_outer_quotes": len(key) != len(key.strip("'\"")),
        "has_internal_whitespace": any(c in sanitized for c in " \t\r\n"),
        "masked": mask_key(sanitized),
    }


def analyze_error_reason(error_text: str) -> List[str]:
    """Analyze error response and produce actionable suggestions."""
    suggestions = []
    text_lower = error_text.lower()

    if "access_token_type_unsupported" in text_lower or "401" in error_text:
        suggestions.append(
            "[原因 1] Google Cloud 側で「Generative Language API」が有効化されていない可能性があります。\n"
            "  -> 対策: Google Cloud Console > [API とサービス] > [有効な API とサービス] を開き、\n"
            "     「Generative Language API」を検索して「有効にする」をクリックしてください。"
        )
        suggestions.append(
            "[原因 2] API キーの制限（API Restrictions）で Generative Language API が除外されている可能性があります。\n"
            "  -> 対策: Google Cloud Console > [認証情報] で当該キーの「API の制限」を確認し、\n"
            "     「Generative Language API」を許可するか、「キーを制限しない」を選択してください。"
        )
        suggestions.append(
            "[原因 3] Google AI Studio の別プロジェクトでの新規キー再発行をお試しください。\n"
            "  -> 対策: https://aistudio.google.com/app/apikey から新しいプロジェクトを作成してキーを取得してください。"
        )
    elif "403" in error_text or "permission_denied" in text_lower:
        suggestions.append("アクセス権限エラー（403 PERMISSION_DENIED）です。プロジェクトの利用規約同意や課金設定状況をご確認ください。")
    elif "404" in error_text or "not_found" in text_lower:
        suggestions.append(f"モデルが見つかりません。モデル名 ({DEFAULT_EMBEDDING_MODEL}) をご確認ください。")
    elif "429" in error_text or "resource_exhausted" in text_lower:
        suggestions.append("レート制限超過（429 RESOURCE_EXHAUSTED）です。少し時間をおいてから再試行してください。")
    else:
        suggestions.append(f"エラー詳細: {error_text}\nネットワーク環境やプロキシ、APIキーの有効性を確認してください。")

    return suggestions


class EmbeddingService:
    """Async embedding generator strictly using official Google GenAI SDK (Fail-Fast)."""

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
        self.model = model.removeprefix("models/")
        self.dimension = dimension
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise GeminiApiUnavailableError(
                    "GEMINI_API_KEY が未設定です。環境変数を確認するか、"
                    "python -m src.services.embedding で疎通を確認してください。"
                )
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _get_embed_config(self) -> Any:
        """Create EmbedContentConfig enforcing output dimension."""
        if hasattr(types, "EmbedContentConfig"):
            return types.EmbedContentConfig(output_dimensionality=self.dimension)
        return {"output_dimensionality": self.dimension}

    async def get_embedding(self, text: str) -> List[float]:
        """Generate embedding vector for a single query text asynchronously."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        def _call_sdk() -> List[float]:
            res = self.client.models.embed_content(
                model=self.model,
                contents=text,
                config=self._get_embed_config(),
            )
            if not res.embeddings or not res.embeddings[0].values:
                raise GeminiApiUnavailableError("Empty embedding returned by GenAI SDK")
            values = res.embeddings[0].values
            if len(values) != self.dimension:
                raise GeminiApiUnavailableError(
                    f"Unexpected embedding dimension: expected {self.dimension}, got {len(values)}"
                )
            return values

        try:
            return await asyncio.to_thread(_call_sdk)
        except Exception as e:
            logger.error("Gemini Embedding API call failed: %s", e)
            raise GeminiApiUnavailableError(
                f"Gemini Embedding API ({self.model}) との通信に失敗しました: {e}"
            ) from e

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for multiple texts asynchronously."""
        if not texts:
            return []

        def _call_sdk() -> List[List[float]]:
            res = self.client.models.embed_content(
                model=self.model,
                contents=texts,
                config=self._get_embed_config(),
            )
            if not res.embeddings or len(res.embeddings) != len(texts):
                raise GeminiApiUnavailableError(
                    f"Expected {len(texts)} embeddings, received {len(res.embeddings) if res.embeddings else 0}"
                )
            results = []
            for emb in res.embeddings:
                if len(emb.values) != self.dimension:
                    raise GeminiApiUnavailableError(
                        f"Unexpected embedding dimension: expected {self.dimension}, got {len(emb.values)}"
                    )
                results.append(emb.values)
            return results

        try:
            return await asyncio.to_thread(_call_sdk)
        except Exception as e:
            logger.error("Gemini Batch Embedding API call failed: %s", e)
            raise GeminiApiUnavailableError(
                f"Gemini Batch Embedding API ({self.model}) との通信に失敗しました: {e}"
            ) from e


default_embedding_service = EmbeddingService()


async def get_embedding(text: str) -> List[float]:
    return await default_embedding_service.get_embedding(text)


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    return await default_embedding_service.get_embeddings(texts)


def run_diagnostics(raw_key: Optional[str], model: str = DEFAULT_EMBEDDING_MODEL) -> int:
    """Run full diagnostic suite via official Google GenAI SDK and print report."""
    print("=" * 70)
    print("  [Backend] Gemini API Diagnostic Tool (Official Google GenAI SDK)")
    print("=" * 70)

    target_key = sanitize_key(raw_key or os.getenv("GEMINI_API_KEY") or getattr(config, "GEMINI_API_KEY", ""))
    if not target_key:
        print("[!] API キーが指定されていません。")
        print("    --key 引数で直接渡すか、環境変数 GEMINI_API_KEY を設定してください。")
        print("=" * 70)
        return 1

    props = inspect_key_properties(raw_key or target_key)

    print("[*] キー形式チェック:")
    print(f"    - マスク表示:           {props['masked']}")
    print(f"    - 文字長:               {props['sanitized_length']} 文字")
    print(f"    - AQ. プレフィックス:   {'はい (新形式 Auth Key)' if props['starts_with_aq'] else 'いいえ'}")
    print(f"    - AIza プレフィックス:  {'はい (従来形式 Standard Key)' if props['starts_with_aiza'] else 'いいえ'}")
    print(f"    - ASCII 文字列:         {'はい' if props['is_ascii'] else 'いいえ (不正な非ASCII文字あり)'}")
    print(f"    - 外側のクォート混入:   {'あり (自動除去済み)' if props['has_outer_quotes'] else 'なし'}")

    print("\n[*] 公式 Google GenAI SDK による疎通テスト実行中...")
    try:
        service = EmbeddingService(api_key=target_key, model=model)
        dim = len(asyncio.run(service.get_embedding("健康・スポーツ科学実習")))
        print("\n[*] 診断結果一覧:")
        print(f"    - 公式 SDK - Embedding ({model}):")
        print(f"      [SUCCESS] 成功 (取得次元: {dim}次元)")
        print("\n" + "=" * 70)
        print("  【判定】 PERFECT: Gemini Embedding API が正常に動作しています！")
        print("=" * 70)
        return 0
    except Exception as e:
        error_msg = str(e)
        print("\n[*] 診断結果一覧:")
        print(f"    - 公式 SDK - Embedding ({model}):")
        print(f"      [FAILED] 失敗: {error_msg}")
        print("\n" + "=" * 70)
        print("  【判定】 FAILED: API 呼び出しが拒否されました。")
        print("\n【トラブルシューティング処方箋】")
        suggestions = analyze_error_reason(error_msg)
        for sug in suggestions:
            print(f"\n{sug}")
        print("\n" + "=" * 70)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini Embedding Diagnostic Tool for Backend (Official SDK)")
    parser.add_argument(
        "--key",
        "-k",
        type=str,
        default=None,
        help="Test a specific API key directly.",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Target embedding model (default: {DEFAULT_EMBEDDING_MODEL})",
    )
    args = parser.parse_args()

    exit_code = run_diagnostics(args.key, model=args.model)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
