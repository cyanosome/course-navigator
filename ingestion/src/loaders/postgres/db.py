"""
Database connection management for PostgreSQL loaders and verification tools.
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import psycopg
from psycopg.rows import dict_row

# Potential .env locations
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_LOCATIONS = [
    PROJECT_ROOT / "db" / ".env",
    PROJECT_ROOT / ".env",
]


def load_env_file_vars() -> Dict[str, str]:
    """Load key-value pairs from .env files without external dependencies."""
    vars_found: Dict[str, str] = {}
    for env_path in ENV_LOCATIONS:
        if env_path.exists():
            try:
                # Support cp932/utf-8 on Windows
                content = env_path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        vars_found[k.strip()] = v.strip().strip("'\"")
            except Exception:
                pass
    return vars_found


def get_db_config(
    host: Optional[str] = None,
    port: Optional[int] = None,
    dbname: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve database connection configuration.

    Resolution order:
    1. Explicit arguments
    2. Environment variables (DB_*, POSTGRES_*)
    3. .env files in db/.env or .env
    4. Fallback defaults (127.0.0.1:5432, admin, coursenavigator)
    """
    file_vars = load_env_file_vars()

    resolved_host = (
        host
        or os.getenv("DB_HOST")
        or file_vars.get("DB_HOST")
        or "127.0.0.1"
    )
    # If host is 'postgres' (container name), default to 127.0.0.1 when running on host
    if resolved_host == "postgres" and not os.path.exists("/.dockerenv"):
        resolved_host = "127.0.0.1"

    resolved_port = int(
        port
        or os.getenv("DB_PORT")
        or file_vars.get("DB_PORT")
        or 5432
    )

    resolved_dbname = (
        dbname
        or os.getenv("DB_NAME")
        or os.getenv("POSTGRES_DB")
        or file_vars.get("DB_NAME")
        or file_vars.get("POSTGRES_DB")
        or "coursenavigator"
    )

    resolved_user = (
        user
        or os.getenv("DB_USER")
        or os.getenv("POSTGRES_USER")
        or file_vars.get("DB_USER")
        or file_vars.get("POSTGRES_USER")
        or "admin"
    )

    resolved_password = (
        password
        or os.getenv("DB_PASSWORD")
        or os.getenv("POSTGRES_PASSWORD")
        or file_vars.get("DB_PASSWORD")
        or file_vars.get("POSTGRES_PASSWORD")
        or "secure_password_please_change"
    )

    return {
        "host": resolved_host,
        "port": resolved_port,
        "dbname": resolved_dbname,
        "user": resolved_user,
        "password": resolved_password,
    }


def get_connection(
    config: Optional[Dict[str, Any]] = None,
    row_factory=dict_row,
) -> psycopg.Connection:
    """Create and return a new psycopg connection with dictionary rows by default."""
    cfg = config or get_db_config()
    return psycopg.connect(
        host=cfg["host"],
        port=cfg["port"],
        dbname=cfg["dbname"],
        user=cfg["user"],
        password=cfg["password"],
        row_factory=row_factory,
    )
