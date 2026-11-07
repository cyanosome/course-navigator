"""診断（質問に答えると履修プランを出す）のエンジン。LLM は使わず、同じ入力なら同じ出力を返す。

- model: エンジンの型（科目・系統図・設定）
- config: 設定の読み込みと検査（誤りは一覧で返す。数え方は事前登録の M1 と同じ）
- primitives: 設定で使える primitive 9つ
- answers: 答えの検査と指紋
- engine: プランの組み立てと理由の文
- source: DB の行から科目と系統図を作る（読み取りだけ）
設定のファイルは configs/<department_id>.json。
"""
