"""
nose plugin for easy testing of django projects and apps. Sets up a test
database (or schema) and installs apps from test settings file before tests
are run, and tears the test database (or schema) down after all tests are run.
"""

from __future__ import with_statement

import logging
import os, sys, shutil
import re
import subprocess
import signal
import tempfile
import math, string, random
import socket
import time
import urllib2
import httplib

from time import sleep

from nose.plugins import Plugin
from nose.plugins.skip import SkipTest
import nose.case

from selenium.firefox.webdriver import WebDriver as FirefoxWebDriver
from selenium.chrome.webdriver import WebDriver as ChromeDriver
from selenium.remote.webdriver import WebDriver as RemoteDriver
from selenium.common.exceptions import (
    ErrorInResponseException,
    WebDriverException,
)

from django.core.files.storage import FileSystemStorage
from django.core.handlers.wsgi import WSGIHandler
from django.core.servers.basehttp import  AdminMediaHandler

# Force settings.py pointer
# search the current working directory and all parent directories to find
# the settings file
from nose.importer import add_path
if not 'DJANGO_SETTINGS_MODULE' in os.environ:
    os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from django.core.management import setup_environ

DEFAULT_LIVE_SERVER_ADDRESS = '0.0.0.0'
DEFAULT_LIVE_SERVER_PORT = '8000'

NT_ROOT = re.compile(r"^[a-zA-Z]:\\$")
def get_settings_path(settings_module):
    '''
    Hunt down the settings.py module by going up the FS path
    '''
    cwd = os.getcwd()
    settings_filename = '%s.py' % (
        settings_module.split('.')[-1]
    )
    while cwd:
        if settings_filename in os.listdir(cwd):
            break
        cwd = os.path.split(cwd)[0]
        if os.name == 'nt' and NT_ROOT.match(cwd):
            return None
        elif cwd == '/':
            return None
    return cwd

def _dummy(*args, **kwargs):
    """Dummy function that replaces the transaction functions"""
    return


