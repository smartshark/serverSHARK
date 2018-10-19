from django.core.management.base import BaseCommand
from smartshark.models import Project
from smartshark.utils import projectUtils
from bson.objectid import ObjectId
import sys

class Command(BaseCommand):
    help = 'Deletes all data of a project'


    def handle(self, *args, **options):
        for p in Project.objects.all():
            print(p.name)
        try:
           l = input("Which project should be deleted?")
           project = Project.objects.all().get(name=l)
           print("Calculate data tree for ",project.name)
        except Project.DoesNotExist or Project.MultipleObjectsReturned:
           self.stdout.write(self.style.ERROR('Project not found'))
           sys.exit(-1)

        schemas = projectUtils.getPlugins()

        # Analyze the schema
        deb = []
        x = projectUtils.findDependencyOfSchema('project', schemas.values(), [])
        schemaProject = projectUtils.SchemaReference('project', '_id', x)
        deb.append(schemaProject)

        projectUtils.countOnDependencyTree(schemaProject,ObjectId(project.mongo_id))

        self.printDependencyTree(deb, project)

        l = input("Continue with data deletion? (y/n)")
        if(l == "yes" or l == "y"):

            projectUtils.deleteOnDependencyTree(schemaProject,ObjectId(project.mongo_id))
            self.stdout.write(self.style.SUCCESS('Successfully deleted project data'))
        else:
            self.stdout.write(self.style.ERROR('No data deleted'))

    def printDependencyTree(self, deb, project):
        print("Project data of ", project.name)
        for dependency in deb:
            print(dependency.collection_name, " ", "(", dependency.count, ")")
            self.printSubDep(dependency.dependencys,1)

    def printSubDep(self, deb, depth):
        for dependency in deb:
            print("  " * (depth -1),"└──",dependency.collection_name, " ", "(", dependency.count, ")")
            self.printSubDep(dependency.dependencys,depth+1)