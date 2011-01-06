import math
import random
import os.path
import shutil
import string

from django.core.files.storage import FileSystemStorage

from nosedjango.plugins.base import Plugin

class TestFileSystemStorage(FileSystemStorage):
    """
    Filesystem storage that puts files in a special test folder that can
    be deleted before and after tests.
    """
    def __init__(self, location=None, base_url=None, *args, **kwargs):
        from django.conf import settings
        token = settings._TEST_FS_TOKEN

        location = os.path.join(settings.MEDIA_ROOT, token)
        base_url = os.path.join(settings.MEDIA_URL, '%s/' % token)
        return super(TestFileSystemStorage, self).__init__(location, base_url, *args, **kwargs)

class FileStoragePlugin(Plugin):
    """
    Set up a test file system so you're writing to a specific directory for your
    testing.
    """
    name = 'django-file-storage'

    def beforeTestSetup(self, settings):
        settings.DEFAULT_FILE_STORAGE = 'nosedjango.plugins.file_storage.TestFileSystemStorage'
        self.token = random_token()

        settings._TEST_FS_TOKEN = self.token


    def afterRollback(self, settings):
        self.clear_test_media()

    def clear_test_media(self):
        tfs = TestFileSystemStorage()
        try:
            shutil.rmtree(tfs.location)
        except OSError:
            pass

def random_token(bits=128):
    """
    Generates a random token, using the url-safe base64 alphabet.
    The "bits" argument specifies the bits of randomness to use.
    """
    alphabet = string.ascii_letters + string.digits + '-_'
    # alphabet length is 64, so each letter provides lg(64) = 6 bits
    num_letters = int(math.ceil(bits / 6.0))
    return ''.join(random.choice(alphabet) for i in range(num_letters))

