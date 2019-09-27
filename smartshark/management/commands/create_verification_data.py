#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import tempfile

from django.core.management.base import BaseCommand
from django.db import connections

from smartshark.models import Project, CommitVerification
from smartshark.mongohandler import handler
from smartshark.utils.projectUtils import create_local_repo_for_project, get_all_commits_of_repo, get_commit_from_database


class Command(BaseCommand):
    help = 'Create verification data for a project'

    db = handler.client.smartshark

    def handle(self, *args, **options):
        for p in Project.objects.all():
            self.stdout.write(p.name)
        try:
            l = input("Which project should be verified? ")
            project = Project.objects.all().get(name__iexact=l)
            self.stdout.write("Verfiy project {}".format(project.name))
        except (Project.DoesNotExist, Project.MultipleObjectsReturned) as e:
            self.stdout.write(self.style.ERROR('Error loading project: {}'.format(e)))
            sys.exit(-1)

        self.use_meme = True
        l2 = input('did memeSHARK run for project {}? (Y/n)'.format(project.name))
        if l2.lower() == 'n':
            self.use_meme = False
        self.stdout.write('Assuming memeSHARK {}'.format(self.use_meme))

        with tempfile.TemporaryDirectory() as path:
            projectMongo = self.db.project.find_one({"name": project.name})
            vcsMongo = self.db.vcs_system.find_one({"project_id": projectMongo["_id"]})

            l = input("Delete old verification data first? (y/N)")
            if l.lower() == 'y':
                CommitVerification.objects.filter(project=project).delete()
                self.stdout.write("Deleted old verification data")

            repo = create_local_repo_for_project(vcsMongo, path)
            if not repo.is_empty:

                allCommits = get_all_commits_of_repo(vcsMongo, repo)
                self.stdout.write("Found {} commits for the project".format(len(allCommits)))

                # close connection because the above may take a long time
                connections['default'].close()

                # 2. Iterate over the commits
                for commit in allCommits:
                    # print("Commit " + commit)

                    try:
                        resultModel = CommitVerification.objects.get(project=project, vcs_system=vcsMongo['url'], commit=str(commit))
                    except CommitVerification.DoesNotExist:
                        resultModel = CommitVerification()
                        resultModel.project = project
                        resultModel.vcs_system = vcsMongo['url']
                        resultModel.commit = str(commit)

                    resultModel.text = ""

                    db_commit = get_commit_from_database(self.db, commit, vcsMongo["_id"])

                    # Basic validation wihtout checkout the version
                    if not db_commit:
                        print('commit {} not in database, skipping validation'.format(commit))
                        continue
                    resultModel.save()

        self.stdout.write('Verification data created.')
