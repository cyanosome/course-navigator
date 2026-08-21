# course-agent

実験3-2「履修系統図に沿った検索」の意図パーサ・Evidence 生成、および将来の ADK Workflow
（関数ノード / ルータ / Runner）を置くパッケージ。

`google-adk` 依存をこのパッケージだけに閉じ込め、`course-api` / `course-ingestion` へ
伝播させないためにワークスペースの別メンバーとして切り出している。
現時点では `intent_rules.py` と `rank.py`（どちらも DB / LLM に触らない純関数）のみ。
