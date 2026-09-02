"""Workflow のグラフ定義（設計書 実験3-2 §2.2）。

分岐4本・合流1点・終端2箇所という構造そのものが実験3-2 の検証対象なので、
ノードの中身が関数であっても edges からノードを外さない（§10）。
"""

from google.adk import Workflow

from agent import nodes

__all__ = ["WORKFLOW_NAME", "workflow"]

WORKFLOW_NAME = "course_navigator_workflow"

workflow = Workflow(
    name=WORKFLOW_NAME,
    edges=[
        # edges の先頭には文字列 "START" が必須（2026-08-05 の ADK smoke で確定）。
        # 省くと実行時ではなく Workflow(...) の構築時に
        #   ValidationError: Graph validation failed.
        #   START node (name: '__START__') not found in graph nodes.
        # で落ちる。3要素以上のチェーン記法はこのエントリ指定にだけ使う。
        ("START", nodes.parse_intent, nodes.route_by_mode),
        (
            nodes.route_by_mode,
            {
                "next_step": nodes.expand_forward,
                "prereq": nodes.expand_backward,
                "topic": nodes.search_by_topic,
                "unclear": nodes.respond_unclear,
            },
        ),
        # 3経路 → 合流ノード rank_candidates
        (nodes.expand_forward, nodes.rank_candidates),
        (nodes.expand_backward, nodes.rank_candidates),
        (nodes.search_by_topic, nodes.rank_candidates),
        # 合流ノード → 回答生成（ステップ6 でこの右辺を Agent に差し替える）
        (nodes.rank_candidates, nodes.compose_answer),
    ],
)
