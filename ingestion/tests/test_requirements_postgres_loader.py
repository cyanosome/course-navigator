"""
Unit tests for PostgreSQL Requirements Loader and Verifier.
"""

import pytest
from pathlib import Path
from src.loaders.postgres.db import get_connection
from src.loaders.postgres.loader_requirements import PostgresRequirementsLoader
from src.loaders.postgres.verify_requirements import get_requirements_stats, verify_all


def test_postgres_requirements_loader():
    """Verify loading requirements into PostgreSQL with dry-run and commit."""
    conn = get_connection()
    loader = PostgresRequirementsLoader(conn=conn)

    json_path = Path("data/parsed/university/kansai/2026/bulletin_cee_requirements.json")
    if not json_path.exists():
        pytest.skip("Requirements JSON not found.")

    try:
        # Test dry-run
        dry_stats = loader.load_requirements(json_path=json_path, dry_run=True)
        assert dry_stats["dry_run"] is True
        assert dry_stats["graduation_requirement_id"] == "2026_env_cee"

        # Test live load
        live_stats = loader.load_requirements(json_path=json_path, dry_run=False)
        assert live_stats["dry_run"] is False
        assert live_stats["course_requirements_inserted"] > 0

        # Verify through verifier
        stats = get_requirements_stats(conn)
        assert len(stats["graduation_requirements"]) >= 1
        assert len(stats["requirement_types"]) >= 2
        assert verify_all(conn) is True
    finally:
        loader.close()
