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

    def beforeTestSetup(self, settings, setup_test_environment, connection):
        pass

    def afterTestSetup(self, settings):
        pass

    def beforeTestDb(self, settings, connection, management):
        pass

    def afterTestDb(self, settings, connection):
        pass

    def beforeTransactionManagement(self, settings, test):
        pass

    def afterTransactionManagement(self, settings, test):
        pass

    def beforeFixtureLoad(self, settings, test):
        pass

    def afterFixtureLoad(self, settings, test):
        pass

    def beforeUrlConfLoad(self, settings, test):
        pass

    def afterUrlConfLoad(self, settings, test):
        pass

    def beforeDestroyTestDb(self, settings, connection):
        pass

    def afterDestroyTestDb(self, settings, connection):
        pass

    def beforeTeardownTestEnv(self, settings, teardown_test_environment):
        pass

    def afterTeardownTestEnv(self, settings):
        pass
