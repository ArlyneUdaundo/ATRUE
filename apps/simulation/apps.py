from django.apps import AppConfig


class SimulationConfig(AppConfig):
    name = 'simulation'

    def ready(self):
        # Registers the role/catalogue consistency checks in simulation/checks.py.
        from . import checks  # noqa: F401