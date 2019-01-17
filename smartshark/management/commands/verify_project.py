#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from django.core.management.base import BaseCommand

from smartshark.models import Project
from smartshark.mongohandler import handler
from smartshark.utils.projects import create_local_repo_for_project


class Command(BaseCommand):
    help = 'Verify a project'

    def handle(self, *args, **options):
        for p in Project.objects.all():
            self.stdout.write(p.name)
        try:
            l = input("Which project should be deleted? ")
            project = Project.objects.all().get(name__iexact=l)
            self.stdout.write("Calculate data tree for {}".format(project.name))
        except (Project.DoesNotExist, Project.MultipleObjectsReturned) as e:
            self.stdout.write(self.style.ERROR('Error loading project: {}'.format(e)))
            sys.exit(-1)

        path = "../tmp-repo"
        db = handler.client.smartshark
        projectMongo = db.project.find_one({"name": project.name})
        print(projectMongo["_id"])
        vcsMongo = db.vcs_system.find_one({"project_id": projectMongo["_id"]})
        #if vcsMongo == None or vcsMongo["repository_type"] != 'git':
        #    self.stdout.write(self.style.ERROR('Error: repository is not a git repository'))
        #    sys.exit(-1)
        # 1. Checkout the project


        repo = create_local_repo_for_project(vcsMongo, path)
        if not repo.is_empty:
            # 2. Iterate over the commits
        # 3. Iterate foreach commit over the files
        # 4. Verfiy, that the files are in the database
