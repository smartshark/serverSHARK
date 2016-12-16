from collections import OrderedDict

from pymongo import MongoClient
from pymongo.errors import OperationFailure

import server.settings


class MongoHandler(object):
    def __init__(self):
        self.address = server.settings.DATABASES['mongodb']['HOST']
        self.port = server.settings.DATABASES['mongodb']['PORT']
        self.user = server.settings.DATABASES['mongodb']['USER']
        self.password = server.settings.DATABASES['mongodb']['PASSWORD']
        self.database = server.settings.DATABASES['mongodb']['NAME']
        self.authentication_database = server.settings.DATABASES['mongodb']['AUTHENTICATION_DB']
        self.schema_collection = server.settings.DATABASES['mongodb']['PLUGIN_SCHEMA_COLLECTION']

        self.client = MongoClient(host=self.address, port=self.port)
        if self.user is not None and self.password is not None and self.authentication_database is not None:
            self.client[self.database].authenticate(self.user, self.password, source=self.authentication_database)

    def add_user(self, username, password, roles):
        self.client[self.database].add_user(name=username, password=password, roles=roles)

    def update_user(self, username, password, roles):
        if password is not None:
            try:
                self.remove_user(username)
            except OperationFailure as e:
                pass

            self.add_user(username, password, roles)

    def remove_user(self, username):
        self.client[self.database].remove_user(username)

    def update_roles(self, username, roles):
        self.client[self.database]._create_or_update_user(False, username, None, False, roles=roles)

    def add_project(self, project):
        return self.client.get_database(self.database).get_collection('project')\
            .insert_one({'name': project.name}).inserted_id

    def delete_project(self, project):
        self.client.get_database(self.database).get_collection('project').delete_one({'name': project.name})

    def add_schema(self, plugin_schema, plugin):
        plugin_schema['plugin'] = str(plugin)
        self.client.get_database(self.database).get_collection(self.schema_collection).insert_one(plugin_schema)

    def delete_schema(self, plugin):
        self.client.get_database(self.database).get_collection(self.schema_collection)\
            .find_one_and_delete({'plugin': str(plugin)})

    def create_and_shard_collections(self, created_collections):
        for collection in created_collections:
            name = collection['name']
            unique = collection.get('unique', False)
            shard_keys = collection['shard_key']
            ordered_dict = OrderedDict()
            for shard_key in shard_keys:
                ordered_dict.update(shard_key)

            # Create collection, if it is already existent --> ignore it
            try:
                self.client.get_database(self.database).create_collection(name)
                self.client.get_database('admin').command('shardCollection', self.database+'.'+name, key=ordered_dict,
                                                          unique=unique)
            except:
                pass


handler = MongoHandler()