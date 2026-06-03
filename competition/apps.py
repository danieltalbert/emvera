"""AppConfig for the competition app."""

from django.apps import AppConfig


class CompetitionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'competition'
    verbose_name = 'Investment Competitions'
