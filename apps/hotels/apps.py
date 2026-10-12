from django.apps import AppConfig


class HotelsConfig(AppConfig):
    name = 'hotels'

    def ready(self):
        from . import checks  # noqa: F401
