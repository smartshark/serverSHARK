from django.apps import AppConfig


class ServersharkConfig(AppConfig):
    name = 'smartshark'
    verbose_name = 'SmartSHARK'

    def ready(self):
        import smartshark.signals.handlers
