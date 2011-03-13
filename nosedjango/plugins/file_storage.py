import os.path
import shutil

from nosedjango.plugins.base import Plugin

class FileStoragePlugin(Plugin):
    """
    Set up a test file system so you're writing to a specific directory for your
    testing.
    """
    name = 'django-testfs'

    def afterTestSetup(self, settings):
        settings.DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
        from django.core.files.storage import default_storage

        token = self.get_unique_token()
        default_storage.location = os.path.join(settings.MEDIA_ROOT, token)
        default_storage.base_url = os.path.join(settings.MEDIA_URL, '%s/' % token)

    def afterRollback(self, settings):
        self.clear_test_media()

    def clear_test_media(self):
        from django.core.files.storage import default_storage
        try:
            shutil.rmtree(default_storage.location)
        except OSError:
            pass
