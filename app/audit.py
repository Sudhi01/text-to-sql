"""
Phase 2 - Audit Logger
Logs every query attempt (passed or blocked) for compliance.
Writes to audit.log in JSON Lines format — one record per line.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.config import AUDIT_LOG_PATH

# Also send to Python logger for console visibility
logger = logging.getLogger(__name__)


def log_query(
    question: str,
    sql: str,
    blocked: bool,
    reason: Optional[str] = None,
    execution_time: Optional[float] = None,
    row_count: Optional[int] = None,
    flags: Optional[list] = None,
):
    """
    Write one audit record to audit.log.

    Format (JSON Lines):
    {
        "timestamp": "2025-01-01T12:00:00Z",
        "question": "...",
        "sql": "...",
        "blocked": true|false,
        "blocked_reason": "..." | null,
        "execution_time": 0.012 | null,
        "row_count": 3 | null,
        "flags": [...] | null
    }
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": question,
        "sql": sql,
        "blocked": blocked,
        "blocked_reason": reason,
        "execution_time": execution_time,
        "row_count": row_count,
        "flags": flags or [],
    }

    # Write to audit log file
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError as e:
        logger.error("Failed to write audit log: %s", e)

    # Also log to console
    status = "BLOCKED" if blocked else "PASSED"
    logger.info("[AUDIT] %s | question=%r | reason=%s", status, question, reason or "none")