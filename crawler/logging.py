"""Structured JSON logging configuration for production monitoring."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict
from crawler.config import settings


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects with standard fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include standard context if present
        for attr in ("worker_id", "url", "status_code", "latency_ms", "record_type", "domain"):
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(level: str | None = None, log_format: str | None = None) -> logging.Logger:
    """Configures the root logger and returns the application logger."""
    selected_level = getattr(logging, (level or settings.log_level).upper(), logging.INFO)
    selected_format = (log_format or settings.log_format).lower()

    root = logging.getLogger()
    root.setLevel(selected_level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(selected_level)

    if selected_format == "json":
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")
        )

    root.addHandler(handler)

    # Silence overly verbose external libraries
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return logging.getLogger("crawler")


logger = setup_logging()
