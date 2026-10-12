from django.apps import AppConfig


class EstablishmentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'establishments'
    verbose_name = 'Establishments'

    def ready(self):
        from . import signals  # noqa: F401