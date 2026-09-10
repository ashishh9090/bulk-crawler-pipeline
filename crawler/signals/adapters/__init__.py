"""Adapter factory and registry for Phase II signal sources."""

from typing import Dict, Type
from crawler.signals.adapters.api_adapter import APISignalAdapter
from crawler.signals.adapters.base import BaseSignalAdapter
from crawler.signals.adapters.html_adapter import HTMLSignalAdapter
from crawler.signals.adapters.rss_adapter import RSSSignalAdapter
from crawler.signals.config import SourceConfig

ADAPTER_MAP: Dict[str, Type[BaseSignalAdapter]] = {
    "rss": RSSSignalAdapter,
    "atom": RSSSignalAdapter,
    "api": APISignalAdapter,
    "html_listing": HTMLSignalAdapter,
}


def get_signal_adapter(config: SourceConfig) -> BaseSignalAdapter:
    """Creates and returns the appropriate adapter instance for a source configuration."""
    adapter_cls = ADAPTER_MAP.get(config.adapter_type)
    if not adapter_cls:
        raise ValueError(
            f"Unsupported adapter_type '{config.adapter_type}' for source '{config.id}'. "
            f"Available types: {list(ADAPTER_MAP.keys())}"
        )
    return adapter_cls(config)
