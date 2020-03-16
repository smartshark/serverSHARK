#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from django.db import connections
from django.core.management.base import BaseCommand

from smartshark.models import Project, CommitVerification
from smartshark.mongohandler import handler
from smartshark.datacollection.executionutils import get_revisions_for_failed_verification

logger = logging.getLogger('django')


class Command(BaseCommand):
    """This clears CodeEntityState lists from specified commits"""

    help = 'Clear CES list on commits where at least one verification failed (coast or meco)'

    def add_arguments(self, parser):
        parser.add_argument('project_name', type=str)

    def handle(self, *args, **options):
        if not options['project_name']:
            self.stdout.write('need project name')

        project = Project.objects.get(name__iexact=options['project_name'])

        # get commits where at least one plugin failed
        commits = get_revisions_for_failed_verification(project)

        if len(commits) == 0:
            self.stderr.write('No verification data!')
            return

        l = input("Delete CES lists on {} commits? (y/N)".format(len(commits)))
        if l.lower() != 'y':
            return

        connections['default'].close()
        cv = CommitVerification.objects.get(project=project, commit=commits[0])
        revisions = ','.join(commits)

        logger.info('Setting code_entity_states to an empty list for these commits: {}'.format(revisions))
        del_list_count, changed_commit_id_count, should_change_commit_ids, childs = handler.clear_code_entity_state_lists(revisions, cv.vcs_system)
        logger.info('Deleted code_entity_states list for {} commits, changed commit_id on {}/{} code entity states for {} childs'.format(del_list_count, changed_commit_id_count, should_change_commit_ids, childs))

        self.stdout.write('Deleted code_entity_states list for {} commits, changed commit_id on {}/{} code entity states for {} childs'.format(del_list_count, changed_commit_id_count, should_change_commit_ids, childs))

        with open('./revisions_to_change', 'w') as f:
            f.write(revisions)

        self.stdout.write('Revisions written to file ./revisions_to_change')
