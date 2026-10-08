"""
Neo4j Graph Loader

Loads parsed course summary JSON records into Neo4j in batches,
creating Course, Professor, and Department nodes along with
TAUGHT_BY and BELONGS_TO relationships.
"""

import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase, Driver, Session

from src.graph.schema import CONSTRAINTS, BATCH_INGEST_QUERY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Base directory paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARSED_FILE = (
    BASE_DIR
    / "data"
    / "parsed"
    / "university"
    / "komazawa"
    / "2026"
    / "courses_summary.json"
)


def get_driver(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Driver:
    """Create a Neo4j driver using environment variables or passed parameters."""
    uri = uri or os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = user or os.getenv("NEO4J_USER", "neo4j")
    password = password or os.getenv("NEO4J_PASSWORD", "secure_password_please_change")

    logger.info("Initializing Neo4j driver for %s as user %s", uri, user)
    return GraphDatabase.driver(uri, auth=(user, password))


def ensure_constraints(session: Session) -> None:
    """Apply required unique constraints to the Neo4j database."""
    logger.info("Applying Neo4j constraints...")
    for query in CONSTRAINTS:
        logger.debug("Executing constraint query: %s", query)
        session.run(query).consume()
    logger.info("All constraints verified/created.")


def load_courses_batch(session: Session, batch: List[Dict[str, Any]]) -> None:
    """Load a batch of course records using UNWIND Cypher query."""
    if not batch:
        return
    result = session.run(BATCH_INGEST_QUERY, batch=batch)
    result.consume()


def load_from_file(
    file_path: Path,
    driver: Driver,
    batch_size: int = 1000,
) -> Dict[str, Any]:
    """Load courses from JSON file into Neo4j in batches.

    Args:
        file_path: Path to courses_summary.json.
        driver: Neo4j Driver instance.
        batch_size: Number of records per Cypher transaction.

    Returns:
        Summary dict of the load operation.
    """
    logger.info("Loading courses from file: %s", file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    start_time = time.time()
    with open(file_path, "r", encoding="utf-8") as f:
        courses: List[Dict[str, Any]] = json.load(f)

    total_records = len(courses)
    logger.info("Total records to ingest: %d (Batch size: %d)", total_records, batch_size)

    with driver.session() as session:
        # 1. Ensure constraints before ingesting
        ensure_constraints(session)

        # 2. Batch ingestion
        batches_processed = 0
        records_processed = 0

        for i in range(0, total_records, batch_size):
            batch = courses[i : i + batch_size]
            load_courses_batch(session, batch)
            batches_processed += 1
            records_processed += len(batch)
            logger.info(
                "Ingested batch %d/%d (%d/%d records)",
                batches_processed,
                (total_records + batch_size - 1) // batch_size,
                records_processed,
                total_records,
            )

    elapsed_seconds = time.time() - start_time
    summary = {
        "total_records": total_records,
        "records_processed": records_processed,
        "batches_processed": batches_processed,
        "elapsed_seconds": round(elapsed_seconds, 2),
    }
    logger.info("Ingestion completed successfully: %s", summary)
    return summary


def main() -> None:
    """CLI entrypoint for graph loader."""
    input_file = DEFAULT_PARSED_FILE
    batch_size = 1000

    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        input_file = Path(sys.argv[1])
    if len(sys.argv) > 2 and not sys.argv[2].startswith("-"):
        try:
            batch_size = int(sys.argv[2])
        except ValueError:
            pass

    driver = get_driver()
    try:
        driver.verify_connectivity()
        summary = load_from_file(input_file, driver=driver, batch_size=batch_size)
        logger.info("Summary: %s", summary)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
