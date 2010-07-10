from __future__ import with_statement

import os, tempfile, shutil, subprocess, signal

from nosedjango.plugins.base import Plugin

class SphinxPlugin(Plugin):
    """
    Plugin for configuring and running a sphinx search process for djangosphinx
    that's hooked up to a django test database.
    """
    name = 'django-sphinx'

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

        super(SphinxPlugin, self).options(parser, env)

    def configure(self, options, config):
        if options.sphinx_config_tpl:
            self.sphinx_config_tpl = os.path.abspath(options.sphinx_config_tpl)

            # Create a directory for storing the configs, logs and index files
            self.tmp_sphinx_dir = tempfile.mkdtemp()

            self.searchd_port = 45798

        super(SphinxPlugin, self).configure(options, config)

    def startTest(self, test):
        from django.conf import settings
        if settings.DATABASE_ENGINE == 'mysql':
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

                with open(self.sphinx_config_tpl, 'r') as tpl_f:
                    context = {
                        'database_name': settings.DATABASE_NAME,
                        'database_username': settings.DATABASE_USER,
                        'database_password': settings.DATABASE_PASSWORD,
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
        from django.conf import settings
        if settings.DATABASE_ENGINE == 'mysql':
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

    def _stop_searchd(self):
        if not self._searchd.poll():
            os.kill(self._searchd.pid, signal.SIGKILL)
            self._searchd.wait()