class NoseDjango(Plugin):
    """
    Enable to set up django test environment before running all tests, and
    tear it down after all tests.

    Note that your django project must be on PYTHONPATH for the settings file
    to be loaded. The plugin will help out by placing the nose working dir
    into sys.path if it isn't already there, unless the -P
    (--no-path-adjustment) argument is set.
    """
    name = 'django'

    def disable_transaction_support(self, transaction):
        self.orig_commit = transaction.commit
        self.orig_rollback = transaction.rollback
        self.orig_savepoint_commit = transaction.savepoint_commit
        self.orig_savepoint_rollback = transaction.savepoint_rollback
        self.orig_enter = transaction.enter_transaction_management
        self.orig_leave = transaction.leave_transaction_management

        transaction.commit = _dummy
        transaction.rollback = _dummy
        transaction.savepoint_commit = _dummy
        transaction.savepoint_rollback = _dummy
        transaction.enter_transaction_management = _dummy
        transaction.leave_transaction_management = _dummy

    def restore_transaction_support(self, transaction):
        transaction.commit = self.orig_commit
        transaction.rollback = self.orig_rollback
        transaction.savepoint_commit = self.orig_savepoint_commit
        transaction.savepoint_rollback = self.orig_savepoint_rollback
        transaction.enter_transaction_management = self.orig_enter
        transaction.leave_transaction_management = self.orig_leave

    def options(self, parser, env):
        parser.add_option('--django-settings',
                          help='Use custom Django settings module.',
                          metavar='SETTINGS',
                          )
        parser.add_option('--django-sqlite',
                          help='Use in-memory sqlite for the tests',
                          dest='use_sqlite', action="store_true",
                          default=False
                          )
        parser.add_option('--django-testfs',
                          help='Use a local isolated test filestyem',
                          dest='use_testfs', action="store_true",
                          default=False
                          )
        super(NoseDjango, self).options(parser, env)

    def configure(self, options, conf):
        self.verbosity = conf.verbosity
        if options.django_settings:
            self.settings_module = options.django_settings
        elif 'DJANGO_SETTINGS_MODULE' in os.environ:
            self.settings_module = os.environ['DJANGO_SETTINGS_MODULE']
        else:
            self.settings_module = 'settings'

        self._use_sqlite = options.use_sqlite
        self._use_testfs = options.use_testfs

        super(NoseDjango, self).configure(options, conf)

    def begin(self):
        """
        Create the test database and schema, if needed, and switch the
        connection over to that database. Then call install() to install
        all apps listed in the loaded settings module.
        """
        os.environ['DJANGO_SETTINGS_MODULE'] = self.settings_module

        if self.conf.addPaths:
            map(add_path, self.conf.where)

        try:
            __import__(self.settings_module)
            self.settings_path = self.settings_module
        except ImportError:
            # Settings module is not found in PYTHONPATH. Try to do
            # some funky backwards crawling in directory tree, ie. add
            # the working directory (and any package parents) to
            # sys.path before trying to import django modules;
            # otherwise, they won't be able to find project.settings
            # if the working dir is project/ or project/..

            self.settings_path = get_settings_path(self.settings_module)

            if not self.settings_path:
                # short circuit if no settings file can be found
                raise RuntimeError("Can't find Django settings file!")

            add_path(self.settings_path)
            sys.path.append(self.settings_path)

        from django.conf import settings

        # If the user passed in --django-sqlite, use an in-memory sqlite db
        if self._use_sqlite:
            settings.DATABASE_ENGINE = 'sqlite3'
            settings.DATABASE_NAME = '' # in-memory database
            settings.DATABASE_OPTIONS = {}
            settings.DATABASE_USER = ''
            settings.DATABASE_PASSWORD = ''

        # Do our custom testrunner stuff
        custom_before(use_testfs=self._use_testfs)

        # Some Django code paths evaluate differently
        # between DEBUG and not DEBUG.  Example of this include the url
        # dispatcher when 404's are hit.  Django's own test runner forces DEBUG
        # to be off.
        settings.DEBUG = False

        from django.core import management
        from django.test.utils import setup_test_environment

        self.old_db = settings.DATABASE_NAME
        from django.db import connection

        setup_test_environment()

        management.get_commands()
        management._commands['syncdb'] = 'django.core'

        connection.creation.create_test_db(verbosity=self.verbosity)

    def _should_use_transaction_isolation(self, test, settings):
        """
        Determine if the given test supports transaction management for database
        rollback test isolation and also whether or not the test has opted out
        of that support.

        Transactions make database rollback much quicker when supported, with
        the caveat that any tests that are explicitly testing transactions won't
        work properly and any tests that depend on external access to the test
        database won't be able to view data created/altered during the test.
        """
        from django.test import TransactionTestCase, TestCase

        if not getattr(test.context, 'use_transaction_isolation', True):
            # The test explicitly says not to use transaction isolation
            return False
        if getattr(settings, 'DISABLE_TRANSACTION_MANAGEMENT', False):
            # Do not use transactions if user has forbidden usage.
            return False
        if hasattr(settings, 'DATABASE_SUPPORTS_TRANSACTIONS'):
            if not settings.DATABASE_SUPPORTS_TRANSACTIONS:
                # The DB doesn't support transactions. Don't try it
                return False

        return True

    def _should_use_django_testcase_management(self, test):
        """
        Should we let Django's custom testcase classes handle the setup/teardown
        operations for transaction rollback, fixture loading and urlconf loading.
        """
        from django.test import TransactionTestCase

        # If we're a subclass of TransactionTestCase, then the testcase will
        # handle any transaction setup, fixtures, or urlconfs
        if isinstance(test.test, TransactionTestCase):
            return True
        return False

    def _should_rebuild_schema(self, test):
        if getattr(test.context, 'rebuild_schema', False):
            return True
        return False

    def afterTest(self, test):
        """
        Clean up any changes to the test database.
        """
        # Restore transaction support on tests
        from django.conf import settings
        from django.contrib.contenttypes.models import ContentType
        from django.db import connection, transaction
        from django.core.management import call_command
        from django.test.utils import setup_test_environment, teardown_test_environment
        from django import VERSION as DJANGO_VERSION

        if self._should_rebuild_schema(test):
            connection.creation.destroy_test_db(
                self.old_db, verbosity=self.verbosity)
            teardown_test_environment()

            setup_test_environment()
            connection.creation.create_test_db(verbosity=self.verbosity)
            return

        use_transaction_isolation = self._should_use_transaction_isolation(
            test, settings)
        using_django_testcase_management = self._should_use_django_testcase_management(test)

        if use_transaction_isolation \
           and not using_django_testcase_management:
            self.restore_transaction_support(transaction)
            transaction.rollback()
            if transaction.is_managed():
                transaction.leave_transaction_management()
            # If connection is not closed Postgres can go wild with
            # character encodings.
            connection.close()
        elif not use_transaction_isolation:
            # Have to clear the db even if we're using django because django
            # doesn't properly flush the database after a test. It relies on
            # flushing before a test, so we want to avoid the case where a django
            # test doesn't flush and then a normal test runs, because it will
            # expect the db to already be flushed
            ContentType.objects.clear_cache() # Otherwise django.contrib.auth.Permissions will depend on deleted ContentTypes
            call_command('flush', verbosity=0, interactive=False)

            # In Django <1.2 Depending on the order of certain post-syncdb
            # signals, ContentTypes can be removed accidentally. Manually delete and re-add all
            # and recreate ContentTypes if we're using the contenttypes app
            # See: http://code.djangoproject.com/ticket/9207
            # See: http://code.djangoproject.com/ticket/7052
            if DJANGO_VERSION[0] <= 1 and DJANGO_VERSION[1] < 2 \
               and 'django.contrib.contenttypes' in settings.INSTALLED_APPS:
                from django.contrib.contenttypes.models import ContentType
                from django.contrib.contenttypes.management import update_all_contenttypes
                from django.db import models
                from django.contrib.auth.management import create_permissions
                from django.contrib.auth.models import Permission

                ContentType.objects.all().delete()
                ContentType.objects.clear_cache()
                update_all_contenttypes(verbosity=0)

                # Because of various ways of handling auto-increment, we need to
                # make sure the new contenttypes start at 1
                next_pk = 1
                content_types = list(ContentType.objects.all().order_by('pk'))
                ContentType.objects.all().delete()
                for ct in content_types:
                    ct.pk = next_pk
                    ct.save()
                    next_pk += 1

                # Because of the same problems with ContentTypes, we can get
                # busted permissions
                Permission.objects.all().delete()
                for app in models.get_apps():
                    create_permissions(app=app, created_models=None, verbosity=0)

                # Because of various ways of handling auto-increment, we need to
                # make sure the new permissions start at 1
                next_pk = 1
                permissions = list(Permission.objects.all().order_by('pk'))
                Permission.objects.all().delete()
                for perm in permissions:
                    perm.pk = next_pk
                    perm.save()
                    next_pk += 1

    def beforeTest(self, test):
        """
        Load any database fixtures, set up any test url configurations and
        prepare for using transactions for database rollback if possible.
        """
        if not self.settings_path:
            # short circuit if no settings file can be found
            return

        from django.contrib.sites.models import Site
        from django.contrib.contenttypes.models import ContentType
        from django.core.management import call_command
        from django.core.urlresolvers import clear_url_caches
        from django.conf import settings
        from django.db import connection, transaction
        from django.test import TransactionTestCase

        use_transaction_isolation = self._should_use_transaction_isolation(
            test, settings)
        using_django_testcase_management = self._should_use_django_testcase_management(test)

        if use_transaction_isolation and not using_django_testcase_management:
            transaction.enter_transaction_management()
            transaction.managed(True)
            self.disable_transaction_support(transaction)

        Site.objects.clear_cache()
        ContentType.objects.clear_cache() # Otherwise django.contrib.auth.Permissions will depend on deleted ContentTypes

        if isinstance(test, nose.case.Test) \
           and not using_django_testcase_management:
            # Mirrors django.test.testcases:TestCase

            if hasattr(test.context, 'fixtures'):
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                if use_transaction_isolation:
                    call_command('loaddata', *test.context.fixtures, **{'verbosity': 0, 'commit': False})
                else:
                    call_command('loaddata', *test.context.fixtures, **{'verbosity': 0})

        if isinstance(test, nose.case.Test) and \
           not using_django_testcase_management \
           and hasattr(test.context, 'urls'):
            # We have to use this slightly awkward syntax due to the fact
            # that we're using *args and **kwargs together.
            self.old_urlconf = settings.ROOT_URLCONF
            settings.ROOT_URLCONF = self.urls
            clear_url_caches()

    def finalize(self, result=None):
        """
        Clean up any created database and schema.
        """
        if not self.settings_path:
            # short circuit if no settings file can be found
            return

        from django.test.utils import teardown_test_environment
        from django.db import connection
        from django.conf import settings

        # Clean up our custom testrunner stuff
        custom_after(use_testfs=self._use_testfs)

        connection.creation.destroy_test_db(self.old_db, verbosity=self.verbosity)
        teardown_test_environment()

        if hasattr(self, 'old_urlconf'):
            settings.ROOT_URLCONF = self.old_urlconf
            clear_url_caches()

