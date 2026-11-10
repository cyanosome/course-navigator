"""研究のセッションの開始で数えるデータの状態（制約 C8・C9、ab-variants.md 2.1）。

Cypher とクエリ実行のみを担当する。始めてよいかの判断は course_core/research/study.py の start_violations。
"""

from neo4j import AsyncSession

_COUNT_SIMILAR_TO = """
MATCH ()-[r:SIMILAR_TO]->()
RETURN count(r) AS edges, collect(DISTINCT r.model) AS models
"""


async def count_similar_to(session: AsyncSession) -> tuple[int, list[str]]:
    """SIMILAR_TO の本数と、線の model の値（偽の埋め込み deterministic-mock-768 を見分ける）。"""
    result = await session.run(_COUNT_SIMILAR_TO)
    record = await result.single(strict=True)
    models = sorted(str(model) for model in record["models"] if model is not None)
    return int(record["edges"]), models
