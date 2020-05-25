#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from django.core.management.base import BaseCommand
from django.db import connections
from bson.objectid import ObjectId

from smartshark.models import Project
from smartshark.utils import projectUtils
from smartshark.utils.projectUtils import delete_file_from_gridfs_for_project


class Command(BaseCommand):
    help = 'Deletes all data of a project'

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

        schemas = projectUtils.getPlugins()

        # Analyze the schema
        deb = []
        x = projectUtils.findDependencyOfSchema('project', schemas.values(), [])
        project_schema = projectUtils.SchemaReference('project', '_id', x)
        deb.append(project_schema)

        projectUtils.count_on_dependency_tree(project_schema, ObjectId(project.mongo_id))
        self._print_dependency_tree(deb, project)

        while True:
            l = input("Continue with data deletion? (y/n) ")
            if l=="yes" or l=="y":
                self.stdout.write('Deleting project from the MongoDB')

                # Before everything else we need to delete the file from the gridfs
                delete_file_from_gridfs_for_project(ObjectId(project.mongo_id))

                projectUtils.delete_on_dependency_tree(project_schema, ObjectId(project.mongo_id))
                self.stdout.write(self.style.SUCCESS('Successfully deleted project from the MongoDB'))

                connections['default'].close()

                self.stdout.write('Deleting project from the serverSHARK')
                project.delete()
                self.stdout.write(self.style.SUCCESS('Successfully deleted project from the serverSHARK'))
                break
            elif l=="no" or l=="n":
                self.stdout.write(self.style.ERROR('No data deleted'))
                break
            else:
                self.stdout.write(self.style.ERROR('Only (y)es and (n)o accepted'))

    def _print_dependency_tree(self, deb, project):
        self.stdout.write("Project data of {}".format(project.name))
        for dependency in deb:
            self.stdout.write('{} ({})'.format(dependency.collection_name, dependency.count))
            self._print_sub_dependency(dependency.dependencys, 1)

    def _print_sub_dependency(self, deb, depth):
        for dependency in deb:
            self.stdout.write('{} └── {} ({})'.format('  ' * (depth - 1), dependency.collection_name, dependency.count))
            self._print_sub_dependency(dependency.dependencys, depth + 1)
