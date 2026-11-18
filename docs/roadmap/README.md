# ロードマップ運用ガイド (`docs/roadmap/`)

本ディレクトリは、「Course Navigator」の研究・開発ロードマップを **フェーズ・並列トラック単位で分割管理** するためのソースディレクトリです。

> [!IMPORTANT]
> **`docs/roadmap.md` は自動生成ファイルです。**
> ロードマップを編集する場合は、必ず本ディレクトリ（`docs/roadmap/*.md`）を編集し、ビルドスクリプトを実行して [docs/roadmap.md](../roadmap.md) を更新してください。

## 1. ディレクトリ構成

| ファイル | 役割 |
| :--- | :--- |
| [manifest.json](manifest.json) | 一列統合ビュー (`docs/roadmap.md`) の結合順序・見出しシフト・グループ定義 |
| [build.py](build.py) | 静的結合スクリプト（Python 標準ライブラリのみで動作） |
| [test_build.py](test_build.py) | `build.py` のユニットテスト（見出し・相対リンク・整合性検証） |
| [00-vision-and-ops.md](00-vision-and-ops.md) | プロジェクト理念・定例MTG・非営利方針・全体像 Mermaid 図 |
| [01-history-p1-p2.md](01-history-p1-p2.md) | 完了フェーズ（旧 Phase 1, Phase 2）の記録 |
| [02-phase3-kansai.md](02-phase3-kansai.md) | Phase 3（関西大学 Ingestion & DBS論文投稿） |
| [03-phase4a-kb.md](03-phase4a-kb.md) | Phase 4-0（体制拡充・開発/PM基盤） & Phase 4A（カリキュラム知識基盤・研究調査） |
| [04-phase4b-agent.md](04-phase4b-agent.md) | Phase 4B: 工学的システム改善（ログ・評価基盤 / Frontend・Backend・DB 改修） |
| [05-phase4c-univ.md](05-phase4c-univ.md) | Phase 4C: 実大学への全学展開・連携実証・資金/クレジット対策 |
| [06-phase5-production.md](06-phase5-production.md) | Phase 5: 全学・複数大学での本番運用 & Active Learning |
| [07-management-policy.md](07-management-policy.md) | 進捗・タスク管理方針（GitHub Projects / ADR / 実験記録） |

## 2. ビルド・検証コマンド

```bash
# 一列統合ビュー (docs/roadmap.md) を再生成する
uv run --no-project python docs/roadmap/build.py

# docs/roadmap/ と docs/roadmap.md が同期しているか検証する（CI用）
uv run --no-project python docs/roadmap/build.py --check

# ビルドスクリプトのテストを実行する
uv run --no-project python -m unittest docs/roadmap/test_build.py
```

`Makefile` が利用できる環境では以下も使用できます:

```bash
make roadmap
make roadmap-check
```
