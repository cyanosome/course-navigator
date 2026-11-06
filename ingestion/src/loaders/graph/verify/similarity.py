"""
Neo4j Course Embedding and Similarity Verification CLI.

Provides command-line diagnostics to inspect:
- Embedding coverage and Vector Index status
- [:SIMILAR_TO] edge distribution and course-to-course neighbors
- Dynamic vector query execution via CALL db.index.vector.queryNodes
"""

import argparse
import logging
import os
from typing import Any, Dict, List, Optional
from neo4j import GraphDatabase, Driver

from src.services.embedding import embed_text

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
DEFAULT_NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
DEFAULT_NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "devpassword")
INDEX_NAME = "course_embedding_index"


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Driver:
    """Create Neo4j driver connection."""
    u = uri or os.getenv("NEO4J_URI", DEFAULT_NEO4J_URI)
    usr = user or os.getenv("NEO4J_USER", DEFAULT_NEO4J_USER)
    pwd = password or os.getenv("NEO4J_PASSWORD", DEFAULT_NEO4J_PASSWORD)
    return GraphDatabase.driver(u, auth=(usr, pwd))


class SimilarityVerifier:
    """Diagnostic inspector for embeddings, Vector Indexes, and similarity edges."""

    def __init__(self, driver: Optional[Driver] = None):
        self.driver = driver or get_driver()
        self._owned_driver = driver is None

    def close(self):
        if self._owned_driver and self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def check_stats(self) -> Dict[str, Any]:
        """Aggregate statistics for embeddings and similarity edges."""
        with self.driver.session() as session:
            # 1. Course node stats
            course_res = session.run(
                """
                MATCH (c:Course)
                RETURN count(c) AS total_courses,
                       count(c.embedding) AS courses_with_embedding;
                """
            ).single()

            total_courses = course_res["total_courses"]
            courses_with_emb = course_res["courses_with_embedding"]

            # 2. Similarity edge stats
            edge_res = session.run(
                """
                MATCH ()-[r:SIMILAR_TO]->()
                RETURN count(r) AS total_edges,
                       min(r.score) AS min_score,
                       max(r.score) AS max_score,
                       avg(r.score) AS avg_score;
                """
            ).single()

            total_edges = edge_res["total_edges"]
            min_score = edge_res["min_score"]
            max_score = edge_res["max_score"]
            avg_score = edge_res["avg_score"]

            # 3. Vector index status
            index_status = "NOT_FOUND"
            idx_records = list(session.run("SHOW VECTOR INDEXES YIELD name, state, populationPercent;"))
            for r in idx_records:
                if r["name"] == INDEX_NAME:
                    index_status = f"{r['state']} ({r.get('populationPercent', 'N/A')}%)"
                    break

        print("=" * 65)
        print("Neo4j Course Embedding & Similarity Statistics")
        print("=" * 65)
        print(f"Total Course Nodes           : {total_courses:,}")
        print(f"Courses with Embedding        : {courses_with_emb:,} ({(courses_with_emb / total_courses * 100) if total_courses else 0:.1f}%)")
        print(f"Vector Index ({INDEX_NAME}) : {index_status}")
        print("-" * 65)
        print(f"Total [:SIMILAR_TO] Edges     : {total_edges:,}")
        if total_edges > 0:
            print(f"  - Min Similarity Score      : {min_score:.4f}")
            print(f"  - Max Similarity Score      : {max_score:.4f}")
            print(f"  - Avg Similarity Score      : {avg_score:.4f}")
        print("=" * 65)

        return {
            "total_courses": total_courses,
            "courses_with_embedding": courses_with_emb,
            "vector_index_status": index_status,
            "total_similarity_edges": total_edges,
            "avg_score": avg_score,
        }

    def show_similar_courses(self, identifier: str, limit: int = 10):
        """Show similar courses connected via [:SIMILAR_TO] for a given course."""
        with self.driver.session() as session:
            # Match course by syllabus_id or name
            course = session.run(
                """
                MATCH (c:Course)
                WHERE c.syllabus_id = $id OR c.name = $id OR c.course_code = $id
                RETURN c.syllabus_id AS id, c.name AS name, c.course_code AS code, c.credits AS credits
                LIMIT 1;
                """,
                {"id": identifier},
            ).single()

            if not course:
                print(f"[ERROR] Course not found with identifier: {identifier}")
                return

            print("=" * 65)
            print(f"Target Course: [{course['id']}] {course['name']} ({course['code']}, {course['credits']}単位)")
            print("=" * 65)

            # Retrieve outgoing [:SIMILAR_TO] edges
            similar_records = list(
                session.run(
                    """
                    MATCH (c:Course {syllabus_id: $id})-[r:SIMILAR_TO]->(target:Course)
                    RETURN target.syllabus_id AS id,
                           target.name AS name,
                           target.course_code AS code,
                           r.score AS score,
                           r.model AS model
                    ORDER BY r.score DESC
                    LIMIT $limit;
                    """,
                    {"id": course["id"], "limit": limit},
                )
            )

            if not similar_records:
                print("  No [:SIMILAR_TO] edges found for this course.")
            else:
                print(f"Top {len(similar_records)} Similar Courses ([:SIMILAR_TO]):")
                for rank, rec in enumerate(similar_records, start=1):
                    print(f"  {rank:2d}. [Score: {rec['score']:.4f}] [{rec['id']}] {rec['name']} ({rec['code']})")
            print("=" * 65)

    def test_vector_query(self, query_text: str, top_k: int = 5):
        """Execute dynamic vector query using Vector Index and Gemini Embedding."""
        # Convert query_text to embedding vector using official SDK
        vec = embed_text(query_text)

        with self.driver.session() as session:
            query = f"""
            CALL db.index.vector.queryNodes('{INDEX_NAME}', {top_k}, $vec)
            YIELD node, score
            RETURN node.syllabus_id AS id,
                   node.name AS name,
                   node.course_code AS code,
                   score
            ORDER BY score DESC;
            """
            results = list(session.run(query, {"vec": vec}))

        print("=" * 65)
        print(f"Vector Query Test: \"{query_text}\"")
        print(f"Target Index     : {INDEX_NAME} (top_k={top_k})")
        print("=" * 65)
        if not results:
            print("  No matches returned from Vector Index.")
        else:
            for rank, rec in enumerate(results, start=1):
                print(f"  {rank:2d}. [Score: {float(rec['score']):.4f}] [{rec['id']}] {rec['name']} ({rec['code']})")
        print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Verify Neo4j course embeddings and similarity edges")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: stats
    subparsers.add_parser("stats", help="Show global embedding and similarity edge statistics")

    # Subcommand: show-similar
    show_parser = subparsers.add_parser("show-similar", help="Show connected similar courses for a target course")
    show_parser.add_argument("identifier", type=str, help="syllabus_id, course_code, or exact course name")
    show_parser.add_argument("--limit", type=int, default=10, help="Max results to display")

    # Subcommand: test-query
    query_parser = subparsers.add_parser("test-query", help="Test dynamic vector query against Vector Index")
    query_parser.add_argument("query_text", type=str, help="Text query to search for")
    query_parser.add_argument("--top-k", type=int, default=5, help="Number of nearest courses to retrieve")

    args = parser.parse_args()

    with SimilarityVerifier() as verifier:
        if args.command == "stats":
            verifier.check_stats()
        elif args.command == "show-similar":
            verifier.show_similar_courses(args.identifier, limit=args.limit)
        elif args.command == "test-query":
            verifier.test_vector_query(args.query_text, top_k=args.top_k)


if __name__ == "__main__":
    main()
