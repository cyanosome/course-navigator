"""意図パーサ（設計書 実験3-2 §4.3）。LLM の代替となる決定論的ルール群。

`parse_intent` は DB にも LLM にも触らない純関数で、`seed/courses.json` の辞書照合
だけで mode とアンカーを決める。外した質問は `matched_rule` を見てキーワード表に
1語足せば直る、という運用に閉じるのがこのモジュールの狙い。

> 禁止事項（LLM 版に差し替えるときの制約 / §4.3 末尾）:
> **LLM に科目コード（`GMS-\\d{3}`）を直接出力させてはならない。** LLM は「知らない」と
> 言わずに `GMS-305` のようなそれらしい存在しないコードを出す。決定論的なグラフ探索が
> その嘘のコードを受け取ると探索0件になり「該当なし」と区別がつかないため、実験の結論が
> 「系統図に沿った検索はできなかった」に化ける。LLM 版でも出力させてよいのは自然言語の語
> （anchor_term）までで、コードへの変換は必ずこのモジュールか resolve_anchor が行う。

NOTE(ステップ5 で結線): §4.3 の「段2・段3 で当たらなかった場合のみ
`postgres_repo.search_syllabus` の ILIKE にフォールバックする」は
`course_core.graph.traversal.resolve_anchor`（実装済み・層A）の責務であり、
DB を持ち込むとこの関数が純関数でなくなる。ワークフローノード側で
parse_intent が not_found を返したときにだけ resolve_anchor を呼ぶ形で結線する。
"""

import functools
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import NamedTuple

from agent.schemas import AnchorStatus, Mode, SearchIntent, UnclearKind

MODE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "prereq": ("前提", "必要", "先に", "履修条件", "受けるには", "取る前", "受ける前", "準備"),
    "next_step": (
        "次",
        "つぎ",
        "後に",
        "あとに",
        "その先",
        "先にある",
        "進める",
        "発展",
        "続き",
        "取ったら",
    ),
    "topic": ("関連", "近い", "似た", "同じ分野", "周辺", "ほかに"),
}
MODE_PRIORITY: tuple[Mode, ...] = ("prereq", "next_step", "topic")  # 真の同点時の優先順

# スコープ外を明示的に検出する語（unclear_kind を決めるためだけに使う）
OUT_OF_SCOPE_KEYWORDS = ("限", "曜", "空いて", "時間割")
# NOTE(設計書との差異): §4.3 の表は DECLINE_KEYWORDS に「おすすめ」を含めているが、
# golden q11「何かおすすめの授業ある?」の期待は unclear_kind="no_mode" であり両立しない。
# 判定基準である golden（§8.1）を正とし「おすすめ」を外した。
# A10 の禁止語チェックは respond_unclear の応答文側で担保する。
DECLINE_KEYWORDS = ("難しい", "簡単", "楽", "評判", "単位が取りやすい")

_RE_DROP = re.compile(r"[\s　・＆&()（）「」『』,、.。]")
# 段0 のコード直書き検出。ハイフンの有無と大文字小文字のゆれを吸収して正準化する。
_RE_COURSE_CODE = re.compile(r"([A-Za-z]{2,4})-?(\d{3})")

_SEED_ENV_VAR = "COURSE_SEED_FILE"
_SEED_RELATIVE = Path("seed") / "courses.json"

# 段3 の前方一致で使う最小の接頭辞長（1文字だと「デ」だけで全科目に当たってしまう）。
_MIN_PREFIX_LEN = 2
# ambiguous / not_found のときに聞き返しへ載せる件数（§4.3）。
_MAX_ALTERNATIVES = 3


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)  # 全角英数→半角、半角カナ→全角カナ
    s = s.lower()
    s = _RE_DROP.sub("", s)  # 空白・記号の除去
    s = _hiragana_to_katakana(s)  # 「でーたさいえんす」→「データサイエンス」
    return s.replace("ー", "")  # 長音を除去（表記ゆれ吸収）


def _hiragana_to_katakana(s: str) -> str:
    return "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in s)


class _CourseEntry(NamedTuple):
    """courses.json の1件を照合しやすい形に前処理したもの。"""

    code: str
    title: str
    norm_title: str
    # (正規化後のエイリアス, matched_rule に出す元の表記)
    norm_aliases: tuple[tuple[str, str], ...]


def _seed_path() -> Path:
    """`seed/courses.json` の場所を決める（§5.3 の単一ソース原則）。

    投入スクリプトと golden テストが同じ実ファイルを読むことで、科目を1件足したときに
    期待値だけ古いまま、という事故を構造的に防ぐ。ワークスペースメンバーは editable
    で入るので `__file__` から backend ルートまで遡れば見つかる。
    """
    override = os.getenv(_SEED_ENV_VAR)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _SEED_RELATIVE
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"{_SEED_RELATIVE} が見つかりません。環境変数 {_SEED_ENV_VAR} で指定してください。"
    )


