import pytest
from django.urls import clear_url_caches, get_resolver
from django.urls.resolvers import URLResolver


def _drop_indexes(resolver):
    resolver.__dict__.pop('_fastresolve_index', None)
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            _drop_indexes(pattern)


@pytest.fixture(autouse=True)
def fresh_index():
    """Build indexes inside each test, so every test that depends on them exercises the indexing code."""
    _drop_indexes(get_resolver())
    clear_url_caches()
