from django.apps import AppConfig


class AnimateursConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'animateurs'

    def ready(self):
        from . import signals  # noqa: F401
