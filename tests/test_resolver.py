import random
import re
from types import SimpleNamespace

import pytest
from django.test import override_settings
from django.urls import (
    Resolver404,
    clear_url_caches,
    get_resolver,
    path,
)
from django.urls.resolvers import (
    RegexPattern,
    URLResolver,
)
from django.utils import translation

from django_fastresolve import stock_resolving
from django_fastresolve.resolver import (
    fast_resolve,
    install,
    literal_prefix,
    regex_literal_prefix,
    stock_resolve,
    uninstall,
)
from tests import urls
from tests.urls import make_view

SAMPLE_BY_CONVERTER = {
    'int': ['0', '7', '12'],
    'even': ['4', '5'],
    'str': ['abc', 'a-b'],
    'slug': ['some-slug'],
    'path': ['x/y.txt', 'x'],
}

FIXED_PATHS = [
    '/',
    '',
    'no-leading-slash/',
    '/even/4/',
    '/even/5/',
    '/even/x/',
    '/literal/',
    '/literal',
    '/literal/x/',
    '/lit',
    '/lit/',
    '/literally/',
    '/foo-offer-12/',
    '/foo-bar-offer-12/',
    '/-offer-12/',
    '/files/a/b/c.txt',
    '/files/',
    '/a<b/',
    '/nested/',
    '/nested/detail/3/',
    '/nested/re/12/',
    '/ns/detail/3/',
    '/ns2/5/detail/3/',
    '/ns2/5/',
    '/kw/',
    '/kw/detail/9/',
    '/kwleaf/',
    '/emptyprefix/',
    '/deep/a/b/4/',
    '/deep/a/c/',
    '/deep/a/b/x/',
    '/re-anchored/2026/',
    '/re-anchored/26/',
    '/re-pos/12/abc/',
    '/unanchored/',
    '/foo/bar/unanchored/',
    '/anywhere/',
    '/foo/bar/anywhere/baz',
    '/abc/',
    '/ac/',
    '/abbc/',
    '/xyyz/',
    '/xyz/',
    '/alt/',
    '/other/',
    '/esc.dot/',
    '/escxdot/',
    '/anyxchar/',
    '/any.char/',
    '/case/',
    '/CASE/',
    '/re-include/detail/1/',
    '/re-pos-include/7/re/12/',
    '/translated/',
    '/nope/',
    '/something/weird/',
    '/catchall-child/',
    '/en/i18n/',
    '/sv/i18n/',
    '/en/i18n/3/',
    '/i18n/',
    '/does/not/exist/',
]

MATCH_FIELDS = ['func', 'args', 'kwargs', 'url_name', 'app_names', 'namespaces', 'route', 'captured_kwargs', 'extra_kwargs', 'view_name', '_func_path']


def outcome(path_to_resolve, resolve):
    try:
        match = resolve(path_to_resolve)
    except Resolver404 as e:
        return ('404', e.args[0].get('path'))
    return tuple(getattr(match, field) for field in MATCH_FIELDS)


def fast(path_to_resolve):
    return get_resolver().resolve(path_to_resolve)


def stock(path_to_resolve):
    with stock_resolving():
        return get_resolver().resolve(path_to_resolve)


def assert_same(path_to_resolve):
    assert outcome(path_to_resolve, fast) == outcome(path_to_resolve, stock), path_to_resolve


def test_installed_by_the_app_config():
    assert URLResolver.resolve is fast_resolve


@pytest.mark.parametrize('language', ['en', 'sv'])
@pytest.mark.parametrize('path_to_resolve', FIXED_PATHS)
def test_same_as_stock(path_to_resolve, language):
    with translation.override(language):
        assert_same(path_to_resolve)


def test_fixed_paths_cover_matches_and_misses():
    outcomes = [outcome(p, fast) for p in FIXED_PATHS]
    assert sum(o[0] == '404' for o in outcomes) >= 10
    assert len({o[0] for o in outcomes if o[0] != '404'}) >= 30