@functools.cache
def _catalog() -> tuple[_CourseEntry, ...]:
    """courses.json を遅延ロードしてキャッシュする（コード昇順で固定）。"""
    raw = json.loads(_seed_path().read_text(encoding="utf-8"))
    entries = [
        _CourseEntry(
            code=course["code"],
            title=course["title"],
            norm_title=normalize(course["title"]),
            norm_aliases=tuple(
                (normalize(alias), alias) for alias in course.get("aliases", ())
            ),
        )
        for course in raw
    ]
    return tuple(sorted(entries, key=lambda e: e.code))


@functools.cache
def _keyword_scan_order() -> tuple[tuple[str, str, str], ...]:
    """(mode, 元のキーワード, 正規化キーワード) を文字数の降順に並べた走査順。

    NOTE(最長一致): mode キーワードは最長一致で数える。同一位置のスパンでは長い
    キーワードが短いキーワードを吸収する（例: q04「先にある」(next_step) が
    「先に」(prereq) を吸収し next_step 1ヒットのみになる）。そのため全 (mode, keyword)
    を文字数降順に走査し、既にヒット済みのスパンと重なる短いキーワードは数えない。
    MODE_PRIORITY は本当に同点になったときの tie-break にだけ使う。
    sorted は安定なので、同じ長さのキーワードは MODE_PRIORITY 順・表の記載順を保つ。
    """
    items = [
        (mode, keyword, normalize(keyword))
        for mode in MODE_PRIORITY
        for keyword in MODE_KEYWORDS[mode]
    ]
    return tuple(sorted(items, key=lambda item: -len(item[2])))


def _detect_mode(norm_question: str) -> tuple[Mode | None, str]:
    """正規化済みの質問文から mode を決める。戻り値は (mode, 当たったキーワード)。"""
    counts: dict[str, int] = {mode: 0 for mode in MODE_PRIORITY}
    first_keyword: dict[str, str] = {}
    claimed: list[tuple[int, int]] = []

    for mode, keyword, norm_keyword in _keyword_scan_order():
        start = norm_question.find(norm_keyword)
        while start != -1:
            end = start + len(norm_keyword)
            if not any(s < end and start < e for s, e in claimed):
                claimed.append((start, end))
                counts[mode] += 1
                first_keyword.setdefault(mode, keyword)
            start = norm_question.find(norm_keyword, start + 1)

    # max は最初の最大要素を返すので、同点なら MODE_PRIORITY の並びが効く。
    best = max(MODE_PRIORITY, key=lambda mode: counts[mode])
    if counts[best] == 0:
        return None, ""
    return best, first_keyword[best]


def _unclear_kind_without_mode(norm_question: str) -> tuple[UnclearKind, str]:
    """mode が決まらなかったときの unclear_kind をキーワードで決める。"""
    for keyword in OUT_OF_SCOPE_KEYWORDS:
        if normalize(keyword) in norm_question:
            return "out_of_scope", f"unclear:out_of_scope / keyword:{keyword}"
    for keyword in DECLINE_KEYWORDS:
        if normalize(keyword) in norm_question:
            return "decline", f"unclear:decline / keyword:{keyword}"
    return "no_mode", "unclear:no_mode"


class _AnchorResult(NamedTuple):
    code: str | None
    title: str | None
    status: AnchorStatus
    alternatives: tuple[str, ...]
    rule: str


def _resolve_by_code(nfkc_question: str) -> _AnchorResult | None:
    """段0: コード直書き。「gms301」→「GMS-301」に正準化してから照合する。"""
    match = _RE_COURSE_CODE.search(nfkc_question)
    if match is None:
        return None
    canonical = f"{match.group(1).upper()}-{match.group(2)}"
    for entry in _catalog():
        if entry.code == canonical:
            return _AnchorResult(
                entry.code, entry.title, "exact", (), f"code:{canonical}"
            )
    # 表記としてはコードだがカタログに無い = 存在しない科目。ここで打ち切る
    # （段1 以降に落とすと別科目を勝手に当ててしまい、サイレントな取り違えになる）。
    return _AnchorResult(None, None, "not_found", (), f"code:{canonical}(未登録)")


class _SubstringHit(NamedTuple):
    """段1・段2 の中間表現。並べ替えのキー（一致長・コード）を先頭に置く。"""

    length: int
    code: str
    title: str
    status: AnchorStatus
    rule: str


