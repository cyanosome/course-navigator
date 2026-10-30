"""検索方式比較のコーパス（科目の行・トピック・前提関係）を読む口（prereg_retrieval_seed.md §2）。

駒澤に差し替えるときは、このモジュールに読み込み関数を1つ足し、retrieval_compare から呼び分ける。
表名もここにまとめる（検索条件の SQL はこの定数を使う）。
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import asyncpg
from pydantic import BaseModel, Field

__all__ = [
    "EMBEDDING_TABLE",
    "SEED_PATH",
    "SYLLABUS_TABLE",
    "Corpus",
    "CourseDoc",
    "canonical_sha256",
    "document_body",
    "file_sha256",
    "load_seed_corpus",
    "merge_seed_metadata",
]

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = BACKEND_ROOT / "seed" / "courses.json"

# Yuto の DDL（course_core.repositories.postgres_repo）の表名
SYLLABUS_TABLE = "test_postgres_syllabus"
EMBEDDING_TABLE = "test_course_embeddings"

_TOPIC_SEPARATOR = "、"
_SELECT_SYLLABUS = (
    "SELECT id, code, title, instructor, schedule, credits, syllabus_text "
    f"FROM {SYLLABUS_TABLE} ORDER BY code ASC"
)


class CourseDoc(BaseModel):
    """1科目。id は PostgreSQL の主キー（シードでは Neo4j の Course.id と同じ値）。"""

    id: str
    code: str
    title: str
    instructor: str | None = None
    schedule: str | None = None
    credits: int | None = None
    syllabus_text: str | None = None
    topics: list[str] = Field(default_factory=list)
    prerequisite_codes: list[str] = Field(default_factory=list)


class Corpus(BaseModel):
    name: str
    courses: list[CourseDoc]

    def prerequisites(self) -> dict[str, list[str]]:
        return {course.code: list(course.prerequisite_codes) for course in self.courses}

    def row_snapshot(self) -> list[dict[str, Any]]:
        """PostgreSQL の行に当たる部分だけ（スナップショットのハッシュに使う）。"""
        return [
            course.model_dump(exclude={"topics", "prerequisite_codes"}) for course in self.courses
        ]


def document_body(course: CourseDoc) -> str:
    """埋め込む文書の本文（§3.1）。`トピック: A、B。{syllabus_text}`。トピックが無ければ本文だけ。"""
    text = course.syllabus_text or ""
    if not course.topics:
        return text
    return f"トピック: {_TOPIC_SEPARATOR.join(course.topics)}。{text}"


def canonical_sha256(value: object) -> str:
    """キー順を固定した JSON の SHA-256（スナップショットの同一性確認用）。"""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_seed_metadata(
    rows: Iterable[Mapping[str, Any]], seed: Sequence[Mapping[str, Any]]
) -> list[CourseDoc]:
    """DB の行に seed/courses.json のトピックと前提関係を足す。

    行と seed で科目コードの集合か科目名が食い違えば止める（どちらかが古いまま測るのを防ぐ）。
    """
    seed_by_code = {item["code"]: item for item in seed}
    courses = []
    for row in rows:
        code = row["code"]
        item = seed_by_code.get(code)
        if item is None:
            raise ValueError(f"{code} が seed/courses.json にありません")
        if item["title"] != row["title"]:
            raise ValueError(f"{code} の科目名が DB と seed で違います: {row['title']} / {item['title']}")
        courses.append(
            CourseDoc(
                id=str(row["id"]),
                code=code,
                title=row["title"],
                instructor=row["instructor"],
                schedule=row["schedule"],
                credits=row["credits"],
                syllabus_text=row["syllabus_text"],
                topics=list(item.get("topics", [])),
                prerequisite_codes=list(item.get("prerequisite_codes", [])),
            )
        )
    missing = sorted(seed_by_code.keys() - {course.code for course in courses})
    if missing:
        raise ValueError(f"DB に無い科目が seed にあります: {missing}")
    return courses


async def load_seed_corpus(conn: asyncpg.Connection) -> Corpus:
    """実験用 DB の test_postgres_syllabus と seed/courses.json からシードのコーパスを作る。"""
    rows = await conn.fetch(_SELECT_SYLLABUS)
    seed = json.loads(SEED_PATH.read_text("utf-8"))
    return Corpus(name="seed", courses=merge_seed_metadata(rows, seed))
