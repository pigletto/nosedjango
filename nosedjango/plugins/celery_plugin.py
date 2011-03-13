from nosedjango.plugins.base import Plugin

class CeleryPlugin(Plugin):
    """
    Set up a test file system so you're writing to a specific directory for your
    testing.
    """
    name = 'django-celery'

    def beforeTestSetup(self, settings):
        settings.CELERY_ALWAYS_EAGER = True
        settings.CELERY_RESULTS_BACKEND = 'database'
