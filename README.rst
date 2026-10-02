django-fastresolve
==================

Faster URL resolving for Django, as a drop-in. No changes to your urlconfs.

Django resolves a path by trying every pattern of a urlconf in order, recursing
into includes. With a few hundred patterns at one level, every request pays for
a few hundred regex searches or string compares, and a 404 pays for all of them.

django-fastresolve indexes the patterns of each resolver on their *literal
prefix*: the text a path must start with for the pattern to have any chance of
matching (``'projects/'`` for ``path('projects/<int:pk>/', ...)``, ``'blog/'``
for ``re_path(r'^blog/(?P<slug>\w+)/$', ...)``). A path then only tries the
patterns whose prefix it starts with, still in their original order. All the
matching itself is still Django's own code: converters, a ``to_python`` raising
``ValueError`` falling through to later patterns, namespaces, default kwargs.


Installation
------------

.. code-block::

    pip install django-fastresolve

and add ``'django_fastresolve'`` to ``INSTALLED_APPS``. That's it.

You can also call ``django_fastresolve.install()`` and
``django_fastresolve.uninstall()`` yourself.


How much faster?
----------------

On a real project with three urlconfs, timing ``resolve()`` on every route,
with ``DEBUG = False``:

=====================  ======  ============  ==============  ==========  ==========
urlconf                routes  stock median  fast median     stock 404   fast 404
=====================  ======  ============  ==============  ==========  ==========
internal app           785     25 µs         6 µs            27 µs       2 µs
public site            894     64 µs         4.6 µs          125 µs      4.8 µs
small                  83      8 µs          7 µs            6 µs        3 µs
=====================  ======  ============  ==============  ==========  ==========

The more patterns share a level, the bigger the win. Patterns that stock Django
already finds in the first couple of tries get about 1 µs slower, from the
index lookup.


When does it fall back?
-----------------------

A pattern whose prefix can't be determined safely gets the empty prefix, which
means it is tried for every path, exactly where stock Django would try it. That
is the case for:

- lazily translated routes (``path(gettext_lazy('about/'), ...)``)
- regexes that aren't anchored with ``^``, or that contain ``|``
- ``i18n_patterns`` (``LocalePrefixPattern``)
- ``URLPattern``/``URLResolver`` subclasses that override ``resolve()``
- pattern classes it doesn't know

Only the leading literal part of a regex counts: ``r'^ab?c/'`` has the prefix
``'a'``.


Differences from stock Django
-----------------------------

``tried`` (on ``Resolver404`` and on ``ResolverMatch.tried``) only lists the
patterns that were actually tried, not every pattern before the match.

With ``DEBUG = True`` a 404 is resolved again the stock way, so the 404 debug
page lists every pattern as usual. That also acts as a self check: if stock
Django finds a match where django-fastresolve didn't, you get an
``AssertionError`` saying so, instead of a wrong 404. Please report it if that
happens.

The index for a resolver is built on first use. If you append to or remove from
``urlpatterns`` afterwards the index is rebuilt; replacing an item in place is
not noticed.

To resolve the stock way for a block of code, in the current context only:

.. code-block:: python

    from django_fastresolve import stock_resolving

    with stock_resolving():
        match = resolve('/some/path/')


Running the tests
-----------------

.. code-block::

    uv run pytest

The tests resolve a urlconf full of edge cases, plus a few thousand fuzzed
paths, both ways, and assert identical results.