def custom_before(use_testfs=True):
    if use_testfs:
        setup_fs = SetupTestFilesystem()
    setup_celery = SetupCeleryTesting()
    setup_cache = SetupCacheTesting()
    switched_settings = {
        'DOCUMENT_IMPORT_STORAGE_DIR': 'document_import%(token)s',
        'DOCUMENT_SETTINGS_STORAGE_DIR': 'document_settings%(token)s',
        'ATTACHMENT_STORAGE_PREFIX': 'attachments%(token)s',
        'MAILER_LOCKFILE': 'send_mail%(token)s',
    }
    settings_switcher = SetupSettingsSwitcher(switched_settings)

    from django.conf import settings
    settings.DOCUMENT_PRINTING_CACHE_ON_SAVE = False

    from pstat.printing.conf import settings as print_settings
    from pstat.document_backup.conf import settings as backup_settings
    token = random_token()
    print_settings.PDF_STORAGE_DIR = 'unittest/pdf_cache%s/' % token
    print_settings.PDF_STORAGE_BASE_URL = 'unittest/pdf_cache%s/' % token
    backup_settings.STORAGE_DIR = 'unittest/document_backup%s/' % token
    backup_settings.STORAGE_BASE_URL = 'unittest/document_backup%s/' % token

    settings_switcher.before()
    if use_testfs:
        setup_fs.before()
    setup_celery.before()
    setup_cache.before()

