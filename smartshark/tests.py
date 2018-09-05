import json
import os
from bson.json_util import loads
from bson.objectid import ObjectId

from django.test import TestCase

from smartshark.views import collection
from smartshark.mongohandler import handler

DATABASE_NAME = "smartshark_unittest"
PROJECT_DELETE = "zookeeper-testdelete"

# Create your tests here.
class TestDataDeletionBasic(TestCase):
#    "Basic tests"

    def test_schemaCreator(self):
        schemas = []

        module_dir = os.path.dirname(__file__)
        file_path = os.path.join(module_dir, "test/schema-test.json")
        json1_file = open(file_path).read()
        json_data = json.loads(json1_file)
        schemas.append(json_data)
        x = collection.findDependencyOfSchema('project', schemas, [])
        schemaProject = collection.SchemaReference('project', '_id', x)

        # Struktur des Test JSON
        # project
        #   -> test
        #      -> file
        #      -> file_action
        #            -> hunk
        #   -> testtest

        assert schemaProject.collection_name == 'project'
        assert len(schemaProject.dependencys) == 2

        assert schemaProject.dependencys[0].collection_name == 'test'
        assert len(schemaProject.dependencys[0].dependencys) == 2

        test = schemaProject.dependencys[0]

        assert test.dependencys[0].collection_name == 'file'
        assert len(test.dependencys[0].dependencys) == 0

        assert test.dependencys[1].collection_name == 'file_action'
        assert len(test.dependencys[1].dependencys) == 1

        file_action = test.dependencys[1]

        assert file_action.dependencys[0].collection_name == 'hunk'
        assert len(file_action.dependencys[0].dependencys) == 0

        assert schemaProject.dependencys[1].collection_name == 'testtest'
        assert len(schemaProject.dependencys[1].dependencys) == 0


class MongoDBIntegrationBasicTest(TestCase):

    def setUp(self):
        print("Create Test-Database")

        handler.database = DATABASE_NAME

        handler.client.drop_database(DATABASE_NAME)
        self.testDatabase = handler.client[DATABASE_NAME]

        print("Import data")
        module_dir = os.path.dirname(__file__)
        file_path = os.path.join(module_dir, "test/database-seed")
        for root, dirs, files in os.walk(file_path):
             for name in files:
                if name.endswith('.json'):
                   print("Loading file " + name + "...")
                   filepath = os.path.join(root, name)
                   collection_name = name.replace('.json','')
                   collection_c = self.testDatabase[collection_name]

                   with open(filepath) as f:
                       raw_json_data = loads(f.read())

                   collection_c.insert(raw_json_data)


    def tearDown(self):
        print("Delete Test-Database")
        handler.client.drop_database(DATABASE_NAME)


class TestDataDeletionOnProject(MongoDBIntegrationBasicTest):

    def testDeletionOfProject(self):
        print("delete project")
        schemas = collection.getPlugins()

        # Analyze the schema
        x = collection.findDependencyOfSchema('project', schemas.values(), [])
        schemaProject = collection.SchemaReference('project', '_id', x)

        project_id_to_delete = ""

        # Calculate initial magic numbers (= the total count of data)
        initial = {}
        for data in self.testDatabase['project'].find():
            count = self.calculateMagicNumberOfProject(schemaProject,data['_id'])
            initial[data['name']] = count
            if data['name'] == PROJECT_DELETE:
                project_id_to_delete = data['_id']

        print("Before Delete:" + json.dumps(initial))

        # Delete Project
        collection.deleteOnDependencyTree(schemaProject,project_id_to_delete)

        schemas = collection.getPlugins()

        # Analyze the schema
        x = collection.findDependencyOfSchema('project', schemas.values(), [])
        schemaProject = collection.SchemaReference('project', '_id', x)
        # Calculate the magic numbers (= the total count of data) after the deletion of one project
        afterDelete = {}
        for data in self.testDatabase['project'].find():
            count = self.calculateMagicNumberOfProject(schemaProject,data['_id'])
            afterDelete[data['name']] = count

        print("After Delete:" + json.dumps(afterDelete))

        # Final compare
        for data in self.testDatabase['project'].find():
            if data['name'] == PROJECT_DELETE:
                if initial[data['name']] == 0:
                    print("Warning: The project that should be deleted has 0 data entries in the DB...")
                assert afterDelete[data['name']] == 0
            else:
                assert initial[data['name']] == afterDelete[data['name']]

    def calculateMagicNumberOfProject(self, schemaProject, projectID):
        collection.countOnDependencyTree(schemaProject, ObjectId(projectID))
        number = self.calculateNumber(schemaProject)
        return number

    def calculateNumber(self, tree):
        localCount = 0
        for deb in tree.dependencys:
            localCount = localCount + self.calculateNumber(deb)
        localCount = localCount + tree.count
        tree.count = 0
        return localCount