"""変種（機能フラグの組み合わせ）の表と、組み合わせの制約の検査。

表は設計 ab-variants.md の付録 A（flags_version "1"）の写しに、11/7 の決定（人の A/B を「診断のみ」対
「診断＋対話」にする）で因子 F20 diagnose と V30・V31 を足したもの（flags_version "2"）。各変種の旗は、BASE_FLAGS に
差の "$ai_off" が真なら AI_OFF を重ね、さらに書いた差を重ねたもの。
モジュールを読み込んだ時点で全変種を validate_flags にかけ、外れたら import を失敗させる
（壊れた表をサイレントに直して動かさない）。

制約（ab-variants.md 2.1）の置き場所:
- 旗だけで決まるもの（C1・C2・C3・C5）: validate_flags。
- 人の study に入れられるか（C4・C7・C11）: human_study_violations。
- 課題セットとの両立（C6）: task_set_violations。
- 1つの study の中でそろえるもの（C8）: study_ai_edges_violations。
- 埋め込みが本物か（C9）: embedding_violations。DB の数え上げは呼ぶ側がする。
- C10 は表示の規則（データが無ければ「準備中」）で、旗の検査ではない。
"""

from collections.abc import Iterable, Mapping
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "AI_FLAG_NAMES",
    "AI_OFF",
    "BASE_FLAGS",
    "FLAGS_VERSION",
    "IMPLEMENTED_LEVELS",
    "MOCK_EMBEDDING_MODEL",
    "VARIANTS",
    "VARIANT_DIFFS",
    "VARIANT_NAMES",
    "VariantConstraintError",
    "VariantFlags",
    "build_flags",
    "embedding_violations",
    "human_study_violations",
    "study_ai_edges_violations",
    "task_set_violations",
    "validate_flags",
]

FLAGS_VERSION: Final = "2"
# 埋め込みの生成がキー無し・API 失敗のときに黙って切り替わる偽物のモデル名
# （ingestion/src/transformers/kansai/embedding_generator.py）。これ由来の SIMILAR_TO は意味を持たない。
MOCK_EMBEDDING_MODEL: Final = "deterministic-mock-768"
_AI_OFF_MARKER: Final = "$ai_off"


