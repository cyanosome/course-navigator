"""全条件で共有する QuerySpec を質問ごとに1回だけ作る（prereg_retrieval_seed.md §3.2）。

DB も LLM も使わない。各条件はコミットした JSON（specs/seed_query_specs.json）を読むだけにして、
質問の解釈の違いが条件の差に混ざらないようにする。

    uv run --no-sync python -m eval.query_spec --out eval/specs/seed_query_specs.json
"""

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent import intent_rules
from agent.schemas import Mode

__all__ = [
    "Constraints",
    "Direction",
    "QuerySpec",
    "build_spec",
    "escape_lucene",
    "load_specs",
    "parse_constraints",
]

Direction = Literal["forward", "backward", "topic"]
MODE_DIRECTION: dict[str, Direction] = {"next_step": "forward", "prereq": "backward", "topic": "topic"}

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = BACKEND_ROOT / "tests" / "golden" / "questions.json"

_TERM = re.compile(r"(春|秋)学期")
_DAY = re.compile(r"([月火水木金土日])曜")
_PERIOD = re.compile(r"(\d)限")
_CREDITS = re.compile(r"(\d+)単位")
# Lucene のクエリ構文で意味を持つ文字（&& と || は1文字ずつエスケープすれば足りる）
_LUCENE_SPECIAL = frozenset('+-&|!(){}[]^"~*?:\\/')


class Constraints(BaseModel):
    """質問文から決定的に取れるメタデータの絞り込み条件（C2 が使う）。"""

    term: str | None = None  # 例 "春学期"
    day: str | None = None  # 例 "金"
    period: int | None = None  # 例 3
    credits: int | None = None

    def is_empty(self) -> bool:
        return all(value is None for value in self.model_dump().values())


class QuerySpec(BaseModel):
    question_id: str
    question: str
    embedding_text: str  # 埋め込むテキスト（接頭辞は embeddings.format_query が付ける）
    mode: Mode
    direction: Direction | None = None
    anchor_code: str | None = None
    anchor_title: str | None = None
    anchor_status: str = "no_anchor"
    alternatives: list[str] = Field(default_factory=list)
    matched_rule: str = ""
    constraints: Constraints = Field(default_factory=Constraints)
    fulltext_query: str


def parse_constraints(question: str) -> Constraints:
    """学期・曜日・時限・単位数を正規表現で取る。全角数字は NFKC で半角に寄せてから当てる。"""
    text = unicodedata.normalize("NFKC", question)
    term = _TERM.search(text)
    day = _DAY.search(text)
    period = _PERIOD.search(text)
    credits = _CREDITS.search(text)
    return Constraints(
        term=f"{term.group(1)}学期" if term else None,
        day=day.group(1) if day else None,
        period=int(period.group(1)) if period else None,
        credits=int(credits.group(1)) if credits else None,
    )


def escape_lucene(text: str) -> str:
    """Neo4j 全文検索（Lucene）のクエリとして質問文をそのまま渡せるようにエスケープする。"""
    return "".join(f"\\{char}" if char in _LUCENE_SPECIAL else char for char in text)


def build_spec(question_id: str, question: str) -> QuerySpec:
    intent = intent_rules.parse_intent(question)
    return QuerySpec(
        question_id=question_id,
        question=question,
        embedding_text=question,
        mode=intent.mode,
        direction=MODE_DIRECTION.get(intent.mode),
        anchor_code=intent.anchor_code,
        anchor_title=intent.anchor_title,
        anchor_status=intent.anchor_status,
        alternatives=list(intent.alternatives),
        matched_rule=intent.matched_rule,
        constraints=parse_constraints(question),
        fulltext_query=escape_lucene(question),
    )


def load_specs(path: Path) -> list[QuerySpec]:
    return [QuerySpec.model_validate(item) for item in json.loads(path.read_text("utf-8"))]


def write_specs(golden: Path, out: Path) -> list[QuerySpec]:
    cases = json.loads(golden.read_text("utf-8"))
    specs = [build_spec(case["id"], case["question"]) for case in cases]
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = [spec.model_dump(mode="json") for spec in specs]
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return specs


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m eval.query_spec", description=__doc__)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    specs = write_specs(args.golden, args.out)
    print(f"wrote {len(specs)} specs to {args.out}")


if __name__ == "__main__":
    main(sys.argv[1:])
