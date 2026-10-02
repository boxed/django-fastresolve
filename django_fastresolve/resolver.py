"""A faster drop-in for ``URLResolver.resolve``.

Django resolves a path by trying every child pattern of a resolver in order,
and recursing into includes. With hundreds of patterns at one level, that's
hundreds of regex searches or string compares per request.

This module indexes each resolver's children by their *literal prefix*: the
part of the pattern that must appear verbatim at the start of the path for the
pattern to have any chance of matching. A path then only needs to try the
children whose literal prefix it starts with, still in their original order.
Everything else (converters, ``ValueError`` from ``to_python`` falling through
to later patterns, namespaces, default kwargs) is Django's own code.

When the prefix of a child can't be determined safely, its prefix is the empty
string, meaning it is a candidate for every path. Correctness never depends on
the index being clever, only on it never excluding a pattern that could match.
"""

import string
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.urls.exceptions import Resolver404
from django.urls.resolvers import (
    RegexPattern,
    ResolverMatch,
    RoutePattern,
    URLPattern,
    URLResolver,
)

stock_resolve = URLResolver.resolve

_use_stock = ContextVar('django_fastresolve_use_stock', default=False)

# Characters that mean themselves when unescaped in a regex, outside a character class
_REGEX_LITERAL_CHARS = frozenset(string.ascii_letters + string.digits + '/-_~%=,;:@!&\'"<>')
_REGEX_QUANTIFIER_START = frozenset('?*+{')


@contextmanager
def stock_resolving():
    """Resolve with Django's own implementation inside this block, in this context only."""
    token = _use_stock.set(True)
    try:
        yield
    finally:
        _use_stock.reset(token)


def regex_literal_prefix(regex):
    """The literal text any match of `regex` (searched with `re.search`) must start with.

    Conservative: returns '' whenever the regex isn't plainly ``^literal...``.
    """
    if not isinstance(regex, str) or not regex.startswith('^') or '|' in regex:
        return ''

    prefix = []
    i = 1
    while i < len(regex):
        c = regex[i]
        if c in _REGEX_LITERAL_CHARS:
            literal, width = c, 1
        elif c == '\\' and i + 1 < len(regex) and not regex[i + 1].isalnum():
            literal, width = regex[i + 1], 2
        else:
            break

        i += width
        if i < len(regex) and regex[i] in _REGEX_QUANTIFIER_START:
            # The char we just read is optional or repeated, so it's not a fixed prefix
            break
        prefix.append(literal)

    return ''.join(prefix)


def literal_prefix(url_pattern):
    """The prefix a path must start with for `url_pattern` to possibly resolve it."""
    resolve_method = getattr(type(url_pattern), 'resolve', None)
    if resolve_method is not URLPattern.resolve and resolve_method is not fast_resolve:
        # A subclass with its own idea of matching, we can't reason about it
        return ''

    pattern = url_pattern.pattern
    if type(pattern) is RoutePattern:
        route = pattern._route
        if not isinstance(route, str):
            # Lazily translated, depends on the active language
            return ''
        # Cutting at any '<' is safe even when it doesn't start a converter: a shorter prefix only means more candidates
        index = route.find('<')
        return route if index == -1 else route[:index]

    if type(pattern) is RegexPattern:
        return regex_literal_prefix(pattern._regex)

    # LocalePrefixPattern, or a pattern type we don't know
    return ''


