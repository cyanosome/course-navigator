"""Gemini API Authentication & Diagnostic CLI Tool.

Enables a rapid feedback loop for validating Gemini API keys (including new AQ. prefix keys),
testing Google GenAI SDK vs REST headers, verifying gemini-embedding-001 and text generation,
and providing actionable suggestions on failure without restarting containers.
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional

import httpx

try:
    from google import genai
    from google.genai.errors import ClientError
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    ClientError = Exception
    GENAI_AVAILABLE = False


def mask_key(key: str) -> str:
    """Safely mask API key showing only prefix and length."""
    if not key:
        return "<EMPTY>"
    if len(key) <= 8:
        return f"{key[:2]}*** (len={len(key)})"
    return f"{key[:6]}...{key[-4:]} (len={len(key)})"


def sanitize_key(key: Optional[str]) -> str:
    """Trim leading/trailing whitespaces, newlines, and single/double quotes."""
    if not key:
        return ""
    return key.strip().strip("'\"").strip()


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


def analyze_error_reason(status_code: int, error_text: str) -> list[str]:
    """Analyze error response and produce actionable suggestions."""
    suggestions = []
    text_lower = error_text.lower()

    if "access_token_type_unsupported" in text_lower or (status_code == 401 and "aq." in error_text):
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
    elif status_code == 401:
        suggestions.append("API キーが無効（401 UNAUTHENTICATED）です。キー文字列のコピー漏れや誤記がないかご確認ください。")
    elif status_code == 403:
        suggestions.append("アクセス権限エラー（403 PERMISSION_DENIED）です。プロジェクトの利用規約同意や課金設定状況をご確認ください。")
    elif status_code == 404:
        suggestions.append("モデルが見つかりません（404 NOT_FOUND）。モデル名に 'models/' プレフィックスが付いているかご確認ください。")
    elif status_code == 429:
        suggestions.append("レート制限超過（429 RESOURCE_EXHAUSTED）です。少し時間をおいてから再試行してください。")
    else:
        suggestions.append(f"エラーコード {status_code}: ネットワーク環境またはプロキシ設定をご確認ください。")

    return suggestions


async def test_rest_embedding(key: str, model: str = "gemini-embedding-001") -> Dict[str, Any]:
    """Test embedding via direct REST with x-goog-api-key header."""
    normalized_model = model if model.startswith("models/") else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:embedContent"
    payload = {
        "model": normalized_model,
        "content": {"parts": [{"text": "健康・スポーツ科学実習"}]},
        "taskType": "RETRIEVAL_QUERY",
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                values = data.get("embedding", {}).get("values", [])
                return {"ok": True, "status": 200, "dimension": len(values)}
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
    except Exception as e:
        return {"ok": False, "status": -1, "error": str(e)}


async def test_rest_generate(key: str, model: str = "gemini-3.5-flash-lite") -> Dict[str, Any]:
    """Test text generation via direct REST with x-goog-api-key header."""
    normalized_model = model if model.startswith("models/") else f"models/{model}"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": "ping"}]}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                return {"ok": True, "status": 200, "reply": text.strip()[:60]}
            return {"ok": False, "status": resp.status_code, "error": resp.text[:300]}
    except Exception as e:
        return {"ok": False, "status": -1, "error": str(e)}


def test_sdk_embedding(key: str, model: str = "gemini-embedding-001") -> Dict[str, Any]:
    """Test embedding via official google-genai SDK."""
    if not GENAI_AVAILABLE:
        return {"ok": False, "error": "google-genai SDK is not installed"}
    try:
        client = genai.Client(api_key=key)
        res = client.models.embed_content(model=model, contents="健康・スポーツ科学実習")
        dim = len(res.embeddings[0].values) if res.embeddings else 0
        return {"ok": True, "dimension": dim}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def test_sdk_generate(key: str, model: str = "gemini-3.5-flash-lite") -> Dict[str, Any]:
    """Test text generation via official google-genai SDK."""
    if not GENAI_AVAILABLE:
        return {"ok": False, "error": "google-genai SDK is not installed"}
    try:
        client = genai.Client(api_key=key)
        res = client.models.generate_content(model=model, contents="ping")
        text = res.text or ""
        return {"ok": True, "reply": text.strip()[:60]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


async def run_diagnostics(raw_key: Optional[str]) -> int:
    """Run full diagnostic suite and print a structured report."""
    print("=" * 70)
    print("  Gemini API Diagnostic Tool (Feedback Loop Engine)")
    print("=" * 70)

    if not raw_key:
        print("[!] API キーが指定されていません。")
        print("    --key 引数で直接渡すか、環境変数 GEMINI_API_KEY を設定してください。")
        print("=" * 70)
        return 1

    props = inspect_key_properties(raw_key)
    sanitized_key = sanitize_key(raw_key)

    print(f"[*] キー形式チェック:")
    print(f"    - マスク表示:           {props['masked']}")
    print(f"    - 文字長:               {props['sanitized_length']} 文字")
    print(f"    - AQ. プレフィックス:   {'はい (新形式 Auth Key)' if props['starts_with_aq'] else 'いいえ'}")
    print(f"    - AIza プレフィックス:  {'はい (従来形式 Standard Key)' if props['starts_with_aiza'] else 'いいえ'}")
    print(f"    - ASCII 文字列:         {'はい' if props['is_ascii'] else 'いいえ (不正な非ASCII文字あり)'}")
    print(f"    - 外側のクォート混入:   {'あり (サニタイズで自動除去)' if props['has_outer_quotes'] else 'なし'}")
    print(f"    - 空白/改行混入:        {'あり (要確認)' if props['has_internal_whitespace'] else 'なし'}")

    print("\n[*] 疎通プローブ実行中...")

    # 1. SDK Tests
    sdk_embed = test_sdk_embedding(sanitized_key)
    sdk_gen = test_sdk_generate(sanitized_key)

    # 2. REST Tests
    rest_embed = await test_rest_embedding(sanitized_key)
    rest_gen = await test_rest_generate(sanitized_key)

    print("\n[*] 診断結果一覧:")
    print(f"    1. 公式 SDK - Embedding (gemini-embedding-001):")
    if sdk_embed["ok"]:
        print(f"       [SUCCESS] 成功 (取得次元: {sdk_embed['dimension']}次元)")
    else:
        print(f"       [FAILED] 失敗: {sdk_embed.get('error', '')}")

    print(f"    2. 公式 SDK - Chat/Text (gemini-3.5-flash-lite):")
    if sdk_gen["ok"]:
        print(f"       [SUCCESS] 成功 (応答: {sdk_gen['reply']})")
    else:
        print(f"       [FAILED] 失敗: {sdk_gen.get('error', '')}")

    print(f"    3. REST API - Embedding (x-goog-api-key):")
    if rest_embed["ok"]:
        print(f"       [SUCCESS] 成功 (HTTP {rest_embed['status']}, 次元: {rest_embed['dimension']}次元)")
    else:
        print(f"       [FAILED] 失敗 (HTTP {rest_embed.get('status')}): {rest_embed.get('error', '')}")

    print(f"    4. REST API - Chat/Text (x-goog-api-key):")
    if rest_gen["ok"]:
        print(f"       [SUCCESS] 成功 (HTTP {rest_gen['status']}, 応答: {rest_gen['reply']})")
    else:
        print(f"       [FAILED] 失敗 (HTTP {rest_gen.get('status')}): {rest_gen.get('error', '')}")

    # Overall Evaluation
    all_success = sdk_embed["ok"] and sdk_gen["ok"]
    any_success = sdk_embed["ok"] or sdk_gen["ok"] or rest_embed["ok"] or rest_gen["ok"]

    print("\n" + "=" * 70)
    if all_success:
        print("  【判定】 PERFECT: すべての Gemini API 呼び出しが正常に動作しています！")
        print("=" * 70)
        return 0

    if any_success:
        print("  【判定】 PARTIAL: 一部の機能は成功していますが、未疎通のエンドポイントがあります。")
    else:
        print("  【判定】 FAILED: すべての API 呼び出しが拒否されました。")

    print("\n【トラブルシューティング処方箋 (Feedback Loop)】")
    sample_error = (
        sdk_embed.get("error")
        or rest_embed.get("error")
        or sdk_gen.get("error")
        or ""
    )
    status_code = rest_embed.get("status") or rest_gen.get("status") or 401
    suggestions = analyze_error_reason(status_code, sample_error)
    for sug in suggestions:
        print(f"\n{sug}")

    print("\n" + "=" * 70)
    print("  ※ 修正したキーをテストする際は、コンテナ再起動不要で以下を実行してください:")
    print("     docker exec course-navigator-backend-1 python -m src.tools.verify_gemini --key \"<新しいキー>\"")
    print("=" * 70)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini API Diagnostic & Verification Tool")
    parser.add_argument(
        "--key",
        "-k",
        type=str,
        default=None,
        help="Test a specific API key directly without updating .env or restarting containers.",
    )
    args = parser.parse_args()

    target_key = args.key or os.getenv("GEMINI_API_KEY")
    exit_code = asyncio.run(run_diagnostics(target_key))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
