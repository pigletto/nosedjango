"""
nose plugin for easy testing of django projects and apps. Sets up a test
database (or schema) and installs apps from test settings file before tests
are run, and tears the test database (or schema) down after all tests are run.
"""

from __future__ import with_statement

import os, sys, shutil
import re
import subprocess
import signal
import tempfile
import math, string, random
from time import sleep

from nose.plugins import Plugin
from nose.plugins.skip import SkipTest
import nose.case

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

    def __init__(self):
        Plugin.__init__(self)
        self.nose_config = None
        self.django_plugins = []

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

        super(NoseDjango, self).configure(options, conf)

        self.nose_config = conf

    def call_plugins_method(self, meth_name, *args, **kwargs):
        for plugin in self.django_plugins:
            if hasattr(plugin, meth_name):
                getattr(plugin, meth_name)(*args, **kwargs)

    def begin(self):
        """Create the test database and schema, if needed, and switch the
        connection over to that database. Then call install() to install
        all apps listed in the loaded settings module.
        """
        for plugin in self.nose_config.plugins.plugins:
            if getattr(plugin, 'django_plugin', False):
                self.django_plugins.append(plugin)

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
        custom_before()

        # Some Django code paths evaluate differently
        # between DEBUG and not DEBUG.  Example of this include the url
        # dispatcher when 404's are hit.  Django's own test runner forces DEBUG
        # to be off.
        settings.DEBUG = False

        from django.core import management
        from django.test.utils import setup_test_environment

        self.old_db = settings.DATABASE_NAME
        from django.db import connection

        self.call_plugins_method(
            'beforeTestSetup', settings, setup_test_environment, connection)
        setup_test_environment()
        self.call_plugins_method('afterTestSetup', settings)

        management.get_commands()
        management._commands['syncdb'] = 'django.core'

        self.call_plugins_method('beforeTestDb', settings, connection, management)
        connection.creation.create_test_db(verbosity=self.verbosity)
        self.call_plugins_method('afterTestDb', settings, connection)

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

        # If we're a subclass of TransactionTestCase, then either we shouldn't
        # manage transactions because the test needs to handle it or we can
        # use a transaction but Django's testcase will handle it themselves
        if isinstance(test.test, TransactionTestCase):
            return False

        return True

    def afterTest(self, test):
        """
        Clean up any changes to the test database.
        """
        # Restore transaction support on tests
        from django.conf import settings
        from django.db import connection, transaction

        # beforeRollback(settings, connection, transaction)
        if self._should_use_transaction_isolation(test, settings):
            self.restore_transaction_support(transaction)
            transaction.rollback()
            if transaction.is_managed():
                transaction.leave_transaction_management()
            # If connection is not closed Postgres can go wild with
            # character encodings.
            connection.close()

        self.call_plugins_method('afterRollback', settings)

    def beforeTest(self, test):
        """
        Load any database fixtures, set up any test url configurations and
        prepare for using transactions for database rollback if possible.
        """
        if not self.settings_path:
            # short circuit if no settings file can be found
            return

        from django.core.management import call_command
        from django.core.urlresolvers import clear_url_caches
        from django.conf import settings
        from django.db import connection, transaction
        from django.test import TransactionTestCase

        use_transaction_isolation = self._should_use_transaction_isolation(test, settings)

        if use_transaction_isolation:
            self.call_plugins_method('beforeTransactionManagement', settings, test)

            transaction.enter_transaction_management()
            transaction.managed(True)
            self.disable_transaction_support(transaction)

            from django.contrib.sites.models import Site
            Site.objects.clear_cache()

            self.call_plugins_method('afterTransactionManagement', settings, test)

        self.call_plugins_method('beforeFixtureLoad', settings, test)
        if isinstance(test, nose.case.Test) and \
           not isinstance(test.test, TransactionTestCase):
            # Mirrors django.test.testcases:TestCase
            call_command('flush', verbosity=0, interactive=False)
            if hasattr(test.context, 'fixtures'):
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                call_command('loaddata', *test.context.fixtures, **{'verbosity': 0})
        self.call_plugins_method('afterFixtureLoad', settings, test)

        self.call_plugins_method('beforeUrlConfLoad', settings, test)
        if isinstance(test, nose.case.Test) and \
           not isinstance(test.test, TransactionTestCase) and \
            hasattr(test.context, 'urls'):
                # We have to use this slightly awkward syntax due to the fact
                # that we're using *args and **kwargs together.
                self.old_urlconf = settings.ROOT_URLCONF
                settings.ROOT_URLCONF = self.urls
                clear_url_caches()
        self.call_plugins_method('afterUrlConfLoad', settings, test)

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
        custom_after()

        self.call_plugins_method('beforeDestroyTestDb', settings, connection)
        connection.creation.destroy_test_db(self.old_db, verbosity=self.verbosity)
        self.call_plugins_method('afterDestroyTestDb', settings, connection)

        self.call_plugins_method(
            'beforeTeardownTestEnv', settings, teardown_test_environment)
        teardown_test_environment()
        self.call_plugins_method('afterTeardownTestEnv', settings)

        if hasattr(self, 'old_urlconf'):
            settings.ROOT_URLCONF = self.old_urlconf
            clear_url_caches()