class VariantFlags(BaseModel):
    """20 個の旗（F01〜F20）。AI の旗は assistant=off のとき None（C3）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    search: Literal["kw", "kw_filter", "off"]
    graph: Literal["on", "off"]
    recommend: Literal["reach", "reach_seeded", "catalog", "off"]
    assistant: Literal["on", "off"]
    ai_route: Literal["mcp_grounded", "mcp_free", "static", "static_llm"] | None
    verify: Literal["on", "off"] | None
    citations: Literal["cards", "text"] | None
    first_suggestion: Literal["rule", "llm", "none"]
    style: Literal["standard", "brief", "detailed"] | None
    timetable: Literal["on", "off"]
    detail: Literal["full", "core"]
    question_frame: Literal["composed", "raw", "composed_guardrail"] | None
    toolset: Literal["reused", "per_request"] | None
    rule_edges: Literal["official_all", "official_prereq", "with_inferred"]
    ai_edges: Literal["official", "with_similar", "with_inferred"] | None
    model: Literal["default", "alt"] | None
    retrieval: Literal["agent_tools", "vector_seed"] | None
    similar_panel: Literal["off", "on"]
    requirements: Literal["shown", "hidden"]
    diagnose: Literal["off", "quiz"]  # F20（11/7）。quiz: 質問に答えるとプランを出す画面を足す


AI_FLAG_NAMES: Final = (
    "ai_route",
    "verify",
    "citations",
    "style",
    "question_frame",
    "toolset",
    "model",
    "ai_edges",
    "retrieval",
)

# --- 付録 A の表 ----------------------------------------------------------------

BASE_FLAGS: Final[Mapping[str, str]] = {
    "search": "kw",
    "graph": "on",
    "recommend": "reach",
    "assistant": "on",
    "ai_route": "mcp_grounded",
    "verify": "on",
    "citations": "cards",
    "first_suggestion": "rule",
    "style": "standard",
    "timetable": "on",
    "detail": "full",
    "question_frame": "composed",
    "toolset": "reused",
    "rule_edges": "official_all",
    "ai_edges": "official",
    "model": "default",
    "retrieval": "agent_tools",
    "similar_panel": "off",
    "requirements": "shown",
    "diagnose": "off",
}

AI_OFF: Final[Mapping[str, str | None]] = {
    "assistant": "off",
    **{name: None for name in AI_FLAG_NAMES},
}

VARIANT_DIFFS: Final[Mapping[str, Mapping[str, str | bool]]] = {
    "V00": {},
    "V01": {_AI_OFF_MARKER: True},
    "V02": {_AI_OFF_MARKER: True, "graph": "off", "recommend": "off", "first_suggestion": "none"},
    "V03": {"graph": "off", "recommend": "off", "first_suggestion": "none"},
    "V04": {_AI_OFF_MARKER: True, "recommend": "off", "first_suggestion": "none"},
    "V05": {_AI_OFF_MARKER: True, "recommend": "catalog"},
    "V06": {_AI_OFF_MARKER: True, "recommend": "reach_seeded"},
    "V07": {"ai_route": "mcp_free"},
    "V08": {"ai_route": "static_llm"},
    "V09": {"ai_route": "static"},
    "V10": {"citations": "text"},
    "V11": {"style": "brief"},
    "V12": {"style": "detailed"},
    "V13": {"first_suggestion": "llm"},
    "V14": {"question_frame": "raw"},
    "V15": {"question_frame": "composed_guardrail"},
    "V16": {"toolset": "per_request"},
    "V17": {_AI_OFF_MARKER: True, "timetable": "off"},
    "V18": {_AI_OFF_MARKER: True, "detail": "core"},
    "V19": {_AI_OFF_MARKER: True, "rule_edges": "official_prereq"},
    "V20": {_AI_OFF_MARKER: True, "rule_edges": "with_inferred"},
    "V21": {"model": "alt"},
    "V22": {
        _AI_OFF_MARKER: True,
        "graph": "off",
        "recommend": "off",
        "first_suggestion": "none",
        "search": "kw_filter",
    },
    "V23": {"verify": "off"},
    "V24": {_AI_OFF_MARKER: True, "search": "off"},
    "V25": {"ai_edges": "with_similar"},
    "V26": {"retrieval": "vector_seed"},
    "V27": {_AI_OFF_MARKER: True, "similar_panel": "on"},
    "V28": {"ai_edges": "with_inferred"},
    "V29": {_AI_OFF_MARKER: True, "requirements": "hidden"},
    # 11/7 に足した診断の変種（表の版 2）。V30 は診断のみ、V31 は診断＋対話（差は assistant と AI の旗だけ）
    "V30": {_AI_OFF_MARKER: True, "diagnose": "quiz"},
    "V31": {"diagnose": "quiz"},
}

# ab-variants.md 3 章の名前（CLI の一覧とログを人が読むため）。
VARIANT_NAMES: Final[Mapping[str, str]] = {
    "V00": "ai_full",
    "V01": "noai_full",
    "V02": "search_only",
    "V03": "search_ai",
    "V04": "graph_norec",
    "V05": "rec_catalog",
    "V06": "rec_seeded",
    "V07": "ai_mcp_free",
    "V08": "ai_static_llm",
    "V09": "ai_static",
    "V10": "ai_text",
    "V11": "ai_brief",
    "V12": "ai_detailed",
    "V13": "ai_first_llm",
    "V14": "ai_raw_q",
    "V15": "ai_guard_q",
    "V16": "ai_toolset_fresh",
    "V17": "noai_no_tt",
    "V18": "noai_detail_core",
    "V19": "noai_prereq_edges",
    "V20": "noai_inferred_edges",
    "V21": "ai_model_alt",
    "V22": "search_filters",
    "V23": "ai_verify_off",
    "V24": "noai_nosearch",
    "V25": "ai_with_similar",
    "V26": "ai_vector_seed",
    "V27": "noai_similar_panel",
    "V28": "ai_with_inferred",
    "V29": "noai_req_hidden",
    "V30": "noai_diag",
    "V31": "ai_diag",
}

# 凍結（11/8）までに画面と AI の口で効かせる水準（ab-variants.md 8 章）。人の study はこの水準だけで作る（C11）。
# None（効いていない旗）は常に許す。toolset は T14 で入った側の1つ: 使い回しが入らなければ、
# 凍結のときに V00 の値を per_request に読み替え、ここも per_request に替える（3 章の注）。
IMPLEMENTED_LEVELS: Final[Mapping[str, frozenset[str]]] = {
    "search": frozenset({"kw"}),
    "graph": frozenset({"on", "off"}),
    "recommend": frozenset({"reach", "off"}),
    "assistant": frozenset({"on", "off"}),
    "ai_route": frozenset({"mcp_grounded"}),
    "verify": frozenset({"on"}),
    "citations": frozenset({"cards"}),
    "first_suggestion": frozenset({"rule", "none"}),
    "style": frozenset({"standard"}),
    "timetable": frozenset({"on"}),
    "detail": frozenset({"full"}),
    "question_frame": frozenset({"composed"}),
    "toolset": frozenset({"reused"}),
    "rule_edges": frozenset({"official_all"}),
    "ai_edges": frozenset({"official"}),
    "model": frozenset({"default"}),
    "retrieval": frozenset({"agent_tools"}),
    "similar_panel": frozenset({"off"}),
    "requirements": frozenset({"shown", "hidden"}),
    "diagnose": frozenset({"off", "quiz"}),
}

# 本物の埋め込み（と、それから作った SIMILAR_TO）が要る水準（C9）。
_EMBEDDING_LEVELS: Final = (
    ("similar_panel", "on"),
    ("ai_edges", "with_similar"),
    ("retrieval", "vector_seed"),
)
# 線に出どころの属性が入るまで使えない水準（C7）。
_INFERRED_EDGE_LEVELS: Final = (
    ("rule_edges", "with_inferred"),
    ("ai_edges", "with_inferred"),
)
# 人の study では使えない水準（C4）。
_NOT_FOR_HUMANS_LEVELS: Final = (
    ("verify", "off"),
    ("ai_route", "static_llm"),
)


class VariantConstraintError(ValueError):
    """旗の組み合わせが制約を外れた。violations に外れた制約ごとの文を持つ。"""

    def __init__(self, violations: list[str], variant_id: str | None = None) -> None:
        self.violations = violations
        self.variant_id = variant_id
        where = f"変種 {variant_id} の" if variant_id else ""
        super().__init__(f"{where}旗が制約を満たしません: " + " / ".join(violations))


def validate_flags(flags: VariantFlags, variant_id: str | None = None) -> None:
    """旗だけで決まる制約（C1・C2・C3・C5）を検査し、外れていれば VariantConstraintError。"""
    violations: list[str] = []
    if flags.recommend != "off" and flags.graph != "on":
        violations.append(f"C1: recommend={flags.recommend} は graph=on のときだけ使える")
    if flags.first_suggestion == "rule" and flags.recommend == "off":
        violations.append("C2: first_suggestion=rule は recommend≠off のときだけ使える")
    if flags.first_suggestion == "llm" and flags.assistant != "on":
        violations.append("C2: first_suggestion=llm は assistant=on のときだけ使える")
    ai_values = {name: getattr(flags, name) for name in AI_FLAG_NAMES}
    if flags.assistant == "off":
        not_null = sorted(name for name, value in ai_values.items() if value is not None)
        if not_null:
            violations.append(f"C3: assistant=off なのに AI の旗に値がある: {', '.join(not_null)}")
    else:
        missing = sorted(name for name, value in ai_values.items() if value is None)
        if missing:
            violations.append(f"C3: assistant=on なのに AI の旗が null: {', '.join(missing)}")
    if flags.search == "off" and flags.graph != "on":
        violations.append("C5: search=off は graph=on のときだけ使える")
    if violations:
        raise VariantConstraintError(violations, variant_id)


def _levels_hit(flags: VariantFlags, levels: Iterable[tuple[str, str]]) -> list[str]:
    return [f"{name}={value}" for name, value in levels if getattr(flags, name) == value]


def human_study_violations(flags: VariantFlags) -> list[str]:
    """人の study に入れられない理由（C4・C7・C11）。空なら入れられる。"""
    violations = [f"C4: {hit} は人の study で使えない" for hit in _levels_hit(flags, _NOT_FOR_HUMANS_LEVELS)]
    violations += [
        f"C7: {hit} は線に出どころの属性が入るまで使えない"
        for hit in _levels_hit(flags, _INFERRED_EDGE_LEVELS)
    ]
    for name, allowed in IMPLEMENTED_LEVELS.items():
        value = getattr(flags, name)
        if value is not None and value not in allowed:
            violations.append(f"C11: {name}={value} は未実装の水準")
    return violations


def task_set_violations(flags: VariantFlags, *, has_grading_task: bool) -> list[str]:
    """課題セットと両立しない理由（C6: detail=core と成績のつけ方を答える課題 b）。"""
    if flags.detail == "core" and has_grading_task:
        return ["C6: detail=core は成績のつけ方を答える課題を含む課題セットと使えない"]
    return []


def study_ai_edges_violations(flags_list: Iterable[VariantFlags], *, human_study: bool) -> list[str]:
    """1つの study の中で ai_edges が1つの値にそろっているか（C8）。人の study は official だけ。"""
    values = sorted({flags.ai_edges for flags in flags_list if flags.ai_edges is not None})
    violations: list[str] = []
    if len(values) > 1:
        violations.append(f"C8: 1つの study の中で ai_edges がそろっていない: {', '.join(values)}")
    if human_study and any(value != "official" for value in values):
        violations.append("C8: 人の study の ai_edges は official だけ")
    return violations


def embedding_violations(flags: VariantFlags, embedding_models: Iterable[str]) -> list[str]:
    """本物の埋め込みが要る水準を、偽の埋め込みか埋め込み無しの DB で使おうとしていないか（C9）。

    embedding_models は DB の SIMILAR_TO（と埋め込み）の model の値。呼ぶ側が数える（D2 の similar_models）。
    """
    hits = _levels_hit(flags, _EMBEDDING_LEVELS)
    if not hits:
        return []
    models = set(embedding_models)
    if not models:
        return [f"C9: {hit} は埋め込みと SIMILAR_TO が DB に無いと使えない" for hit in hits]
    if MOCK_EMBEDDING_MODEL in models:
        return [f"C9: {hit} は偽の埋め込み（{MOCK_EMBEDDING_MODEL}）の DB では使えない" for hit in hits]
    return []


def build_flags(diff: Mapping[str, str | bool]) -> VariantFlags:
    """付録 A の差1つから旗の全量を作る（BASE → "$ai_off" なら AI_OFF → 差）。検査はしない。"""
    merged: dict[str, str | None] = dict(BASE_FLAGS)
    if diff.get(_AI_OFF_MARKER) is True:
        merged.update(AI_OFF)
    merged.update({name: value for name, value in diff.items() if name != _AI_OFF_MARKER})
    return VariantFlags.model_validate(merged)


def _build_variants() -> dict[str, VariantFlags]:
    variants: dict[str, VariantFlags] = {}
    for variant_id, diff in VARIANT_DIFFS.items():
        flags = build_flags(diff)
        validate_flags(flags, variant_id)
        variants[variant_id] = flags
    return variants


# 変種 ID → 旗の全量。読み込みで全変種を検査する（外れたら import が失敗する）。
VARIANTS: Final[Mapping[str, VariantFlags]] = _build_variants()
