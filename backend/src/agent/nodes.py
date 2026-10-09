"""ADK の関数ノード（設計書 実験3-2 §2 / エラー処理の層B）。

層B の契約（§6）: **このモジュールには try...except を1つも書かない。**
層A（`course_core.graph.traversal`）が例外を `Envelope` に畳んで必ず値を返すので、
ここは `Envelope.ok` を見て分岐するだけでよい。障害は例外ではなく
「候補0件 + notes」という正常な分岐値で表現する（ADK のリトライ/HITL を壊さない）。

判断ロジック本体（意図解析・Evidence 生成・グラフ探索）はすべて別モジュールの
純関数 or 層A にあり、ここはそれらを ADK のノード signature に合わせて包むだけ。
"""

import os
from collections.abc import Awaitable, Callable

from google.adk import Context, Event
from google.genai import types

from agent import deps, grounding, intent_rules, rank
from agent.schemas import AnswerPayload, Candidate, CandidateSet, SearchIntent
from course_core import config
from course_core.graph import traversal
from course_core.repositories import postgres_repo
from course_core.schemas.traversal import Envelope

__all__ = [
    "MODE_STATE_KEY",
    "attach_sources",
    "compose_answer",
    "expand_backward",
    "expand_forward",
    "parse_intent",
    "rank_candidates",
    "respond_unclear",
    "route_by_mode",
    "route_initial",
    "search_by_topic",
]

# route_by_mode が読む state キー。state に置くのはこの短い文字列1個だけで、
# 候補データは全部 Event(output=...) で運ぶ（§2.2 の「state に大量データを入れない」）。
MODE_STATE_KEY = "temp:mode"

_UNSET_DRIVER_NOTE = "Neo4j ドライバが未設定です（deps.set_backends が呼ばれていません）。"
_UNSET_POOL_NOTE = (
    "PostgreSQL 接続プールが未設定のため出典を検証できませんでした"
    "（deps.set_backends が呼ばれていません）。"
)
_NO_CANDIDATE_ANSWER = "該当する科目が見つかりませんでした。"

# §12 変更2 の定型文。禁止語（難しい / 簡単 / 楽 / おすすめ / 評判 / 単位が取りやすい）を
# 1語も含まないこと自体が A10 の判定対象なので、文面を変えるときは必ず確認する。
_UNCLEAR_MESSAGES: dict[str, str] = {
    "no_mode": (
        "ご質問の意図を特定できませんでした。"
        "「〇〇の前提は?」「〇〇の次は?」「〇〇に近い科目は?」のいずれかの形でお尋ねください。"
    ),
    "not_found": "お尋ねの科目は見つかりませんでした。",
    "ambiguous": "お尋ねの名称に当てはまる科目が複数あります。どれについてお答えしましょうか。",
    "out_of_scope": "時間割・曜日時限による絞り込みには対応していません。",
    "decline": "難易度・履修者評価のデータは保持していないためお答えできません。",
}
_WITH_CATALOG_KINDS = ("no_mode", "not_found")
_CATALOG_PREFIX = "登録されている科目: "
_ALTERNATIVES_PREFIX = "候補: "
_LIST_SEPARATOR = "、"
_LINE_SEPARATOR = "\n"

_Finder = Callable[..., Awaitable[Envelope[list[Candidate]]]]


def _question_text(node_input: object) -> str:
    """エントリノードの入力は `types.Content` で来る（adk-research の 2026-08-05 smoke）。"""
    if isinstance(node_input, types.Content):
        return "".join(part.text or "" for part in (node_input.parts or []))
    return str(node_input)


