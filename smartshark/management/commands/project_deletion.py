from django.core.management.base import BaseCommand
from smartshark.models import Project
from smartshark.views import collection
from bson.objectid import ObjectId
import sys

class Command(BaseCommand):
    help = 'Closes the specified poll for voting'


    def handle(self, *args, **options):
        for p in Project.objects.all():
            print(p.name)
        print("Which project should be deleted?")
        try:
           l = sys.stdin.readline()
           project = Project.objects.all().get(name=l.strip())
           print("Calculate data tree for ",project.name)
        except Project.DoesNotExist or Project.MultipleObjectsReturned:
           self.stdout.write(self.style.ERROR('Project not found'))
           sys.exit(-1)

        schemas = collection.getPlugins()

        # Analyze the schema
        deb = []
        x = collection.findDependencyOfSchema('project', schemas.values(), [])
        schemaProject = collection.SchemaReference('project', '_id', x)
        deb.append(schemaProject)

        collection.countOnDependencyTree(schemaProject,ObjectId(project.mongo_id))

        self.printDependencyTree(deb, project)

        print("Continue with data deletion? (y/n)")
        l = sys.stdin.readline()
        if(l.strip() == "yes" or l.strip() == "y"):

            collection.deleteOnDependencyTree(schemaProject,ObjectId(project.mongo_id))
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