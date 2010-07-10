from nose.plugins.base import Plugin as NosePlugin

class Plugin(NosePlugin):
    django_plugin = True

class IPluginInterface(object):
    """
    IPluginInteface describes the NoseDjango plugin API. Do not subclass or use
    this class directly. This interface describes an API **in addition** to
    the API described with ``nose.plugins.base.IPluginInterface``.
    """
    def __new__(cls, *arg, **kw):
        raise TypeError("IPluginInterface class is for documentation only")

    def beforeTestEnv(self):
        pass

    def afterTestEnv(self):
        pass

    def beforeTestDb(self):
        pass

    def afterTestDb(self):
        pass

    def beforeTransactionManagement(self):
        pass

    def afterTransactionManagement(self):
        pass

    def beforeFixtureLoad(self):
        pass

    def afterFixtureLoad(self):
        pass

    def beforeUrlConfLoad(self):
        pass

    def afterUrlConfLoad(self):
        pass

    def addOptions(self, parser, env):
        """Called to allow plugin to register command-line options with the
        parser. DO NOT return a value from this method unless you want to stop
        all other plugins from setting their options.

        .. warning ::

           DEPRECATED -- implement
           :meth:`options <nose.plugins.base.IPluginInterface.options>` instead.
        """
        pass
    add_options = addOptions
    add_options.deprecated = True

    def addDeprecated(self, test):
        """Called when a deprecated test is seen. DO NOT return a value
        unless you want to stop other plugins from seeing the deprecated
        test.

        .. warning :: DEPRECATED -- check error class in addError instead
        """
        pass
    addDeprecated.deprecated = True

    def addError(self, test, err):
        """Called when a test raises an uncaught exception. DO NOT return a
        value unless you want to stop other plugins from seeing that the
        test has raised an error.

        :param test: the test case
        :type test: :class:`nose.case.Test`
        :param err: sys.exc_info() tuple
        :type err: 3-tuple
        """
        pass
    addError.changed = True

    def addFailure(self, test, err):
        """Called when a test fails. DO NOT return a value unless you
        want to stop other plugins from seeing that the test has failed.

        :param test: the test case
        :type test: :class:`nose.case.Test`
        :param err: 3-tuple
        :type err: sys.exc_info() tuple
        """
        pass
    addFailure.changed = True

    def addSkip(self, test):
        """Called when a test is skipped. DO NOT return a value unless
        you want to stop other plugins from seeing the skipped test.

        .. warning:: DEPRECATED -- check error class in addError instead
        """
        pass
    addSkip.deprecated = True

    def addSuccess(self, test):
        """Called when a test passes. DO NOT return a value unless you
        want to stop other plugins from seeing the passing test.

        :param test: the test case
        :type test: :class:`nose.case.Test`
        """
        pass
    addSuccess.changed = True

    def afterContext(self):
        """Called after a context (generally a module) has been
        lazy-loaded, imported, setup, had its tests loaded and
        executed, and torn down.
        """
        pass
    afterContext._new = True

    def afterDirectory(self, path):
        """Called after all tests have been loaded from directory at path
        and run.

        :param path: the directory that has finished processing
        :type path: string
        """
        pass
    afterDirectory._new = True

    def afterImport(self, filename, module):
        """Called after module is imported from filename. afterImport
        is called even if the import failed.

        :param filename: The file that was loaded
        :type filename: string
        :param filename: The name of the module
        :type module: string
        """
        pass
    afterImport._new = True

    def afterTest(self, test):
        """Called after the test has been run and the result recorded
        (after stopTest).

        :param test: the test case
        :type test: :class:`nose.case.Test`
        """
        pass
    afterTest._new = True

