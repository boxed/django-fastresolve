"""A urlconf full of edge cases. Every test resolves against it both the stock way and the fast way."""

from django.conf.urls.i18n import i18n_patterns
from django.urls import (
    include,
    path,
    re_path,
    register_converter,
)
from django.urls.resolvers import (
    ResolverMatch,
    RoutePattern,
    URLPattern,
)
from django.utils.translation import gettext_lazy


def make_view(name):
    def view(request, *args, **kwargs):
        pass  # pragma: no cover

    view.__name__ = view.__qualname__ = name
    return view


class EvenConverter:
    regex = '[0-9]+'

    def to_python(self, value):
        if int(value) % 2:
            raise ValueError()
        return int(value)

    def to_url(self, value):
        return str(value)  # pragma: no cover


register_converter(EvenConverter, 'even')


class MatchesEverythingEndingInWeird(URLPattern):
    """A subclass with its own resolve: its pattern says nothing about what it matches."""

    def resolve(self, path):
        if path.endswith('/weird/'):
            return ResolverMatch(self.callback, (), {}, 'weird', route=str(self.pattern), captured_kwargs={}, extra_kwargs={})


inner = [
    path('', make_view('inner_index'), name='inner_index'),
    path('detail/<int:pk>/', make_view('inner_detail'), name='inner_detail'),
    re_path(r'^re/(\d+)/$', make_view('inner_re_positional')),
]

urlpatterns = [
    path('', make_view('index'), name='index'),
    # The even converter raises ValueError on odd numbers, and the next pattern must get its turn
    path('even/<even:n>/', make_view('even')),
    path('even/<int:n>/', make_view('odd_fallback')),
    path('literal/', make_view('literal'), name='literal'),
    path('literal/', make_view('literal_shadowed')),
    path('lit', make_view('lit_no_slash')),
    path('literally/', make_view('literally')),
    path('<slug:slug>-offer-<int:pk>/', make_view('slug_offer')),
    path('files/<path:file_path>', make_view('files')),
    path('a<b/', make_view('angle_bracket_without_converter')),
    path('nested/', include(inner)),
    path('ns/', include((inner, 'app'), namespace='ns1')),
    path('ns2/<int:outer>/', include((inner, 'app'), namespace='ns2')),
    path('kw/', include(inner), {'extra': 1}),
    path('kwleaf/', make_view('kwleaf'), {'a': 1}),
    path('', include([path('emptyprefix/', make_view('emptyprefix'))])),
    path('deep/', include([path('a/', include([path('b/', include([path('<int:x>/', make_view('deep'))]))]))])),
    path('deep/a/', include([path('c/', make_view('deep_c'))])),
    re_path(r'^re-anchored/(?P<year>[0-9]{4})/$', make_view('re_named')),
    re_path(r'^re-pos/([0-9]+)/([a-z]+)/$', make_view('re_pos')),
    # Ends in $, so Django uses fullmatch: anchored after all
    re_path(r'unanchored/$', make_view('re_unanchored_fullmatch')),
    # Not anchored and no $: re.search finds this anywhere in the path
    re_path(r'anywhere/', make_view('re_anywhere')),
    re_path(r'^ab?c/$', make_view('re_quantifier')),
    re_path(r'^xy{2}z/$', make_view('re_brace_quantifier')),
    re_path(r'^alt/$|^other/$', make_view('re_alternation')),
    re_path(r'^esc\.dot/$', make_view('re_escaped')),
    re_path(r'^any.char/$', make_view('re_dot')),
    re_path(r'(?i)^case/$', make_view('re_case_insensitive')),
    re_path(r'^re-include/', include(inner)),
    path(gettext_lazy('translated/'), make_view('translated')),
    MatchesEverythingEndingInWeird(RoutePattern('nope/', is_endpoint=True), make_view('weird')),
    re_path(r'^', include([path('catchall-child/', make_view('catchall_child'))])),
]

urlpatterns += i18n_patterns(
    path('i18n/', make_view('i18n')),
    path('i18n/<int:pk>/', make_view('i18n_pk')),
)
