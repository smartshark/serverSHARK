import logging
import os
import string
import json

import redis

from django.conf import settings

from smartshark.models import Job
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface


class BaseConnector(object):

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


class LocalQueueConnector(PluginManagementInterface, BaseConnector):
    """Feeds jobs into a local redis queue."""
    def __init__(self):
        self._log = logging.getLogger('localqueueconnector')
        self.redis_url = settings.LOCALQUEUE['redis_url']
        self.job_queue = settings.LOCALQUEUE['job_queue']
        self.result_queue = settings.LOCALQUEUE['result_queue']

        self.output_path = os.path.join(settings.LOCALQUEUE['root_path'], 'output')
        self.plugin_path = os.path.join(settings.LOCALQUEUE['root_path'], 'plugins')
        self.project_path = os.path.join(settings.LOCALQUEUE['root_path'], 'projects')

        self._debug = settings.LOCALQUEUE['debug']

        self.con = redis.from_url(self.redis_url)

    @property
    def identifier(self):
        return 'LOCALQUEUE'

    def execute_plugins(self, project, jobs, plugin_executions):
        # Prepare project (clone / pull)
        self._log.info('Preparing project...')

        # look for the first plugin execution object where repository url is set
        pe = list(filter(lambda x: x.repository_url, plugin_executions))[0]
        project_name = pe.project.name

        # prepare project with this information
        # TODO: Fails on multiple repositories for one project in the same plugin_execution list
        git_clone_target = os.path.join(self.project_path, project_name)
        self._execute_command({'shell': 'rm -rf {}'.format(git_clone_target)})
        self._execute_command({'shell': 'git clone {} {}'.format(pe.repository_url, git_clone_target)})

        commands = []
        for plugin_execution in plugin_executions:
            plugin_command = self._generate_plugin_execution_command(self.plugin_path, plugin_execution)

            plugin_execution_output_path = os.path.join(self.output_path, str(plugin_execution.pk))
            self._execute_command({'shell': 'mkdir -p {}'.format(plugin_execution_output_path)})

            for job in Job.objects.filter(plugin_execution=plugin_execution).all():
                command = string.Template(plugin_command).safe_substitute({
                    'path': os.path.join(self.project_path, project_name),
                    'revision': job.revision_hash
                })

                self._execute_command({'shell': command, 'job_id': job.pk, 'plugin_execution_id': plugin_execution.pk})

    def _execute_command(self, data):
        if self._debug:
            print('Would execute:')
            print(data['shell'])
            if 'job_id' in data.keys():
                print('Job: {}'.format(data['job_id']))
            print('--')
        else:
            self.con.rpush(self.job_queue, json.dumps(data))

    def get_job_stati(self, jobs):
        """Just return WAIT because then nothing changes for the Job and we can update it from the Peon."""
        stati = []
        for job in jobs:
            stati.append('WAIT')
        return stati

    def get_output_log(self, job):
        out = []
        plugin_execution_output_path = os.path.join(self.output_path, str(job.plugin_execution.pk))
        with open(os.path.join(plugin_execution_output_path, str(job.pk) + '_out.txt'), 'r') as f:
            out.append(f.readline())
        
        return out

    def get_error_log(self, job):
        err = []
        plugin_execution_output_path = os.path.join(self.output_path, str(job.plugin_execution.pk))
        with open(os.path.join(plugin_execution_output_path, str(job.pk) + '_err.txt'), 'r') as f:
            err.append(f.readline())

        return err

    def get_sent_bash_command(self, job):
        return

    def delete_plugins(self, plugins):
        for plugin in plugins:
            self._execute_command({'shell': 'rm -rf {}/{}'.format(self.plugin_path, str(plugin))})

    def install_plugins(self, plugins):
        installations = []

        for plugin in plugins:
            # delete old version first
            self._execute_command({'shell': 'rm -rf {}/{}'.format(self.plugin_path, str(plugin))})

            # Untar plugin
            self._execute_command({'shell': 'mkdir -p {}/{}'.format(self.plugin_path, str(plugin))})
            self._execute_command({'shell': 'tar -C {}/{} -xvf {}'.format(self.plugin_path, str(plugin), plugin.archive.path)})

            # create install command
            path_to_install_script = '{}/{}/install.sh'.format(self.plugin_path, str(plugin))
            path_to_execute_script = '{}/{}/execute.sh'.format(self.plugin_path, str(plugin))

            # Make execution script executable
            self._execute_command({'shell': 'chmod +x {}'.format(path_to_install_script)})
            self._execute_command({'shell': 'chmod +x {}'.format(path_to_execute_script)})

            # Add parameters
            command = self._add_parameters_to_install_command(path_to_install_script, plugin)

            cmd = string.Template(command).substitute({
                'plugin_path': os.path.join(self.plugin_path, str(plugin))
            })

            self._execute_command({'shell': cmd})
            installations.append((True, None))

        return installations


    def delete_output_for_plugin_execution(self, plugin_execution):
        pass