class Index:
    __slots__ = ('patterns', 'length', 'lengths_desc', 'candidates_by_prefix', 'is_root')

    def __init__(self, resolver, patterns):
        self.patterns = patterns
        self.length = len(patterns)
        self.is_root = type(resolver.pattern) is RegexPattern and resolver.pattern._regex == '^/'

        indexes_by_own_prefix = {}
        for i, url_pattern in enumerate(patterns):
            indexes_by_own_prefix.setdefault(literal_prefix(url_pattern), []).append(i)

        lengths = sorted({len(prefix) for prefix in indexes_by_own_prefix})

        # For every prefix, the candidates are its own patterns plus those of every
        # shorter prefix it starts with. Any path's candidates are then those of the
        # longest prefix it starts with. Shortest first, so parents are done before
        # their children.
        indexes_by_prefix = {}
        for prefix in sorted(indexes_by_own_prefix, key=len):
            inherited = ()
            for length in reversed(lengths):
                if length < len(prefix):
                    parent = indexes_by_prefix.get(prefix[:length])
                    if parent is not None:
                        inherited = parent
                        break
            indexes_by_prefix[prefix] = tuple(sorted({*inherited, *indexes_by_own_prefix[prefix]}))

        self.candidates_by_prefix = {prefix: tuple(patterns[i] for i in indexes) for prefix, indexes in indexes_by_prefix.items()}
        self.lengths_desc = tuple(reversed(lengths))

    def candidates(self, path):
        candidates_by_prefix = self.candidates_by_prefix
        path_length = len(path)
        for length in self.lengths_desc:
            if length <= path_length:
                candidates = candidates_by_prefix.get(path[:length])
                if candidates is not None:
                    return candidates
        return ()


def _get_index(resolver):
    patterns = resolver.url_patterns
    index = resolver.__dict__.get('_fastresolve_index')
    # The length check catches the common case of urlpatterns being appended to after the first resolve
    if index is None or index.patterns is not patterns or index.length != len(patterns):
        if not isinstance(patterns, (list, tuple)):
            return None
        index = Index(resolver, patterns)
        resolver._fastresolve_index = index
    return index


def fast_resolve(self, path):
    if _use_stock.get():
        return stock_resolve(self, path)

    path = str(path)  # path may be a reverse_lazy object
    match = self.pattern.match(path)
    if not match:
        raise Resolver404({'path': path})

    index = _get_index(self)
    if index is None:
        return stock_resolve(self, path)

    new_path, args, kwargs = match
    tried = []
    # From here on, this is Django's URLResolver.resolve, only looping over the candidates instead of all patterns
    for pattern in index.candidates(new_path):
        try:
            sub_match = pattern.resolve(new_path)
        except Resolver404 as e:
            self._extend_tried(tried, pattern, e.args[0].get('tried'))
        else:
            if sub_match:
                # Merge captured arguments in match with submatch
                sub_match_dict = {**kwargs, **self.default_kwargs}
                # Update the sub_match_dict with the kwargs from the sub_match.
                sub_match_dict.update(sub_match.kwargs)
                # If there are *any* named groups, ignore all non-named
                # groups. Otherwise, pass all non-named arguments as
                # positional arguments.
                sub_match_args = sub_match.args
                if not sub_match_dict:
                    sub_match_args = args + sub_match.args
                current_route = '' if isinstance(pattern, URLPattern) else str(pattern.pattern)
                self._extend_tried(tried, pattern, sub_match.tried)
                return ResolverMatch(
                    sub_match.func,
                    sub_match_args,
                    sub_match_dict,
                    sub_match.url_name,
                    [self.app_name, *sub_match.app_names],
                    [self.namespace, *sub_match.namespaces],
                    self._join_route(current_route, sub_match.route),
                    tried,
                    captured_kwargs=sub_match.captured_kwargs,
                    extra_kwargs={
                        **self.default_kwargs,
                        **sub_match.extra_kwargs,
                    },
                )
            tried.append([pattern])

    if index.is_root and settings.DEBUG:
        _check_stock_404(self, path)

    raise Resolver404({'tried': tried, 'path': new_path})


def _check_stock_404(resolver, path):
    """In DEBUG, redo a 404 the stock way.

    The 404 debug page then lists every pattern instead of only the candidates,
    and if stock Django does find a match, that's a bug in this library and we
    say so loudly instead of serving a wrong 404.
    """
    with stock_resolving():
        match = stock_resolve(resolver, path)
    raise AssertionError(f'django-fastresolve bug: {path!r} resolved to {match._func_path} with stock Django, but not with django-fastresolve. Please report this at https://github.com/boxed/django-fastresolve/issues')


def install():
    URLResolver.resolve = fast_resolve


def uninstall():
    URLResolver.resolve = stock_resolve