def test_converter_value_error_falls_through_to_the_next_pattern():
    assert fast('/even/4/').func.__name__ == 'even'
    assert fast('/even/5/').func.__name__ == 'odd_fallback'


def test_unanchored_regex_matches_anywhere():
    assert fast('/foo/bar/anywhere/baz').func.__name__ == 're_anywhere'
    assert fast('/unanchored/').func.__name__ == 're_unanchored_fullmatch'
    with pytest.raises(Resolver404):
        fast('/foo/bar/unanchored/')


def test_pattern_subclass_with_own_resolve_is_always_tried():
    assert fast('/something/weird/').func.__name__ == 'weird'


def leaf_samples(patterns, prefix=''):
    """Concrete paths for every leaf route, built from its route string."""
    param_re = re.compile(r'<(?:(?P<converter>[^>:]+):)?(?P<name>[^>]+)>')
    for p in patterns:
        route = str(p.pattern)
        if hasattr(p.pattern, '_route'):
            parts = ['']
            last = 0
            for m in param_re.finditer(route):
                parts = [x + route[last : m.start()] + sample for x in parts for sample in SAMPLE_BY_CONVERTER[m['converter'] or 'str']]
                last = m.end()
            parts = [x + route[last:] for x in parts]
        else:
            parts = [re.sub(r'[\^$\\]', '', route)]
        for part in parts:
            if isinstance(p, URLResolver):
                yield from leaf_samples(p.url_patterns, prefix + part)
            else:
                yield prefix + part


def test_fuzz():
    rng = random.Random(1337)
    samples = sorted(set(leaf_samples(urls.urlpatterns)))
    fragments = sorted({fragment for sample in samples for fragment in re.split('(/)', sample) if fragment}) + ['', 'x', '-', '.', 'en', 'sv']
    paths = set()
    for sample in samples:
        paths.add('/' + sample)
        for cut in range(len(sample)):
            paths.add('/' + sample[:cut])
            paths.add('/' + sample[:cut] + 'x' + sample[cut:])
        paths.add('/' + sample + 'x')
        paths.add('/' + sample + 'x/')
    for _ in range(3000):
        paths.add('/' + ''.join(rng.choice(fragments) for _ in range(rng.randint(1, 8))))

    for p in sorted(paths):
        for language in ['en', 'sv']:
            with translation.override(language):
                assert_same(p)


def test_appending_to_urlpatterns_after_first_resolve():
    with pytest.raises(Resolver404):
        fast('/appended/')
    urls.urlpatterns.append(path('appended/', make_view('appended')))
    try:
        assert fast('/appended/').func.__name__ == 'appended'
    finally:
        urls.urlpatterns.pop()
        clear_url_caches()


@override_settings(DEBUG=True)
def test_debug_404_has_the_full_tried_list():
    with pytest.raises(Resolver404) as fast_404:
        fast('/does/not/exist/')
    with pytest.raises(Resolver404) as stock_404:
        stock('/does/not/exist/')
    assert len(fast_404.value.args[0]['tried']) == len(stock_404.value.args[0]['tried'])
    assert len(fast_404.value.args[0]['tried']) > 30


@override_settings(DEBUG=True)
def test_debug_404_that_stock_django_resolves_is_reported_as_a_bug(monkeypatch):
    from django_fastresolve import resolver

    monkeypatch.setattr(resolver.Index, 'candidates', lambda self, path: ())
    clear_url_caches()
    with pytest.raises(AssertionError, match='django-fastresolve bug'):
        fast('/literal/')
    clear_url_caches()


def test_tried_on_404_without_debug_only_has_candidates():
    with pytest.raises(Resolver404) as e:
        fast('/does/not/exist/')
    assert len(e.value.args[0]['tried']) < 15


