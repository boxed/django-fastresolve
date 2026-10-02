from django.apps import AppConfig


class FastResolveConfig(AppConfig):
    name = 'django_fastresolve'
    verbose_name = 'django-fastresolve'

    def ready(self):
        from django_fastresolve import install

        install()
