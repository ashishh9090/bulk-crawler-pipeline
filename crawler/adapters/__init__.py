"""Source adapters registry."""

from typing import Dict
from crawler.adapters.arxiv_papers import ArxivPapersAdapter
from crawler.adapters.base import BaseAdapter
from crawler.adapters.saashub_products import ProductsAdapter
from crawler.adapters.wikidata_startups import StartupsAdapter

_REGISTRY: Dict[str, BaseAdapter] = {
    "arxiv_papers": ArxivPapersAdapter(),
    "startups": StartupsAdapter(),
    "products": ProductsAdapter(),
}


def get_adapter(name: str) -> BaseAdapter:
    """Retrieves an adapter instance by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown adapter '{name}'. Available: {list(_REGISTRY.keys())}")
    return _REGISTRY[name]


def get_all_adapters() -> Dict[str, BaseAdapter]:
    """Returns dictionary of all registered adapters."""
    return _REGISTRY.copy()