def route_initial(node_input: object, ctx: Context) -> Event:
    """MCP 先行型ワークフローのルート判定ノード。

    AGENT_ENABLE_MCP が有効かつ GEMINI_API_KEY が設定されている場合は "mcp"、
    それ以外（キーなし、フォールバック時）は "static" を返す。
    """
    has_api_key = bool(config.GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY"))
    is_mcp_enabled = bool(config.AGENT_ENABLE_MCP)

    target_route = "mcp" if (is_mcp_enabled and has_api_key) else "static"
    return Event(output=node_input, route=[target_route])


def parse_intent(node_input: object, ctx: Context) -> Event:
    """質問文 → SearchIntent（LLM 0回・決定論）。判定は intent_rules の純関数に委ねる。"""
    intent = intent_rules.parse_intent(_question_text(node_input))
    return Event(output=intent, state={MODE_STATE_KEY: intent.mode})


def route_by_mode(node_input: SearchIntent, ctx: Context) -> Event:
    """4分岐のルータ（§2.1）。mode は state 経由で受け取る。

    キーが無ければ KeyError で落とす。ここで既定値に倒すと、ルーティングを外した
    ことに誰も気づかないままどれかの経路が走る（サイレント失敗）。
    """
    return Event(output=node_input, route=[ctx.state[MODE_STATE_KEY]])


async def _search_graph(intent: SearchIntent, finder: _Finder) -> CandidateSet:
    """層A の探索を1本呼び、Envelope を CandidateSet に畳む（層B の唯一の分岐点）。"""
    driver = deps.neo4j_driver()
    if driver is None:
        return CandidateSet(intent=intent, notes=[_UNSET_DRIVER_NOTE])

    async with driver.session() as session:
        envelope = await finder(session, intent.anchor_code)

    if not envelope.ok:
        return CandidateSet(intent=intent, notes=[envelope.message_ja])
    return CandidateSet(intent=intent, candidates=envelope.data or [])


async def expand_forward(node_input: SearchIntent, ctx: Context) -> Event:
    """後続探索 (c)<-[:REQUIRES_PREREQUISITE*1..3]-(next)。"""
    return Event(output=await _search_graph(node_input, traversal.find_next_courses))


async def expand_backward(node_input: SearchIntent, ctx: Context) -> Event:
    """前提探索 (c)-[:REQUIRES_PREREQUISITE*1..3]->(prereq)。"""
    return Event(output=await _search_graph(node_input, traversal.find_prerequisites))


async def search_by_topic(node_input: SearchIntent, ctx: Context) -> Event:
    """トピック共有探索 (c)-[:COVERS_TOPIC]->(t)<-[:COVERS_TOPIC]-(other)。"""
    return Event(
        output=await _search_graph(node_input, traversal.find_related_by_topic)
    )


def rank_candidates(node_input: CandidateSet, ctx: Context) -> Event:
    """3経路の合流点（§2.1）。並べ替えは層A 済みなので Evidence 生成だけを行う。

    合流前に積まれた notes（探索失敗の理由など）は落とさずに引き継ぐ。
    """
    ranked = rank.build_candidate_set(node_input.intent, node_input.candidates)
    if node_input.notes:
        ranked = ranked.model_copy(
            update={"notes": [*node_input.notes, *ranked.notes]}
        )
    return Event(output=ranked)


def compose_answer(node_input: CandidateSet, ctx: Context) -> Event:
    """ステップ5 の関数ノード版（LLM 0回）。Evidence を素朴に連結するだけ。

    ステップ6 で §11.2 の instruction を持つ Agent に差し替える。差し替えても edges を
    書き換えずに済むよう、入力を CandidateSet・出力を AnswerPayload に固定してある。
    """
    texts = [
        evidence.text
        for candidate in node_input.candidates
        for evidence in candidate.evidence
    ]
    if not texts:
        return Event(
            output=AnswerPayload(
                answer=_LINE_SEPARATOR.join([_NO_CANDIDATE_ANSWER, *node_input.notes])
            )
        )
    return Event(
        output=AnswerPayload(
            answer=_LINE_SEPARATOR.join(texts),
            cited_codes=[candidate.code for candidate in node_input.candidates],
        )
    )


async def attach_sources(node_input: AnswerPayload, ctx: Context) -> Event:
    """mcp_agent の後段で出典を付ける決定論ノード（LLM 0回・test3-2）。

    出典は LLM の生成テキストではなく、cited_codes を PostgreSQL で引き直した行から作る。
    DB に無いコードは unverified_codes に回す（ハルシネーション検出）。
    LlmAgent の出力は dict で届くが、ADK が型注釈に従って AnswerPayload に変換する。
    """
    pool = deps.db_pool()
    if pool is None:
        return Event(output=grounding.ungrounded_answer(node_input, _UNSET_POOL_NOTE))

    async with pool.acquire() as conn:
        rows = await postgres_repo.get_syllabi_by_codes(
            conn, grounding.normalize_codes(node_input.cited_codes)
        )
    return Event(output=grounding.build_grounded_answer(node_input, rows))


def respond_unclear(node_input: SearchIntent, ctx: Context) -> Event:
    """unclear_kind ごとの定型文（§12 変更2）。LLM 0回・候補コードを推測しない。"""
    kind = node_input.unclear_kind or "no_mode"
    lines = [_UNCLEAR_MESSAGES[kind]]
    if kind in _WITH_CATALOG_KINDS:
        lines.append(_CATALOG_PREFIX + _LIST_SEPARATOR.join(intent_rules.course_titles()))
    elif kind == "ambiguous" and node_input.alternatives:
        lines.append(_ALTERNATIVES_PREFIX + _LIST_SEPARATOR.join(node_input.alternatives))
    # cited_codes は空のまま。alternatives は聞き返しの選択肢であって
    # 「探索結果として提示した科目」ではない（A7 の cited_codes ⊆ candidates を保つ）。
    return Event(output=AnswerPayload(answer=_LINE_SEPARATOR.join(lines)))
