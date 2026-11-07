"""診断の設定を機械で採点する（設計コンペの事前登録 comp-diag/protocol.md の M1〜M4）。

backend コンテナの /backend_app で実行する。データはローカルの関西の DB から1度だけ読んでメモリに置く（読み取りだけ。
app の lifespan は起動しない）か、この道具が保存したデータ（--save-snapshot）から読む:

    uv run --no-sync python -m eval.diag_metrics <設定.json か plan.md> [...] [--json-out out.json] [--plans-out plans.jsonl]
    uv run --no-sync python -m eval.diag_metrics <...> --save-snapshot snap.json   # DB から読んだデータも保存する
    uv run --no-sync python -m eval.diag_metrics <...> --snapshot snap.json        # 保存したデータで（DB を読まない）

入力が .md なら JSON のコードブロック（```json、無ければ { で始まる言語名なしのブロック）を中身を直さずに取り出す。
ブロックが無ければ「JSON が読めない」1件、2つ以上なら最初のものを使い「形の違反」1件を M1 に足す。

指標（プランは全学期の科目の syllabus_id の集合）:
- M1 設定の誤りの件数（course_core.diagnose.config.validate_config。まとまり ID は読んだ系統図で照らす）
- M2 答えの組み合わせごとのプランどうしの Jaccard 距離 1 − |A∩B|/|A∪B| の平均（全部の対。両方空なら 0）
- M3 全プランの科目の出現の HHI = Σ s_c²（s_c = 科目 c の出現回数 / 全出現回数）
- M4 埋める学期ごとに「上限まで（credits_total ≥ 上限。上限が null なら3科目以上）」埋まったプランの割合。表の値は学期の平均
答えの組み合わせ: single は選択肢ごと、multi は 1〜max_select 個の組み合わせ、scale5 は 1〜5。全部で 500 通りを超えるときは
random.Random(20261107).sample で 500 通りを選ぶ（番号は質問の順の混合基数。最後の質問がいちばん速く変わる）。
M1 が 1 以上の設定はエンジンが受け付けないので、M2〜M4 は出さない（null）。
"""

import argparse
import asyncio
import hashlib
import itertools
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import asyncpg
from neo4j import AsyncGraphDatabase

from course_core import config as env
from course_core.catalog.registry import DepartmentEntry, load_departments
from course_core.diagnose.answers import Answers
from course_core.diagnose.config import DiagnoseConfig, Question, parse_config, read_config_text, validate_config
from course_core.diagnose.engine import DiagnoseEngine
from course_core.diagnose.model import Catalog, ConfigIssue, DiagCourse, GroupInfo
from course_core.diagnose.source import load_catalog
from course_core.schemas.diagnose import DiagnosePlanOut

__all__ = [
    "MAX_COMBOS",
    "MIN_COURSES_WITHOUT_CAP",
    "SEED",
    "answer_choices",
    "catalog_from_snapshot",
    "catalog_to_snapshot",
    "extract_config_text",
    "fill_rates",
    "hhi",
    "mean_jaccard_distance",
    "sample_answers",
    "score_config",
]

MAX_COMBOS: Final = 500
SEED: Final = 20261107
MIN_COURSES_WITHOUT_CAP: Final = 3
DEFAULT_DEPARTMENT: Final = "kansai-enechem-2026"
SNAPSHOT_FORMAT: Final = "diag-catalog-v1"
_EPS: Final = 1e-9
_FENCE_CHARS: Final = ("`", "~")
_FENCE_MIN: Final = 3
_FENCE_INDENT_MAX: Final = 3


# --- 入力の取り出し ----------------------------------------------------------------------