def custom_before():
    setup_celery = SetupCeleryTesting()
    setup_cache = SetupCacheTesting()

    from django.conf import settings
    settings.DOCUMENT_PRINTING_CACHE_ON_SAVE = False

    setup_celery.before()
    setup_cache.before()

def custom_after():
    setup_celery = SetupCeleryTesting()
    setup_cache = SetupCacheTesting()

    setup_celery.after()
    setup_cache.after()


class SetupCeleryTesting():
    def before(self):
        from django.conf import settings
        settings.CELERY_ALWAYS_EAGER = True

    def after(self):
        pass

class SetupCacheTesting():
    def before(self):
        from django.conf import settings
        settings.CACHE_BACKEND = 'locmem://'
        settings.DISABLE_QUERYSET_CACHE = True

    def after(self):
        pass



class SeleniumPlugin(Plugin):
    name = 'selenium'
    activation_parameter = '--with-selenium'

    def options(self, parser, env=os.environ):
        parser.add_option('--selenium-ss-dir',
                          help='Directory for failure screen shots.'
                          )
        parser.add_option('--headless',
                          help="Run the Selenium tests in a headless mode, with virtual frames starting with the given index (eg. 1)",
                          default=None)
        Plugin.options(self, parser, env)

    def configure(self, options, config):
        if options.selenium_ss_dir:
            self.ss_dir = os.path.abspath(options.selenium_ss_dir)
        else:
            self.ss_dir = os.path.abspath('failure_screenshots')

        self.x_display_counter = 1
        self.run_headless = False
        if options.headless:
            self.run_headless = True
            self.x_display_counter = int(options.headless)

        Plugin.configure(self, options, config)

    def beforeTest(self, test):
        self.xvfb_process = None
        if getattr(test.context, 'selenium', False) and self.run_headless:
            try:
                self.xvfb_process = subprocess.Popen(['xvfb', ':%s' % self.x_display_counter, '-ac', '-screen', '0', '1024x768x24'], stderr=subprocess.PIPE)
            except OSError:
                # Newer distros use Xvfb
                self.xvfb_process = subprocess.Popen(['Xvfb', ':%s' % self.x_display_counter, '-ac', '-screen', '0', '1024x768x24'], stderr=subprocess.PIPE)
            os.environ['DISPLAY'] = ':%s' % self.x_display_counter
            self.x_display_counter += 1

    def afterTest(self, test):
        if getattr(test.context, 'selenium', False):
            driver_attr = getattr(test.context, 'selenium_driver_attr', 'driver')
            driver = getattr(test.test, driver_attr)
            driver.quit()
        if self.xvfb_process:
            os.kill(self.xvfb_process.pid, 9)
            os.waitpid(self.xvfb_process.pid, 0)

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

        driver.save_screenshot(ss_file)