def custom_after(use_testfs=True):
    if use_testfs:
        setup_fs = SetupTestFilesystem()
    setup_celery = SetupCeleryTesting()
    setup_cache = SetupCacheTesting()

    if use_testfs:
        setup_fs.after()
    setup_celery.after()
    setup_cache.after()

def random_token(bits=128):
    """
    Generates a random token, using the url-safe base64 alphabet.
    The "bits" argument specifies the bits of randomness to use.
    """
    alphabet = string.ascii_letters + string.digits + '-_'
    # alphabet length is 64, so each letter provides lg(64) = 6 bits
    num_letters = int(math.ceil(bits / 6.0))
    return ''.join(random.choice(alphabet) for i in range(num_letters))

class TestFileSystemStorage(FileSystemStorage):
    """
    Filesystem storage that puts files in a special test folder that can
    be deleted before and after tests.
    """
    def __init__(self, location=None, base_url=None, *args, **kwargs):
        from django.conf import settings
        token = random_token()
        location = os.path.join(settings.MEDIA_ROOT, token)
        base_url = os.path.join(settings.MEDIA_URL, '%s/' % token)

        return super(TestFileSystemStorage, self).__init__(location, base_url, *args, **kwargs)

class SetupTestFilesystem():
    """
    Set up a test file system so you're writing to a specific directory for your
    testing.
    """
    def before(self):
        from django.conf import settings
        settings.DEFAULT_FILE_STORAGE = 'nosedjango.nosedjango.TestFileSystemStorage'

    def after(self):
        self.clear_test_media()

    def clear_test_media(self):
        from django.core.files.storage import default_storage
        try:
            shutil.rmtree(default_storage.location)
        except OSError:
            pass