def _best_substring_hit(hits: list[_SubstringHit]) -> _AnchorResult | None:
    """段1・段2 の共通処理。複数科目が同時ヒットしたら最長一致優先 → コード昇順。"""
    if not hits:
        return None
    longest = max(hit.length for hit in hits)
    best = min((hit for hit in hits if hit.length == longest), key=lambda hit: hit.code)
    return _AnchorResult(best.code, best.title, best.status, (), best.rule)


def _resolve_by_alias(norm_question: str) -> _AnchorResult | None:
    """段1: エイリアスの正規化文字列が質問文に含まれるか。"""
    hits = [
        _SubstringHit(
            len(norm_alias), entry.code, entry.title, "alias", f"alias:{raw_alias}"
        )
        for entry in _catalog()
        for norm_alias, raw_alias in entry.norm_aliases
        if norm_alias and norm_alias in norm_question
    ]
    return _best_substring_hit(hits)


def _resolve_by_title(norm_question: str) -> _AnchorResult | None:
    """段2: 科目名の正規化文字列が質問文に含まれるか。"""
    hits = [
        _SubstringHit(
            len(entry.norm_title), entry.code, entry.title, "exact", f"title:{entry.title}"
        )
        for entry in _catalog()
        if entry.norm_title and entry.norm_title in norm_question
    ]
    return _best_substring_hit(hits)


def _resolve_by_title_prefix(norm_question: str) -> _AnchorResult | None:
    """段3: 科目名の正準な前方一致。1件なら確定、2件以上は ambiguous。

    各科目について「質問文に含まれる最長の接頭辞」を求め、その最大値を取る科目だけを
    残す（最長一致優先）。こうしないと「データサイエンスの次は?」で「データベース」が
    接頭辞「デタ」で紛れ込み、alternatives が3件に膨らんでしまう。
    """
    lengths: dict[str, int] = {}
    for entry in _catalog():
        if entry.norm_title in norm_question:
            continue  # 段2 で拾うべきもの（title 全体が含まれる）は対象外
        best = 0
        for size in range(_MIN_PREFIX_LEN, len(entry.norm_title)):
            if entry.norm_title[:size] in norm_question:
                best = size
        if best:
            lengths[entry.code] = best
    if not lengths:
        return None

    longest = max(lengths.values())
    matched = sorted(code for code, size in lengths.items() if size == longest)
    if len(matched) == 1:
        entry = next(e for e in _catalog() if e.code == matched[0])
        return _AnchorResult(
            entry.code, entry.title, "exact", (), f"title_prefix:{entry.title}"
        )
    alternatives = tuple(matched[:_MAX_ALTERNATIVES])
    return _AnchorResult(
        None, None, "ambiguous", alternatives, f"ambiguous:{','.join(alternatives)}"
    )


def _resolve_anchor(nfkc_question: str, norm_question: str) -> _AnchorResult:
    """アンカー解決4段（§4.3）。上から順に、最初に確定した段で打ち切る。"""
    for resolver in (
        lambda: _resolve_by_code(nfkc_question),
        lambda: _resolve_by_alias(norm_question),
        lambda: _resolve_by_title(norm_question),
        lambda: _resolve_by_title_prefix(norm_question),
    ):
        result = resolver()
        if result is not None:
            return result
    return _AnchorResult(None, None, "not_found", (), "not_found")


def parse_intent(question: str) -> SearchIntent:
    """質問文から SearchIntent を組み立てる（§4.3）。LLM も DB も使わない。

    実験4-2 以降で LLM 版に差し替えるときは、同一シグネチャの Agent ノードに
    置換するだけで Workflow のグラフは1行も変わらない。
    mode が決まらなければアンカー解決に進まず unclear に倒す（黙って推測しない）。
    """
    nfkc_question = unicodedata.normalize("NFKC", question)
    norm_question = normalize(question)

    mode, keyword = _detect_mode(norm_question)
    if mode is None:
        unclear_kind, rule = _unclear_kind_without_mode(norm_question)
        return SearchIntent(
            mode="unclear",
            unclear_kind=unclear_kind,
            raw_question=question,
            matched_rule=rule,
        )

    anchor = _resolve_anchor(nfkc_question, norm_question)
    matched_rule = f"keyword:{keyword} / {anchor.rule}"

    # ambiguous / not_found は絶対に候補を返さない。unclear に倒して聞き返す。
    if anchor.status in ("ambiguous", "not_found"):
        return SearchIntent(
            mode="unclear",
            anchor_status=anchor.status,
            alternatives=list(anchor.alternatives),
            unclear_kind=anchor.status,
            raw_question=question,
            matched_rule=matched_rule,
        )

    return SearchIntent(
        mode=mode,
        anchor_code=anchor.code,
        anchor_title=anchor.title,
        anchor_status=anchor.status,
        raw_question=question,
        matched_rule=matched_rule,
    )
