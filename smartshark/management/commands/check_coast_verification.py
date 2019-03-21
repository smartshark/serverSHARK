#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from smartshark.models import Job, Project, PluginExecution, CommitVerification
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface

from django.core.management.base import BaseCommand


logger = logging.getLogger('django')


class Command(BaseCommand):
    """This marks CommitVerification models where coastSHARK failed as passed if only files are contained where coastSHARK threw a parsing error."""

    help = 'Check CommitVerification models where coastSHARK failed for parsing errors'

    def add_arguments(self, parser):
        parser.add_argument('project_name', type=str)

    def handle(self, *args, **options):
        if not options['project_name']:
            self.stdout.write('need project name')

        interface = PluginManagementInterface.find_correct_plugin_manager()

        project = Project.objects.get(name__iexact=options['project_name'])

        # get failed commits from CommitVerification where coastSHARK failed
        commits = CommitVerification.objects.filter(project=project, coastSHARK=False)

        # we need to get the most current job for each commit (because of repetitions for coastSHARK runs)
        jobs = {}
        for pe in PluginExecution.objects.filter(plugin__name__startswith='coastSHARK', project=project).order_by('submitted_at'):
            for obj in commits:
                try:
                    jobs[obj.commit] = Job.objects.get(plugin_execution=pe, revision_hash=obj.commit)
                except Job.DoesNotExist:
                    pass
                except Job.MultipleObjectsReturned:
                    jobs[obj.commit] = Job.objects.filter(plugin_execution=pe, revision_hash=obj.commit).last()

        modified = 0
        for obj in commits:
            # split of file for coastSHARK
            tmp = obj.text
            collect_state = False
            coast_files = []
            for line in tmp.split('\n'):
                if collect_state and not line.strip().startswith('+++ mecoSHARK +++'):
                    coast_files.append(line.strip()[1:])
                if line.strip().startswith('+++ coastSHARK +++'):
                    collect_state = True
                if line.strip().startswith('+++ mecoSHARK +++'):
                    collect_state = False

            # get job from our precalculated dict and fetch its stdout log
            job = jobs[obj.commit]
            stdout = interface.get_output_log(job)

            new_lines = []
            parse_error_files = []
            for file in coast_files:
                for line in stdout:
                    if file in line and line.startswith(['Parser Error in file', 'Lexer Error in file']):
                        new_lines.append(file + ' ({})'.format(line))
                        parse_error_files.append(file)

            if set(parse_error_files) == set(coast_files):
                obj.coastSHARK = True
                modified += 1

            if new_lines:
                obj.text = '\n'.join(new_lines) + '\n----\n' + obj.text
                obj.save()

        self.stdout.write('Changed coastSHARK verification to True on {} of {} commits.'.format(modified, len(commits)))