class SetupCeleryTesting():
    def before(self):
        from django.conf import settings
        settings.CELERY_ALWAYS_EAGER = True
        settings.CELERY_RESULTS_BACKEND = 'database'

    def after(self):
        pass

class SetupCacheTesting():
    def before(self):
        from django.conf import settings
        settings.CACHE_BACKEND = 'locmem://'
        settings.DISABLE_QUERYSET_CACHE = True

        from django.core.cache import cache
        cache.clear()

    def after(self):
        pass

class SetupSettingsSwitcher():
    def __init__(self, settings_vals):
        self.settings_vals = settings_vals
        self.token = random_token()

    def before(self):
        from django.conf import settings

        for key, value in self.settings_vals.items():
            setattr(settings, key, value % {'token': self.token})

    def after(self):
        pass

# Next 3 plugins derived from django-sane-testing: http://github.com/Almad/django-sane-testing
# By: Lukas "Almad" Linhart http://almad.net/
#####
### It was a nice try with Django server being threaded.
### It still sucks for some cases (did I mentioned urllib2?),
### so provide cherrypy as working alternative.
### Do imports in method to avoid CP as dependency
### Code originally written by Mikeal Rogers under Apache License.
#####

class CherryPyLiveServerPlugin(Plugin):
    name = 'cherrypyliveserver'

    def __init__(self):
        Plugin.__init__(self)
        self.server_started = False
        self.server_thread = None

    def options(self, parser, env=os.environ):
        Plugin.options(self, parser, env)

    def configure(self, options, config):
        Plugin.configure(self, options, config)

    def startTest(self, test):
        from django.conf import settings

        if not self.server_started and \
           getattr(test, 'start_live_server', False):

            self.start_server(
                address=getattr(settings, "LIVE_SERVER_ADDRESS", DEFAULT_LIVE_SERVER_ADDRESS),
                port=int(getattr(settings, "LIVE_SERVER_PORT", DEFAULT_LIVE_SERVER_PORT))
            )
            self.server_started = True

    def finalize(self, result):
        self.stop_test_server()

    def start_server(self, address='0.0.0.0', port=8000):
        _application = AdminMediaHandler(WSGIHandler())

        def application(environ, start_response):
            environ['PATH_INFO'] = environ['SCRIPT_NAME'] + environ['PATH_INFO']
            return _application(environ, start_response)

        from cherrypy.wsgiserver import CherryPyWSGIServer
        from threading import Thread
        self.httpd = CherryPyWSGIServer((address, port), application, server_name='django-test-http')
        self.httpd_thread = Thread(target=self.httpd.start)
        self.httpd_thread.start()
        #FIXME: This could be avoided by passing self to thread class starting django
        # and waiting for Event lock
        sleep(.5)

    def stop_test_server(self):
        if self.server_started:
            self.httpd.stop()
            self.server_started = False

