#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Provide common connector methods via the BaseConnector.
"""

import string
import os
import server.settings

from django.conf import settings
from mongoengine import connect


class BaseConnector(object):
    """Basic connector execution stuff that is shared between connectors."""
    
    def __init__(self):
        mongo_connection = {
            'host': server.settings.DATABASES['mongodb']['HOST'],
            'port': server.settings.DATABASES['mongodb']['PORT'],
            'db': server.settings.DATABASES['mongodb']['NAME'],
            'username': server.settings.DATABASES['mongodb']['USER'],
            'password': server.settings.DATABASES['mongodb']['PASSWORD'],
            'authentication_source': server.settings.DATABASES['mongodb']['AUTHENTICATION_DB'],
            'connect': False
        }

        connect(**mongo_connection)

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
        command = path_to_execute_script + plugin_execution.get_sorted_argument_values()

        # We need to substitute these here, if the mongodb is not secured
        db_user = settings.DATABASES['mongodb']['USER']
        if db_user is None or db_user == '':
            db_user = 'None'

        db_password = settings.DATABASES['mongodb']['PASSWORD']
        if db_password is None or db_password == '':
            db_password = 'None'

        db_authentication = settings.DATABASES['mongodb']['AUTHENTICATION_DB']
        if db_authentication is None or db_authentication == '':
            db_authentication = 'None'

        # Substitute stuff
        return string.Template(command).safe_substitute({
            'db_user': db_user,
            'db_password': db_password,
            'db_database': settings.DATABASES['mongodb']['NAME'],
            'db_hostname': settings.DATABASES['mongodb']['HOST'],
            'db_port': settings.DATABASES['mongodb']['PORT'],
            'db_authentication': db_authentication,
            'project_name': plugin_execution.project.name,
            'plugin_path': os.path.join(plugin_path, str(plugin_execution.plugin)),
            'cores_per_job': 1,
        })
