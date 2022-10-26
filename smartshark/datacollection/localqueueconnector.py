#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
This module provides a basic alternative for the execution in the HCP System.
It currently works with a worker process that must be running which takes its commands from a redis queue.
The LocalQueueConnector puts the work items into the queue.

This can be used for local debugging for plugin development.
"""
import tarfile
import logging
import os
import string
import json

import redis

from django.conf import settings
from pycoshark.mongomodels import VCSSystem

from smartshark.utils.connector import BaseConnector
from smartshark.models import Job
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface


class LocalQueueConnector(PluginManagementInterface, BaseConnector):
    """Feeds jobs into a local redis queue.

    The purpose is mainly for running a local instance of ServerSHARK for debugging purposes.

    Does not support 'queue' and 'cores_per_job' params from plugin execution!
    """

    def __init__(self):
        """Set some basic stuff, logging and the paths used for plugin execution."""

        super(LocalQueueConnector, self).__init__()

        self._log = logging.getLogger('localqueueconnector')
        self.redis_url = settings.LOCALQUEUE['redis_url']
        self.job_queue = settings.LOCALQUEUE['job_queue']
        self.result_queue = settings.LOCALQUEUE['result_queue']

        self.output_path = settings.LOCALQUEUE['plugin_output']
        self.plugin_path = settings.LOCALQUEUE['plugin_installation']
        self.project_path = os.path.join(settings.LOCALQUEUE['root_path'], 'projects')

        self._debug = settings.LOCALQUEUE['debug']
        self.con = redis.from_url(self.redis_url)


    @property
    def identifier(self):
        """Return uniqe identifier for this connector."""
        return 'LOCALQUEUE'

    def execute_plugins(self, project, plugin_executions):
        """Execute plugins.

        We are just pushing the shell commands that would have been run on the HPC System to the redis queue.
        """
        self._log.info('Preparing project...')

        # this try/catch is used to catch other executions which do not have a project
        all_projects = False
        try:
            # look for the first plugin execution object where repository url is set
            pe = list(filter(lambda x: x.repository_url, plugin_executions))[0]
            project_name = pe.project.name
        except IndexError:
            project_name = 'all'
            all_projects = True

        # TODO: Fails on multiple repositories for one project in the same plugin_execution list
        # Check if vcsshark is executed
        project_folder = os.path.join(self.project_path, project_name)
        if any('vcsshark' == plugin_exec.plugin.name.lower() for plugin_exec in plugin_executions):
            # Clone to update
            self._delete_sanity_check(project_folder)
            self._execute_command({'shell': 'rm -rf {}'.format(project_folder)})
            self._execute_command({'shell': 'git clone {} {}'.format(pe.repository_url, project_folder)})
        else:
            # If there is a plugin that needs the repository folder and it is not existent,
            # we need to get it from the gridfs
            if not all_projects and not os.path.isdir(project_folder):
                self._log.info('fetching project from gridfs')
                repository = VCSSystem.objects.get(url=pe.repository_url).repository_file

                if repository.grid_id is None:
                    self._log.error("Execute vcsshark first!")
                    raise Exception("VCSShark need to be executed first!")

                # make sure we have the directories
                os.makedirs(self.project_path)

                # Read tar_gz and copy it to temporary file
                tmp_tar_gz = os.path.join(self.project_path, 'tmp.tar.gz')
                with open(tmp_tar_gz, 'wb') as repository_tar_gz:
                    repository_tar_gz.write(repository.read())

                # Extract it
                with tarfile.open(tmp_tar_gz, "r:gz") as tar_gz:
                    def is_within_directory(directory, target):
                        
                        abs_directory = os.path.abspath(directory)
                        abs_target = os.path.abspath(target)
                    
                        prefix = os.path.commonprefix([abs_directory, abs_target])
                        
                        return prefix == abs_directory
                    
                    def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
                    
                        for member in tar.getmembers():
                            member_path = os.path.join(path, member.name)
                            if not is_within_directory(path, member_path):
                                raise Exception("Attempted Path Traversal in Tar File")
                    
                        tar.extractall(path, members, numeric_owner=numeric_owner) 
                        
                    
                    safe_extract(tar_gz, self.project_path)

                # Delete temporary tar_gz
                os.remove(tmp_tar_gz)

        for plugin_execution in plugin_executions:
            plugin_command = self._generate_plugin_execution_command(self.plugin_path, plugin_execution)

            plugin_execution_output_path = os.path.join(self.output_path, str(plugin_execution.pk))
            self._execute_command({'shell': 'mkdir -p {}'.format(plugin_execution_output_path)})

            for job in Job.objects.filter(plugin_execution=plugin_execution).all():
                command = string.Template(plugin_command).safe_substitute({
                    'path': os.path.join(self.project_path, project_name),
                    'revision': job.revision_hash
                })

                # in addition to the shell command we are passing ids so that the worker can write back to the database if the job was successful.
                self._execute_command({'shell': command, 'job_id': job.pk, 'plugin_execution_id': plugin_execution.pk})


    def _delete_sanity_check(self, path):
        """At least dont allow rm -rf /."""
        if path in ['', '/', '.']:
            raise Exception('trying to rm -rf / this should not happen :-(')

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
        """Just return WAIT because then nothing changes for the Job and we can update it from the worker."""
        stati = []
        for job in jobs:
            stati.append('WAIT')
        return stati

    def _get_log_file(self, job, log_type):
        ret = []
        plugin_execution_output_path = os.path.join(self.output_path, str(job.plugin_execution.pk))
        with open(os.path.join(plugin_execution_output_path, str(job.pk) + '_' + log_type + '.txt'), 'r') as f:
            for line in f.readlines():
                ret.append(line.rstrip())
        return ret

    def get_output_log(self, job):
        """Return the contents of the out log file."""
        return self._get_log_file(job, 'out')

    def get_error_log(self, job):
        """Return the contents of the err log file."""
        return self._get_log_file(job, 'err')

    def get_sent_bash_command(self, job):
        """Not implemented."""
        return

    def default_queue(self):
        return self.job_queue

    def default_cores_per_job(self):
        return 1

    def delete_plugins(self, plugins):
        """Delete plugin folder."""
        for plugin in plugins:
            path_to_remove = '{}/{}'.format(self.plugin_path, str(plugin))
            self._delete_sanity_check(path_to_remove)
            self._execute_command({'shell': 'rm -rf {}'.format(path_to_remove)})

    def install_plugins(self, plugins):
        """Create folders for plugin, decompress tar and execute install script."""
        installations = []

        for plugin in plugins:
            # delete old version first
            path_to_remove = '{}/{}'.format(self.plugin_path, str(plugin))
            self._delete_sanity_check(path_to_remove)
            self._execute_command({'shell': 'rm -rf {}'.format(path_to_remove)})

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

            # we always return true because we do not have channel back for job execution results
            installations.append((True, None))

        return installations

    def delete_output_for_plugin_execution(self, plugin_execution):
        """Delete folder containing output for plugin execution id."""
        path_to_remove = os.path.join(self.output_path, str(plugin_execution.id))
        self._delete_sanity_check(path_to_remove)
        self._execute_command({'shell': 'rm -rf {}'.format(path_to_remove)})