class SeleniumPlugin(Plugin):
    name = 'selenium'

    def options(self, parser, env=os.environ):
        parser.add_option('--selenium-ss-dir',
                          help='Directory for failure screen shots.'
                          )
        parser.add_option('--headless',
                          help="Run the Selenium tests in a headless mode, with virtual frames starting with the given index (eg. 1)",
                          default=None)
        parser.add_option('--driver-type',
                          help='The type of driver that needs to be created',
                          default='firefox')
        parser.add_option('--remote-server-address',
                          help='Use a remote server to run the tests, must pass in the server address',
                          default='localhost')
        parser.add_option('--selenium-port',
                          help='The port for the selenium server',
                          default='4444')
        Plugin.options(self, parser, env)

    def configure(self, options, config):
        if options.selenium_ss_dir:
            self.ss_dir = os.path.abspath(options.selenium_ss_dir)
        else:
            self.ss_dir = os.path.abspath('failure_screenshots')
        valid_browsers = ['firefox', 'internet_explorer', 'chrome']
        if options.driver_type not in valid_browsers:
            raise RuntimeError('--driver-type must be one of: %s' % ' '.join(valid_browsers))
        self._driver_type = options.driver_type.replace('_', ' ')
        self._remote_server_address = options.remote_server_address
        self._selenium_port = options.selenium_port
        self._driver = None
        self._current_windows_handle = None

        self.x_display = 1
        self.run_headless = False
        if options.headless:
            self.run_headless = True
            self.x_display = int(options.headless)
        Plugin.configure(self, options, config)

    def get_driver(self):
        # Lazilly gets the driver one time cant call in begin since ssh tunnel
        # may not be created
        if self._driver:
            return self._driver

        if self._driver_type == 'firefox':
            self._driver = FirefoxWebDriver()
        elif self._driver_type == 'chrome':
            self._driver = ChromeDriver()
        else:
            timeout = 60
            step = 1
            current = 0
            while current < timeout:
                try:
                    self._driver = RemoteDriver(
                        'http://%s:%s/wd/hub' % (self._remote_server_address, self._selenium_port),
                        self._driver_type,
                        'WINDOWS',
                    )
                    break
                except urllib2.URLError:
                    time.sleep(step)
                    current += step
                except httplib.BadStatusLine:
                    self._driver = None
                    break
            if current >= timeout:
                raise urllib2.URLError('timeout')

        # Set the logging level to INFO
        return self._driver


    def finalize(self, result):
        driver = self.get_driver()
        if driver:
            self.get_driver().quit()

        if self.xvfb_process:
            os.kill(self.xvfb_process.pid, 9)
            os.waitpid(self.xvfb_process.pid, 0)

    def begin(self):
        self.xvfb_process = None
        if self.run_headless:
            xvfb_display = self.x_display
            try:
                self.xvfb_process = subprocess.Popen(['xvfb', ':%s' % xvfb_display, '-ac', '-screen', '0', '1024x768x24'], stderr=subprocess.PIPE)
            except OSError:
                # Newer distros use Xvfb
                self.xvfb_process = subprocess.Popen(['Xvfb', ':%s' % xvfb_display, '-ac', '-screen', '0', '1024x768x24'], stderr=subprocess.PIPE)
            os.environ['DISPLAY'] = ':%s' % xvfb_display

    def beforeTest(self, test):
        driver = self.get_driver()
        logging.getLogger().setLevel(logging.INFO)
        setattr(test.test, 'driver', driver)
        # need to know the main window handle for cleaning up extra windows at
        # the end of each test
        if driver:
            self._current_windows_handle = driver.get_current_window_handle()

    def afterTest(self, test):
        driver = getattr(test.test, 'driver', False)
        if not driver:
            return
        if self._current_windows_handle:
            # close all extra windows except for the main window
            for window in driver.get_window_handles():
                if window != self._current_windows_handle:
                    driver.switch_to_window(window)
                    driver.close()
                    driver.switch_to_window(self._current_windows_handle)
        # deal with the onbeforeunload if it is there until selenium has a
        # way to do so in the api
        try:
            driver.execute_script('window.onbeforeunload = function(){};')
        except (ErrorInResponseException, AssertionError):
            pass
        except WebDriverException:
            driver.quit()
            self._driver = None
            

    def handleError(self, test, err):
        if isinstance(test, nose.case.Test) and \
           getattr(test.context, 'selenium_take_ss', False):
            self._take_screenshot(test)

    def handleFailure(self, test, err):
        if isinstance(test, nose.case.Test) and \
           getattr(test.context, 'selenium_take_ss', False):
            self._take_screenshot(test)

    def _take_screenshot(self, test):
        driver_attr = getattr(test.context, 'selenium_driver_attr', 'driver')
        try:
            driver = getattr(test.test, driver_attr)
        except AttributeError:
            print "Error attempting to take failure screenshot"
            return

        # Make the failure ss directory if it doesn't exist
        if not os.path.exists(self.ss_dir):
            os.makedirs(self.ss_dir)

        ss_file = os.path.join(self.ss_dir, '%s.png' % test.id())

        # The Remote server does not have the attribute ``save_screenshot``, so
        # we have to check to see if it is there before using it
        if hasattr(driver, 'save_screenshot'):
            driver.save_screenshot(ss_file)

