#!/usr/bin/env python
# -*- coding: utf-8 -*-

from smartshark.models import Job, Plugin, Project, PluginExecution

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Convenience method to set job states on multiple jobs."""

    help = 'Set job states'

    def add_arguments(self, parser):
        parser.add_argument('plugin_name', type=str)
        parser.add_argument('project_name', type=str)
        parser.add_argument('filter_state', type=str, help='Select only Jobs with this state.')
        parser.add_argument('state', type=str, help='State that will be set on Jobs.')
        parser.add_argument('--execute', action='store_true', dest='execute', help='Really execute the operation.')

    def handle(self, *args, **options):

        tmp = options['plugin_name'].split('=')
        if len(tmp) > 1:
            plugin_name = tmp[0]
            plugin_version = tmp[1]
            plugin = Plugin.objects.get(name__icontains=plugin_name, version=plugin_version)
        else:
            plugin = Plugin.objects.get(name__icontains=options['plugin_name'])

        project = Project.objects.get(name__iexact=options['project_name'])

        pe = PluginExecution.objects.filter(plugin=plugin, project=project).order_by('-submitted_at')[0]
        self.stdout.write('looking in pluginexecution from: {}'.format(pe.submitted_at))

        jobs = Job.objects.filter(plugin_execution=pe, status=options['filter_state'].upper())

        if not options['execute']:
            self.stdout.write('not executing, to execute operation run with --execute')

        h = 'setting {} on {} jobs with state {} for plugin {} on project {}'.format(options['state'], len(jobs), options['filter_state'], plugin.name, project.name)
        self.stdout.write(h)

        if options['execute']:
            for job in jobs:
                job.status = options['state'].upper()
                job.save()

            self.stdout.write('Finished setting job states')