@pytest.mark.parametrize(
    'regex, expected',
    [
        (r'^foo/$', 'foo/'),
        (r'^foo/(?P<x>\d+)/$', 'foo/'),
        (r'foo/$', ''),
        (r'^ab?c/', 'a'),
        (r'^ab*c/', 'a'),
        (r'^ab+c/', 'a'),
        (r'^xy{2}z/', 'x'),
        (r'^esc\.dot/', 'esc.dot/'),
        (r'^esc\.?dot/', 'esc'),
        (r'^\d+/', ''),
        (r'^a.b/', 'a'),
        (r'^a[bc]/', 'a'),
        (r'^a|b', ''),
        (r'(?i)^case/', ''),
        (r'^', ''),
        (r'^/', '/'),
        (r'^a(b)/', 'a'),
        (r'^a$', 'a'),
    ],
)
def test_regex_literal_prefix(regex, expected):
    assert regex_literal_prefix(regex) == expected


@pytest.mark.parametrize(
    'regex, expected',
    [
        (r'^esc\.', 'esc.'),
        ('^a\\', 'a'),
    ],
)
def test_regex_literal_prefix_escape_at_end(regex, expected):
    assert regex_literal_prefix(regex) == expected


@pytest.mark.parametrize(
    'route, expected',
    [
        ('literal/', 'literal/'),
        ('a<int:x>/', 'a'),
        ('foo/<int:x>/', 'foo/'),
        ('<int:x>/', ''),
    ],
)
def test_literal_prefix_of_route(route, expected):
    assert literal_prefix(path(route, make_view('v'))) == expected


def is_subsequence(needle, haystack):
    it = iter(haystack)
    return all(any(x == y for y in it) for x in needle)


def tried_routes(tried):
    return [[str(p.pattern) for p in entry] for entry in tried]


@pytest.mark.parametrize('path_to_resolve', ['/nested/nope/', '/deep/a/b/x/', '/ns2/5/nope/'])
def test_tried_on_404_is_a_subsequence_of_stock(path_to_resolve):
    with pytest.raises(Resolver404) as fast_404:
        fast(path_to_resolve)
    with pytest.raises(Resolver404) as stock_404:
        stock(path_to_resolve)
    fast_tried = tried_routes(fast_404.value.args[0]['tried'])
    assert any(len(entry) > 1 for entry in fast_tried)
    assert is_subsequence(fast_tried, tried_routes(stock_404.value.args[0]['tried']))


@pytest.mark.parametrize('path_to_resolve', ['/literal/', '/nested/detail/3/', '/deep/a/b/4/', '/even/5/'])
def test_tried_on_match_is_a_subsequence_of_stock(path_to_resolve):
    fast_tried = tried_routes(fast(path_to_resolve).tried)
    stock_tried = tried_routes(stock(path_to_resolve).tried)
    assert fast_tried[-1] == stock_tried[-1]
    assert is_subsequence(fast_tried, stock_tried)


def test_index_is_reused_and_rebuilt_when_patterns_are_replaced():
    resolver = get_resolver()
    fast('/literal/')
    index = resolver._fastresolve_index
    fast('/literal/')
    assert resolver._fastresolve_index is index

    resolver.url_patterns = [*resolver.url_patterns[:-1], path('replaced/', make_view('replaced'))]
    try:
        assert fast('/replaced/').func.__name__ == 'replaced'
        assert resolver._fastresolve_index is not index
    finally:
        clear_url_caches()


class PatternSequence:
    """url patterns that are iterable, but neither a list nor a tuple."""

    def __init__(self, patterns):
        self.patterns = patterns

    def __iter__(self):
        return iter(self.patterns)


def test_patterns_that_are_not_a_list_fall_back_to_stock():
    resolver = URLResolver(RegexPattern(r'^/'), SimpleNamespace(urlpatterns=PatternSequence([path('x/', make_view('x'))])))
    assert resolver.resolve('/x/').func.__name__ == 'x'
    with pytest.raises(Resolver404):
        resolver.resolve('/y/')


def test_uninstall_and_install():
    uninstall()
    try:
        assert URLResolver.resolve is stock_resolve
    finally:
        install()
    assert URLResolver.resolve is fast_resolve