class SshTunnelPlugin(Plugin):
    name = 'sshtunnel'

    def options(self, parser, env=os.environ):
        parser.add_option('--remote-server',
                          help='Use a remote server to run the tests, must pass in the server address',
                          )
        parser.add_option('--to-from-ports',
                          help='Should be of the form x:y where x is the port that needs to be forwarded to the server and y is the port that the server needs forwarded back to the localhost',
                          default='4444:8001',
                          )
        parser.add_option('--username',
                          help='The username with which to create the ssh tunnel to the remote server',
                          default=None,
                          )
        Plugin.options(self, parser, env)

    def configure(self, options, config):
        # This is only checked since this plugin is configured regardless if
        # the sshtunnel flag is used, and we only want this info here if the
        # --remote-server flag is used
        if options.remote_server:
            try:
                to_port, from_port = options.to_from_ports.split(':', 1)
            except:
                raise RuntimeError("--to_from_ports should be of the form x:y")
            else:
                self._to_port = to_port
                self._from_port = from_port
            self._remote_server = options.remote_server
            self._username = options.username
        Plugin.configure(self, options, config)

    def begin(self):
        # If we are using a remote connection we want to create two tunnels,
        # one to forward from local to server for the port that selenium is
        # listening to, and another from server to local on the port runserver
        # is running on
        if getattr(self, '_remote_server', False):
            params = {
                'username': self._username,
                'host': self._remote_server,
                'to_port': self._to_port,
                'from_port': self._from_port,
            }
            host_str = self._remote_server
            if self._username:
                host_str = '%(username)s@%(host)s' % params,
            self.tunnel_command = [
                'ssh',
                host_str,
                '-L',
                '%(to_port)s:%(host)s:%(to_port)s' % params,
                '-N',
            ]
            self.reverse_tunnel_command = [
                'ssh',
                '-nNT',
                '-R',
                '%(from_port)s:localhost:%(from_port)s' % params,
                host_str,
            ]
            self._tunnel = subprocess.Popen(
                self.tunnel_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._reverse_tunnel = subprocess.Popen(
                self.reverse_tunnel_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def finalize(self, result):
        # Clean up all ssh tunnels
        if not self._tunnel.poll():
            os.kill(self._tunnel.pid, signal.SIGKILL)
            self._tunnel.wait()
        if not self._reverse_tunnel.poll():
            os.kill(self._reverse_tunnel.pid, signal.SIGKILL)
            self._reverse_tunnel.wait()

class DjangoSphinxPlugin(Plugin):
    name = 'djangosphinx'

    def options(self, parser, env=os.environ):
        """
        Sphinx config file that can optionally take the following python
        template string arguments:

        ``database_name``
        ``database_password``
        ``database_username``
        ``sphinx_search_data_dir``
        ``searchd_log_dir``
        """
        parser.add_option('--sphinx-config-tpl',
                          help='Path to the Sphinx configuration file template.')

        super(DjangoSphinxPlugin, self).options(parser, env)

    def configure(self, options, config):
        if options.sphinx_config_tpl:
            self.sphinx_config_tpl = os.path.abspath(options.sphinx_config_tpl)

            # Create a directory for storing the configs, logs and index files
            self.tmp_sphinx_dir = tempfile.mkdtemp()

            self.searchd_port = 45798

        super(DjangoSphinxPlugin, self).configure(options, config)

    def startTest(self, test):
        from django.conf import settings
        from django.db import connection
        if 'mysql' in connection.settings_dict['ENGINE']:
            # Using startTest instead of beforeTest so that we can be sure that
            # the fixtures were already loaded with nosedjango's beforeTest
            build_sphinx_index = getattr(test, 'build_sphinx_index', False)
            run_sphinx_searchd = getattr(test, 'run_sphinx_searchd', False)

            if run_sphinx_searchd:
                # Need to build the config

                # Update the DjangoSphinx client to use the proper port and index
                settings.SPHINX_PORT = self.searchd_port
                from djangosphinx import models as dj_sphinx_models
                dj_sphinx_models.SPHINX_PORT = self.searchd_port

                # Generate the sphinx configuration file from the template
                sphinx_config_path = os.path.join(self.tmp_sphinx_dir, 'sphinx.conf')

                db_dict = connection.settings_dict
                with open(self.sphinx_config_tpl, 'r') as tpl_f:
                    context = {
                        'database_name': db_dict['NAME'],
                        'database_username': db_dict['USER'],
                        'database_password': db_dict['PASSWORD'],
                        'sphinx_search_data_dir': self.tmp_sphinx_dir,
                        'searchd_log_dir': self.tmp_sphinx_dir,
                    }
                    tpl = tpl_f.read()
                    output = tpl % context

                    with open(sphinx_config_path, 'w') as sphinx_conf_f:
                        sphinx_conf_f.write(output)
                        sphinx_conf_f.flush()


            if build_sphinx_index:
                self._build_sphinx_index(sphinx_config_path)
            if run_sphinx_searchd:
                self._start_searchd(sphinx_config_path)

    def afterTest(self, test):
        from django.db import connection
        if 'mysql' in connection.settings_dict['ENGINE']:
            if getattr(test.context, 'run_sphinx_searchd', False):
                self._stop_searchd()

    def finalize(self, test):
        # Delete the temporary sphinx directory
        shutil.rmtree(self.tmp_sphinx_dir, ignore_errors=True)

    def _build_sphinx_index(self, config):
        indexer = subprocess.Popen(['indexer', '--config', config, '--all'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if indexer.wait() != 0:
            print "Sphinx Indexing Problem"
            stdout, stderr = indexer.communicate()
            print "stdout: %s" % stdout
            print "stderr: %s" % stderr

    def _start_searchd(self, config):
        self._searchd = subprocess.Popen(
            ['searchd', '--config', config, '--console',
             '--port', str(self.searchd_port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        returned = self._searchd.poll()
        if returned != None:
            print "Sphinx Search unavailable. searchd exited with code: %s" % returned
            stdout, stderr = self._searchd.communicate()
            print "stdout: %s" % stdout
            print "stderr: %s" % stderr

        self._wait_for_connection(self.searchd_port)

    def _wait_for_connection(self, port):
        """
        Wait until we can make a socket connection to sphinx.
        """
        connected = False
        max_tries = 10
        num_tries = 0
        wait_time = 0.5
        while not connected or num_tries >= max_tries:
            time.sleep(wait_time)
            try:
                af = socket.AF_INET
                addr = ('127.0.0.1', port)
                desc = '%s;%s' % addr
                sock = socket.socket (af, socket.SOCK_STREAM)
                sock.connect (addr)
            except socket.error, msg:
                if sock:
                    sock.close()
                num_tries += 1
                continue
            connected = True

        if not connected:
            print >> sys.stderr, "Error connecting to sphinx searchd"

    def _stop_searchd(self):
        try:
            if not self._searchd.poll():
                os.kill(self._searchd.pid, signal.SIGKILL)
                self._searchd.wait()
        except AttributeError:
            print sys.stderr, "Error stoping sphinx search daemon"
