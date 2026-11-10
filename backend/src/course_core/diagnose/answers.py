"""答えの検査と指紋（answers_digest）。

答えの形: {<question_id>: [<option_id>...]}（single・multi）か {<question_id>: <1〜5>}（scale5）。
- すべての質問に答える。知らない質問・選択肢、数の違い（single は1つ、multi は 1〜max_select、重なり無し）は誤り
- scale5 の n は n 番目の選択肢を選んだことにする
検査を通った答えは「質問 → 選んだ選択肢の id（設定の並び）」に揃える。指紋はこの揃えた答えから作るので、
選択肢を送る並びが違っても同じ指紋・同じプランになる。
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Final

from course_core.diagnose.config import SCALE5_POINTS, DiagnoseConfig, Question

__all__ = ["Answers", "RawAnswer", "answers_digest", "validate_answers"]

Answers = dict[str, tuple[str, ...]]
RawAnswer = Sequence[str] | int
_DIGEST_PREFIX: Final = "sha256:"


def _selected(question: Question, value: RawAnswer) -> tuple[tuple[str, ...] | None, str | None]:
    """(設定の並びに揃えた選択肢の id, 誤り)。"""
    if question.kind == "scale5":
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= SCALE5_POINTS:
            return None, f"{question.id}: 1〜{SCALE5_POINTS} の整数で答えてください"
        return (question.options[value - 1].id,), None
    if isinstance(value, (str, int)) or not isinstance(value, Sequence):
        return None, f"{question.id}: 選択肢の id の配列で答えてください"
    known = question.option_ids()
    unknown = [option_id for option_id in value if option_id not in known]
    if unknown:
        return None, f"{question.id}: 知らない選択肢です: {', '.join(map(str, unknown))}"
    if len(set(value)) != len(value):
        return None, f"{question.id}: 同じ選択肢が2回あります"
    limit = 1 if question.kind == "single" else question.max_select or 1
    if question.kind == "single" and len(value) != 1:
        return None, f"{question.id}: 1つだけ選んでください"
    if not 1 <= len(value) <= limit:
        return None, f"{question.id}: 1〜{limit} 個選んでください（{len(value)} 個）"
    chosen = set(value)
    return tuple(option_id for option_id in known if option_id in chosen), None


def validate_answers(config: DiagnoseConfig, raw: Mapping[str, RawAnswer]) -> tuple[Answers, list[str]]:
    """(揃えた答え, 誤りの一覧)。誤りが1つでもあれば答えは使わない。"""
    errors: list[str] = []
    unknown = [question_id for question_id in raw if config.question(question_id) is None]
    if unknown:
        errors.append(f"知らない質問です: {', '.join(unknown)}")
    missing = [question.id for question in config.questions if question.id not in raw]
    if missing:
        errors.append(f"答えていない質問があります: {', '.join(missing)}")
    answers: Answers = {}
    for question in config.questions:
        if question.id not in raw:
            continue
        selected, error = _selected(question, raw[question.id])
        if error is not None:
            errors.append(error)
        elif selected is not None:
            answers[question.id] = selected
    return answers, errors


def answers_digest(answers: Mapping[str, Sequence[str]]) -> str:
    """揃えた答えの指紋（ログで答えとプランを突き合わせる）。鍵の並び・選択肢の並びに左右されない。"""
    canonical = {question_id: sorted(option_ids) for question_id, option_ids in answers.items()}
    text = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _DIGEST_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()
