"""Initialise the database schema.

Usage (from the repository root):

    python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.database.session import init_db  # noqa: E402
from app.logging_config import configure_logging, get_logger  # noqa: E402


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    logger = get_logger("scripts.init_db")
    init_db()
    logger.info("Database initialised at %s", settings.database_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
