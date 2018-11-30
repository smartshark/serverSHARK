from smartshark.mongohandler import handler


def getPlugins():
    # Load the tables directly from the MongoDB
    schemas = {}
    query = handler.client.get_database(handler.database).get_collection('plugin_schema').find()

    plugins = {}
    for schema in query:
        name, version = schema["plugin"].split('_')
        version = version.split('.')  # Split into tuple
        if name in plugins:
            if version > plugins[name]:
                schemas[name] = schema

        else:
            schemas[name] = schema
            plugins[name] = version

    # Alternativ way to get the schema via the files of the plugin installations
    # for root, dirs, files in os.walk(plugin_path):
    #    for name in files:
    #        if name == 'schema.json':
    #            filepath = os.path.join(root, name)
    #            json1_file = open(filepath).read()
    #            json_data = json.loads(json1_file)
    #            schemas.append(json_data)
    return schemas


def findDependencyOfSchema(name, schemas, ground_dependencys=[]):
    dependencys = []
    for schema in schemas:
        for collection in schema['collections']:
            # For each field in the collection check if the field is a reference
            if(collection['collection_name'] not in ground_dependencys):
                for field in collection['fields']:
                    if('reference_to' in field and field['reference_to'] == name):
                        ground_dependencys.append(collection['collection_name'])
                        dependencys.append(SchemaReference(collection['collection_name'],field['field_name'], findDependencyOfSchema(collection['collection_name'],schemas, ground_dependencys)))

    return dependencys


def count_on_dependency_tree(tree, parent_id):

    ids = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id}).distinct('_id')
    count = len(ids)

    tree.count = tree.count + count
    for _id in ids:
        for deb in tree.dependencys:
            count_on_dependency_tree(deb, _id)


def delete_on_dependency_tree(tree, parent_id):

    ids = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id}).distinct('_id')
    count = len(ids)

    tree.count = tree.count + count
    for _id in ids:
        for deb in tree.dependencys:
            delete_on_dependency_tree(deb, _id)

    handler.client.get_database(handler.database).get_collection(tree.collection_name).delete_many({tree.field: parent_id})


def countOnDependencyTree(tree, parent_id):
    #print(handler.database)
    query = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id})
    count = query.count()
    # print(tree.collection_name)
    tree.count = tree.count + count
    for object in query:
        #print(object)
        #print(object.get('_id'))
        for deb in tree.dependencys:
            countOnDependencyTree(deb,object.get('_id'))


def deleteOnDependencyTree(tree, parent_id):
    query = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id})
    count = query.count()
    # print(tree.collection_name)
    tree.count = tree.count + count
    for object in query:
        #print(object)
        #print(object.get('_id'))
        for deb in tree.dependencys:
            deleteOnDependencyTree(deb,object.get('_id'))
    # Delete finally
    #if(tree.collection_name != 'project'):
    handler.client.get_database(handler.database).get_collection(tree.collection_name).delete_many({tree.field: parent_id})


class SchemaReference:

    def __init__(self, collection_name, field, deb):
        self.collection_name = collection_name
        self.field = field
        self.dependencys = deb
        self.count = 0

    def __repr__(self):
        return str(self.collection_name) + " --> " + str(self.field) + " Dependencys:" + str(self.dependencys)

    def __str__(self):
        return str(self.collection_name) + " --> " + str(self.field) + " Dependencys:" + str(self.dependencys)
