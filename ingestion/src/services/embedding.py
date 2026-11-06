"""Syllabus Embedding Service for Ingestion pipeline.

Strictly utilizes the official Google GenAI SDK (google-genai) for generating
course and query embeddings, and integrates CLI diagnostic capabilities.
"""

import argparse
import logging
import os
import sys
from typing import Any, Dict, List, Optional

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    APIError = Exception
    GENAI_AVAILABLE = False

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_DIMENSION = 768


class GeminiEmbeddingError(RuntimeError):
    """Raised when Gemini Embedding generation fails."""
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
    """Embedding service using the official Google GenAI SDK (Fail-Fast)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimension: int = DEFAULT_DIMENSION,
    ):
        if not GENAI_AVAILABLE:
            raise ImportError("google-genai SDK がインストールされていません。'uv sync' または 'pip install google-genai' を実行してください。")

        self.api_key = sanitize_key(api_key or os.getenv("GEMINI_API_KEY"))
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY が未設定です。.env に設定するか、"
                "python -m src.services.embedding でキーの健全性を確認してください。"
            )
        self.model = model.removeprefix("models/")
        self.dimension = dimension
        self.client = genai.Client(api_key=self.api_key)

    def _get_embed_config(self) -> Any:
        """Create EmbedContentConfig enforcing output dimension."""
        if types is not None and hasattr(types, "EmbedContentConfig"):
            return types.EmbedContentConfig(output_dimensionality=self.dimension)
        return {"output_dimensionality": self.dimension}

    def probe_connectivity(self, sample_text: str = "健康・スポーツ科学実習") -> None:
        """Probe Gemini API with 1 text to ensure connectivity before batch processing."""
        logger.info("Probing Gemini API connectivity (model=%s, dim=%d)...", self.model, self.dimension)
        try:
            vec = self.embed_text(sample_text)
            if len(vec) != self.dimension:
                raise GeminiEmbeddingError(
                    f"予期しない埋め込み次元数です: 期待値 {self.dimension}, 実際 {len(vec)}"
                )
            logger.info("Gemini API probe succeeded (%d dimension).", len(vec))
        except Exception as e:
            raise GeminiEmbeddingError(
                f"Gemini API への事前疎通テストに失敗しました。\n"
                f"理由: {e}\n"
                f"python -m src.services.embedding を実行して診断結果を確認してください。"
            ) from e

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single text."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        try:
            res = self.client.models.embed_content(
                model=self.model,
                contents=text,
                config=self._get_embed_config(),
            )
            if not res.embeddings or not res.embeddings[0].values:
                raise GeminiEmbeddingError("空の埋め込みレスポンスを受信しました。")
            values = res.embeddings[0].values
            if len(values) != self.dimension:
                raise GeminiEmbeddingError(
                    f"予期しない次元数です: 期待値 {self.dimension}, 実際 {len(values)}"
                )
            return values
        except Exception as e:
            raise GeminiEmbeddingError(f"Embedding 生成に失敗しました (model={self.model}): {e}") from e

    def embed_texts(self, texts: List[str], batch_size: int = 50) -> List[List[float]]:
        """Generate embeddings for multiple texts in batches."""
        if not texts:
            return []

        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                res = self.client.models.embed_content(
                    model=self.model,
                    contents=batch,
                    config=self._get_embed_config(),
                )
                if not res.embeddings or len(res.embeddings) != len(batch):
                    raise GeminiEmbeddingError(
                        f"リクエスト件数 ({len(batch)}) と返却件数 ({len(res.embeddings) if res.embeddings else 0}) が一致しません。"
                    )
                for emb in res.embeddings:
                    values = emb.values
                    if len(values) != self.dimension:
                        raise GeminiEmbeddingError(
                            f"予期しない次元数です: 期待値 {self.dimension}, 実際 {len(values)}"
                        )
                    all_embeddings.append(values)
            except Exception as e:
                raise GeminiEmbeddingError(
                    f"バッチ Embedding 生成に失敗しました (index {i}〜{i+len(batch)-1}): {e}"
                ) from e

        return all_embeddings


def embed_text(
    text: str,
    api_key: Optional[str] = None,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> List[float]:
    """Helper function to embed a single text."""
    service = EmbeddingService(api_key=api_key, model=model)
    return service.embed_text(text)


def embed_texts(
    texts: List[str],
    api_key: Optional[str] = None,
    model: str = DEFAULT_EMBEDDING_MODEL,
    batch_size: int = 50,
) -> List[List[float]]:
    """Helper function to embed a list of texts."""
    service = EmbeddingService(api_key=api_key, model=model)
    return service.embed_texts(texts, batch_size=batch_size)


def run_diagnostics(raw_key: Optional[str], model: str = DEFAULT_EMBEDDING_MODEL) -> int:
    """Run full diagnostic suite via official Google GenAI SDK and print report."""
    print("=" * 70)
    print("  [Ingestion] Gemini API Diagnostic Tool (Official Google GenAI SDK)")
    print("=" * 70)

    if not GENAI_AVAILABLE:
        print("[FAILED] google-genai SDK がこの環境にインストールされていません。")
        print("         'uv sync' または 'pip install google-genai' を実行してください。")
        print("=" * 70)
        return 1

    if not raw_key:
        print("[!] API キーが指定されていません。")
        print("    --key 引数で直接渡すか、環境変数 GEMINI_API_KEY を設定してください。")
        print("=" * 70)
        return 1

    props = inspect_key_properties(raw_key)
    sanitized_key = sanitize_key(raw_key)

    print("[*] キー形式チェック:")
    print(f"    - マスク表示:           {props['masked']}")
    print(f"    - 文字長:               {props['sanitized_length']} 文字")
    print(f"    - AQ. プレフィックス:   {'はい (新形式 Auth Key)' if props['starts_with_aq'] else 'いいえ'}")
    print(f"    - AIza プレフィックス:  {'はい (従来形式 Standard Key)' if props['starts_with_aiza'] else 'いいえ'}")
    print(f"    - ASCII 文字列:         {'はい' if props['is_ascii'] else 'いいえ (不正な非ASCII文字あり)'}")
    print(f"    - 外側のクォート混入:   {'あり (自動除去済み)' if props['has_outer_quotes'] else 'なし'}")

    print("\n[*] 公式 Google GenAI SDK による疎通テスト実行中...")
    try:
        service = EmbeddingService(api_key=sanitized_key, model=model)
        dim = len(service.embed_text("健康・スポーツ科学実習"))
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
    parser = argparse.ArgumentParser(description="Gemini Embedding Diagnostic Tool for Ingestion (Official SDK)")
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

    target_key = args.key or os.getenv("GEMINI_API_KEY")
    exit_code = run_diagnostics(target_key, model=args.model)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