def _code_blocks(text: str) -> list[tuple[str, str]]:
    """Markdown のフェンスのコードブロック（言語名, 中身）。閉じていないブロックは文書の終わりまで。"""
    blocks: list[tuple[str, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        fence_char = stripped[:1]
        run = len(stripped) - len(stripped.lstrip(fence_char)) if fence_char in _FENCE_CHARS else 0
        if indent > _FENCE_INDENT_MAX or run < _FENCE_MIN:
            index += 1
            continue
        info = (stripped[run:].split() or [""])[0].lower()  # 言語名（```json の json）
        body: list[str] = []
        index += 1
        while index < len(lines):
            closing = lines[index].strip()
            if closing and set(closing) == {fence_char} and len(closing) >= run:
                break
            body.append(lines[index])
            index += 1
        blocks.append((info, "\n".join(body)))
        index += 1
    return blocks


def extract_config_text(text: str) -> tuple[str | None, list[ConfigIssue]]:
    """応募作の Markdown から設定の JSON の文字列を取り出す（中身は直さない）。(文字列か None, M1 に足す誤り)。"""
    blocks = _code_blocks(text)
    candidates = [body for info, body in blocks if info == "json"]
    if not candidates:
        candidates = [body for info, body in blocks if info == "" and body.lstrip().startswith("{")]
    if not candidates:
        return None, [ConfigIssue("json", "$", "JSON のコードブロックがありません")]
    issues = []
    if len(candidates) > 1:
        issues.append(ConfigIssue("shape", "$", f"JSON のコードブロックが {len(candidates)} つあります（最初のものを使った）"))
    return candidates[0], issues


# --- 答えの組み合わせ --------------------------------------------------------------------


def answer_choices(question: Question) -> list[tuple[str, ...]]:
    """1つの質問の答え方の一覧（選んだ選択肢の id。設定の並び）。"""
    ids = question.option_ids()
    if question.kind == "multi":
        limit = question.max_select or 1
        return [combo for size in range(1, limit + 1) for combo in itertools.combinations(ids, size)]
    return [(option_id,) for option_id in ids]  # single と scale5（n 番目の選択肢）


def sample_answers(config: DiagnoseConfig, max_combos: int = MAX_COMBOS, seed: int = SEED) -> tuple[list[Answers], int, bool]:
    """(答えの一覧, 全組み合わせの数, 無作為に選んだか)。"""
    choices = [answer_choices(question) for question in config.questions]
    radices = [len(options) for options in choices]
    total = 1
    for radix in radices:
        total *= radix
    sampled = total > max_combos
    numbers = sorted(random.Random(seed).sample(range(total), max_combos)) if sampled else list(range(total))
    answers: list[Answers] = []
    for number in numbers:
        digits: list[int] = []
        for radix in reversed(radices):
            number, digit = divmod(number, radix)
            digits.append(digit)
        digits.reverse()
        answers.append(
            {question.id: choices[position][digit] for position, (question, digit) in enumerate(zip(config.questions, digits))}
        )
    return answers, total, sampled


# --- 指標 --------------------------------------------------------------------------------


def _course_set(plan: DiagnosePlanOut) -> frozenset[str]:
    return frozenset(course.syllabus_id for term in plan.terms for course in term.courses)


def mean_jaccard_distance(plans: Sequence[frozenset[str]]) -> float:
    """全部の対の Jaccard 距離の平均。プランが1つ以下なら 0。"""
    pairs = 0
    total = 0.0
    for first, second in itertools.combinations(plans, 2):
        union = len(first | second)
        total += 0.0 if union == 0 else 1.0 - len(first & second) / union
        pairs += 1
    return total / pairs if pairs else 0.0


def hhi(plans: Sequence[frozenset[str]]) -> float | None:
    """科目の出現の HHI。どのプランにも科目が無ければ None。"""
    counts = Counter(course for plan in plans for course in plan)
    occurrences = sum(counts.values())
    if occurrences == 0:
        return None
    return sum((count / occurrences) ** 2 for count in counts.values())


def fill_rates(plans: Sequence[DiagnosePlanOut], cap: float | None) -> list[dict[str, Any]]:
    """埋める学期ごとの、上限まで（上限が null なら3科目以上）埋まったプランの割合と平均。"""
    if not plans:
        return []
    rows = []
    for position, first in enumerate(plans[0].terms):
        terms = [plan.terms[position] for plan in plans]
        filled = [
            term.credits_total >= cap - _EPS if cap is not None else len(term.courses) >= MIN_COURSES_WITHOUT_CAP
            for term in terms
        ]
        rows.append(
            {
                "year": first.year,
                "term": first.term,
                "rate": sum(filled) / len(terms),
                "mean_credits": sum(term.credits_total for term in terms) / len(terms),
                "mean_courses": sum(len(term.courses) for term in terms) / len(terms),
            }
        )
    return rows


def _issue_json(issue: ConfigIssue) -> dict[str, str]:
    return {"kind": issue.kind, "path": issue.path, "message": issue.message}


def score_config(
    text: str,
    catalog: Catalog,
    *,
    markdown: bool,
    max_combos: int = MAX_COMBOS,
    seed: int = SEED,
    plans_sink: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """1つの設定（JSON の文字列か、応募作の Markdown）の M1〜M4。plans_sink を渡すと答えとプランを足す。"""
    issues: list[ConfigIssue] = []
    config_text: str | None = text
    if markdown:
        config_text, issues = extract_config_text(text)
    raw: Any = None
    if config_text is not None:
        raw, read_issues = read_config_text(config_text)
        issues += read_issues
        if not read_issues:
            issues += validate_config(raw, department_id=catalog.department_id, known_groups=catalog.group_ids)
    result: dict[str, Any] = {
        "config_version": raw.get("version") if isinstance(raw, dict) else None,
        "M1": {
            "count": len(issues),
            "by_kind": dict(sorted(Counter(issue.kind for issue in issues).items())),
            "issues": [_issue_json(issue) for issue in issues],
        },
        "M2": None,
        "M3": None,
        "M4": None,
        "combos": None,
        "plans": None,
    }
    if issues:
        result["skipped"] = "設定に誤りがあるのでエンジンに流していない（M2〜M4 は null）"
        return result

    config = parse_config(raw)
    engine = DiagnoseEngine(config, catalog)
    answers_list, total, sampled = sample_answers(config, max_combos, seed)
    plans = [engine.plan(answers) for answers in answers_list]
    sets = [_course_set(plan) for plan in plans]
    rates = fill_rates(plans, config.credit_cap_per_term)
    counts = Counter(course for plan_set in sets for course in plan_set)
    names = {course.syllabus_id: course.name for course in catalog.courses}
    result.update(
        {
            "M2": mean_jaccard_distance(sets),
            "M3": hhi(sets),
            "M4": {"mean": sum(row["rate"] for row in rates) / len(rates) if rates else None, "per_term": rates},
            "combos": {"total": total, "used": len(plans), "sampled": sampled, "seed": seed, "max": max_combos},
            "plans": {
                "distinct": len(set(sets)),
                "mean_courses": sum(len(plan_set) for plan_set in sets) / len(sets) if sets else 0.0,
                "courses_ever_used": len(counts),
                "top_courses": [
                    {"syllabus_id": syllabus_id, "name": names.get(syllabus_id, ""), "plans": count, "share_of_plans": count / len(sets)}
                    for syllabus_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]
                ],
            },
        }
    )
    if plans_sink is not None:
        plans_sink.extend(
            {
                "config_version": config.version,
                "answers": {question_id: list(option_ids) for question_id, option_ids in answers.items()},
                "answers_digest": plan.answers_digest,
                "terms": [
                    {"year": term.year, "term": term.term, "credits_total": term.credits_total,
                     "syllabus_ids": [course.syllabus_id for course in term.courses]}
                    for term in plan.terms
                ],
            }
            for answers, plan in zip(answers_list, plans)
        )
    return result


# --- データの読み込みと保存 -----------------------------------------------------------------


def catalog_to_snapshot(catalog: Catalog) -> dict[str, Any]:
    """Catalog を JSON にする（科目の本文を含むのでリポに入れない）。"""
    return {
        "format": SNAPSHOT_FORMAT,
        "department_id": catalog.department_id,
        "data_version": catalog.data_version,
        "courses": [{**asdict(course), "slots": list(course.slots), "texts": dict(course.texts)} for course in catalog.courses],
        "groups": [asdict(group) for group in catalog.groups.values()],
        "edges": [list(edge) for edge in catalog.edges],
    }


def catalog_from_snapshot(data: dict[str, Any]) -> Catalog:
    if data.get("format") != SNAPSHOT_FORMAT:
        raise ValueError(f"保存したデータの形が違います（{SNAPSHOT_FORMAT} ではない）: {data.get('format')!r}")
    return Catalog.build(
        department_id=data["department_id"],
        data_version=data["data_version"],
        courses=[DiagCourse(**{**course, "slots": tuple(course["slots"])}) for course in data["courses"]],
        groups=[GroupInfo(**group) for group in data["groups"]],
        edges=[(source, target) for source, target in data["edges"]],
    )


async def _catalog_from_db(department: DepartmentEntry) -> Catalog:
    """ローカルの DB から1度だけ読む（読み取りだけ）。接続先は backend と同じ環境変数。"""
    env.validate_required_env()
    conn = await asyncpg.connect(
        host=env.DB_HOST, port=env.DB_PORT, user=env.DB_USER, password=env.DB_PASSWORD, database=env.DB_NAME
    )
    driver = AsyncGraphDatabase.driver(env.NEO4J_URI, auth=(env.NEO4J_USER, env.NEO4J_PASSWORD))
    try:
        async with driver.session() as session:
            return await load_catalog(conn, session, department)
    finally:
        await conn.close()
        await driver.close()


# --- 表 ----------------------------------------------------------------------------------


def _number(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_table(results: Sequence[dict[str, Any]]) -> str:
    lines = [
        "| 入力 | 版 | M1 誤り | M2 Jaccard 距離の平均 | M3 HHI | M4 埋まった割合 | 組み合わせ（流した/全部） | 違うプラン | 平均科目数 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        combos = result["combos"]
        plans = result["plans"]
        lines.append(
            "| {input} | {version} | {m1} | {m2} | {m3} | {m4} | {combos} | {distinct} | {mean} |".format(
                input=Path(result["input"]).name if result["input"] else "",
                version=result["config_version"] or "—",
                m1=result["M1"]["count"],
                m2=_number(result["M2"]),
                m3=_number(result["M3"], 4),
                m4=_number(result["M4"]["mean"]) if result["M4"] else "—",
                combos=f"{combos['used']}/{combos['total']}" + ("（無作為）" if combos["sampled"] else "") if combos else "—",
                distinct=plans["distinct"] if plans else "—",
                mean=_number(plans["mean_courses"], 1) if plans else "—",
            )
        )
    for result in results:
        name = Path(result["input"]).name if result["input"] else ""
        if result["M4"]:
            per_term = "、".join(
                f"{row['year']}年{row['term']} {row['rate']:.3f}（平均 {row['mean_credits']:.1f} 単位・{row['mean_courses']:.1f} 科目）"
                for row in result["M4"]["per_term"]
            )
            lines.append(f"\n{name} の M4 の学期ごと: {per_term}")
        if result["M1"]["issues"]:
            lines.append(f"\n{name} の M1 の誤り（{result['M1']['count']} 件）:")
            lines += [f"- [{issue['kind']}] {issue['path']}: {issue['message']}" for issue in result["M1"]["issues"]]
    return "\n".join(lines)


# --- 入口 --------------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="診断の設定の M1〜M4（comp-diag/protocol.md）")
    parser.add_argument("inputs", nargs="+", type=Path, help="設定の JSON か、応募作の plan.md（JSON のコードブロックを取り出す）")
    parser.add_argument("--department", default=DEFAULT_DEPARTMENT)
    parser.add_argument("--snapshot", type=Path, help="この道具が保存したデータから読む（DB を読まない）")
    parser.add_argument("--save-snapshot", type=Path, help="DB から読んだデータを保存する（科目の本文を含む。リポに入れない）")
    parser.add_argument("--json-out", type=Path, help="結果の JSON の置き場（無ければ表のあとに標準出力へ）")
    parser.add_argument("--plans-out", type=Path, help="答えとプランの生データ（JSONL）の置き場")
    parser.add_argument("--git-sha", default=None, help="実行したコードの commit（コンテナに .git が無いのでホストから渡す）")
    parser.add_argument("--max-combos", type=int, default=MAX_COMBOS)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    department = load_departments().get(args.department)
    if department is None:
        parser.error(f"登録に無い学科です: {args.department}")
    if args.snapshot is not None:
        catalog = catalog_from_snapshot(json.loads(args.snapshot.read_text(encoding="utf-8")))
        data_source = {"source": "snapshot", "path": str(args.snapshot), "sha256": _sha256(args.snapshot)}
    else:
        catalog = asyncio.run(_catalog_from_db(department))
        data_source = {"source": "db"}
        if args.save_snapshot is not None:
            args.save_snapshot.write_text(json.dumps(catalog_to_snapshot(catalog), ensure_ascii=False), encoding="utf-8")
            data_source |= {"saved_snapshot": str(args.save_snapshot), "sha256": _sha256(args.save_snapshot)}
    if catalog.department_id != department.id:
        parser.error(f"データの学科 {catalog.department_id} が --department と違います")

    plans_sink: list[dict[str, Any]] | None = [] if args.plans_out is not None else None
    results = []
    for path in args.inputs:
        before = len(plans_sink) if plans_sink is not None else 0
        result = score_config(
            path.read_text(encoding="utf-8"),
            catalog,
            markdown=path.suffix.lower() == ".md",
            max_combos=args.max_combos,
            seed=args.seed,
            plans_sink=plans_sink,
        )
        if plans_sink is not None:
            for row in plans_sink[before:]:
                row["input"] = str(path)
        results.append({"input": str(path), "input_sha256": _sha256(path), **result})

    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": args.git_sha,
        "protocol": "comp-diag/protocol.md（M1〜M4）",
        "department_id": department.id,
        "data": data_source
        | {
            "data_version": catalog.data_version,
            "course_count": len(catalog.courses),
            "group_count": len(catalog.groups),
            "edge_count": len(catalog.edges),
        },
        "results": results,
    }
    print(render_table(results))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out is not None:
        args.json_out.write_text(text + "\n", encoding="utf-8")
        print(f"\nJSON: {args.json_out}")
    else:
        print("\n" + text)
    if plans_sink is not None:
        args.plans_out.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in plans_sink), encoding="utf-8")
        print(f"プラン: {args.plans_out}（{len(plans_sink)} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
