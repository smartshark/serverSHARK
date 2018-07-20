#!/usr/bin/env python
# -*- coding: utf-8 -*-

from decimal import Decimal

from smartshark.models import Job, Plugin, Project, PluginExecution
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Fetch Logs for set of jobs and filter them for certain keywords."""

    help = 'Filter job logs'

    def add_arguments(self, parser):
        parser.add_argument('plugin_name', type=str, help='Name of the plugin, Version can be used with = e.g., coastSHARK=1.03')
        parser.add_argument('project_name', type=str)
        parser.add_argument('filter_state', type=str, help='Select only Jobs with this state.')
        parser.add_argument('filter_log_type', type=str, help='Log type (error, output).')
        parser.add_argument('filter_string', type=str, help='String to filter in job logs.')

        parser.add_argument('--execute', action='store_true', dest='execute', help='Really execute the operation.')

    def handle(self, *args, **options):

        tmp = options['plugin_name'].split('=')
        if len(tmp) > 1:
            plugin_name = tmp[0]
            plugin_version = Decimal(tmp[1])
            plugin = Plugin.objects.get(name__icontains=plugin_name, version=plugin_version)
        else:
            plugin = Plugin.objects.get(name__icontains=options['plugin_name'])

        project = Project.objects.get(name__icontains=options['project_name'])

        pe = PluginExecution.objects.get(plugin=plugin, project=project)

        jobs = Job.objects.filter(plugin_execution=pe, status=options['filter_state'].upper())

        if not options['execute']:
            self.stdout.write('not executing, to execute operation run with --execute')

        h = 'Searching for {} in {} logs of {} jobs with state {} for plugin {} on project {}'.format(options['filter_string'], options['filter_log_type'], len(jobs), options['filter_state'], plugin.name, project.name)
        self.stdout.write(h)

        interface = PluginManagementInterface.find_correct_plugin_manager()

        if options['execute']:
            found = 0
            for job in jobs:
                output = []
                if options['filter_log_type'] == 'error':
                    output = interface.get_error_log(job)
                if options['filter_log_type'] == 'output':
                    output = interface.get_output_log(job)

                if output:
                    output = '\n'.join(output)

                if options['filter_string'] in output:
                    found += 1

            self.stdout.write('String found in {} of {} jobs'.format(found, len(jobs)))
