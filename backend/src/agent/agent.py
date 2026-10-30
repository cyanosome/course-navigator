"""adk web が自動検出するエージェントのエントリポイント。

`uv run adk web src/agent --host 0.0.0.0 --port 8085` で起動した際に
このファイルの `root_agent` が読み込まれる。
"""

import pydantic
from google.genai import types

from agent import deps
from agent.workflow import build_mcp_first_workflow
from course_core import config

# Pydantic v2 の MockValSer エラー回避:
# adk web (SqliteSessionService) が event.model_dump_json() を呼ぶ際、
# google.genai.types のモデルが遅延評価 (MockValSer) のまま残っていると
# TypeError: 'MockValSer' object is not an instance of 'SchemaSerializer'
# でクラッシュするため、起動時に一括で model_rebuild() を適用して SchemaSerializer をコンパイルする。
for _name in dir(types):
    _obj = getattr(types, _name)
    if isinstance(_obj, type) and issubclass(_obj, pydantic.BaseModel):
        try:
            _obj.model_rebuild()
        except Exception:
            pass

# adk web 等の CLI 起動時に static フォールバックが実 Neo4j にアクセスできるよう、
# deps のドライバが未設定なら環境変数から自動初期化する
if deps.neo4j_driver() is None and config.NEO4J_URI:
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver(
            config.NEO4J_URI,
            auth=(
                config.NEO4J_USER,
                config.NEO4J_PASSWORD or "secure_password_please_change",
            ),
        )
        deps.set_backends(None, driver)
    except Exception:
        pass
# 使用するモデルの指定はここか､.envで行うことができます｡
ACTIVE_MODEL = "gemini-3.5-flash"

# adk web 用のエントリポイント (MCP 先行型ワークフロー: ルート完全分離・フォールバック対応)
root_agent = build_mcp_first_workflow(model=ACTIVE_MODEL)
