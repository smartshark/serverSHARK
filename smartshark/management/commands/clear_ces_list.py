#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from django.core.management.base import BaseCommand

from smartshark.models import Project
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
        # commits = CommitVerification.objects.filter(project=project).filter(Q(mecoSHARK=False) | Q(coastSHARK=False))

        if len(commits) == 0:
            self.stderr.write('No verification data!')
            return

        l = input("Delete CES lists on {} commits? (y/N)".format(len(commits)))
        if l.lower() != 'y':
            return

        revisions = []
        vcs = commits[0].vcs_system

        for cv in commits:
            if cv.vcs_system != vcs:
                self.stderr.write('Multiple VCS Systems found!')
                return

            revisions.append(cv.commit)

        revisions = ','.join(revisions)

        logger.info('Setting code_entity_states to an empty list for these commits: {}'.format(revisions))
        del_list_count, changed_commit_id_count, should_change_commit_ids, childs = handler.clear_code_entity_state_lists(revisions, cv[0].vcs_system)
        logger.info('Deleted code_entity_states list for {} commits, changed commit_id on {}/{} code entity states for {} childs'.format(del_list_count, changed_commit_id_count, should_change_commit_ids, childs))

        self.stdout.write('Deleted code_entity_states list for {} commits, changed commit_id on {}/{} code entity states for {} childs'.format(del_list_count, changed_commit_id_count, should_change_commit_ids, childs))

        with open('./revisions_to_change', 'w') as f:
            f.write(revisions)
        self.stdout.write(revisions)
