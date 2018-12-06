#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Provide common connector methods via the BaseConnector.
"""

import string
import os

from django.conf import settings


class BaseConnector(object):
    """Basic connector execution stuff that is shared between connectors."""

    def _add_parameters_to_install_command(self, path_to_script, plugin):
        # we may have additional parameters
        command = path_to_script + " "

        for argument in plugin.argument_set.all().filter(type='install').order_by('position'):
            # Add none if the value is not set, this needs to be catched in the install.sh of the plugin
            if not argument.install_value.strip():
                command += "None"
            else:
                command += argument.install_value + " "

        return command

    def _generate_plugin_execution_command(self, plugin_path, plugin_execution):
        path_to_execute_script = '{}/{}/execute.sh'.format(plugin_path, str(plugin_execution.plugin))

        # we have parmeters!
        path_to_execute_script += " "

        # Add parameter
        command = path_to_execute_script + plugin_execution.get_named_argument_values()

        # Substitute stuff
        return string.Template(command).safe_substitute({
            'db_user': settings.DATABASES['mongodb']['USER'],
            'db_password': settings.DATABASES['mongodb']['PASSWORD'],
            'db_database': settings.DATABASES['mongodb']['NAME'],
            'db_hostname': settings.DATABASES['mongodb']['HOST'],
            'db_port': settings.DATABASES['mongodb']['PORT'],
            'db_authentication': settings.DATABASES['mongodb']['AUTHENTICATION_DB'],
            'project_name': plugin_execution.project.name,
            'plugin_path': os.path.join(plugin_path, str(plugin_execution.plugin))
        })
