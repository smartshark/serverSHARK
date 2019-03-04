from collections import OrderedDict

from pymongo import MongoClient
from bson.objectid import ObjectId
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

    def get_plugin_schemas(self):
        schemas =  self.client.get_database(self.database).get_collection(self.schema_collection).find()
        return [schema for schema in schemas]

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

    def get_number_of_projects(self):
        return self.client.get_database(self.database).get_collection('project').count()

    def get_number_of_commits(self, vcs_system_id=None):
        if vcs_system_id is None:
            return self.client.get_database(self.database).get_collection('commit').count()
        else:
            return self.client.get_database(self.database).get_collection('commit').find(
                {'vcs_system_id': vcs_system_id}).count()

    def get_number_of_people(self):
        return self.client.get_database(self.database).get_collection('people').count()

    def get_number_of_refactorings(self):
        return self.client.get_database(self.database).get_collection('refactoring').count()

    def get_number_of_mailing_messages(self, mailing_list_id=None):
        if mailing_list_id is None:
            return self.client.get_database(self.database).get_collection('message').count()
        else:
            return self.client.get_database(self.database).get_collection('message').find(
                {'mailing_list_id': mailing_list_id}).count()

    def get_number_of_issues(self, issue_system_id=None):
        if issue_system_id is None:
            return self.client.get_database(self.database).get_collection('issue').count()
        else:
            return self.client.get_database(self.database).get_collection('issue').find(
                {'issue_system_id': issue_system_id}).count()

    def get_number_of_issue_comments(self, issue_id=None):
        if issue_id is None:
            return self.client.get_database(self.database).get_collection('issue_comment').count()
        else:
            return self.client.get_database(self.database).get_collection('issue_comment').find(
                {'issue_id': issue_id}).count()

    def get_number_of_issue_systems(self, project_id=None):
        if project_id is None:
            return self.client.get_database(self.database).get_collection('issue_system').count()
        else:
            return self.client.get_database(self.database).get_collection('issue_system').find(
                {'project_id': project_id}).count()

    def get_number_of_vcs_systems(self, project_id=None):
        if project_id is None:
            return self.client.get_database(self.database).get_collection('vcs_system').count()
        else:
            return self.client.get_database(self.database).get_collection('vcs_system').find(
                {'project_id': project_id}).count()

    def get_number_of_mailing_lists(self, project_id=None):
        if project_id is None:
            return self.client.get_database(self.database).get_collection('mailing_list').count()
        else:
            return self.client.get_database(self.database).get_collection('mailing_list').find(
                {'project_id': project_id}).count()

    def get_number_of_issue_events(self, issue_id=None):
        if issue_id is None:
            return self.client.get_database(self.database).get_collection('event').count()
        else:
            return self.client.get_database(self.database).get_collection('event').find(
                {'issue_id': issue_id}).count()

    def get_number_of_clones(self, commit_id=None):
        if commit_id is None:
            return self.client.get_database(self.database).get_collection('code_group_state').count()
        else:
            return self.client.get_database(self.database).get_collection('code_group_state').find(
                {'commit_id': commit_id}).count()

    def get_number_of_hunks(self, file_action=None):
        if file_action is None:
            return self.client.get_database(self.database).get_collection('hunk').count()
        else:
            return self.client.get_database(self.database).get_collection('hunk').find(
                {'file_action_id': file_action}).count()

    def get_number_of_file_changes(self, commit_id=None):
        if commit_id is None:
            return self.client.get_database(self.database).get_collection('file_action').count()
        else:
            return self.client.get_database(self.database).get_collection('file_action').find(
                {'commit_id': commit_id}).count()

    def get_number_of_code_group_states(self, commit_id=None):
        if commit_id is None:
            return self.client.get_database(self.database).get_collection('clone_instance').count()
        else:
            return self.client.get_database(self.database).get_collection('clone_instance').find(
                {'commit_id': commit_id}).count()

    def get_number_of_code_entity_states(self, commit_id=None):
        if commit_id is None:
            return self.client.get_database(self.database).get_collection('code_entity_state').count()
        else:
            return self.client.get_database(self.database).get_collection('code_entity_state').find(
                {'commit_id': commit_id}).count()

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
                self.client.get_database('admin').command('shardCollection', self.database + '.' + name, key=ordered_dict,
                                                          unique=unique)
            except:
                pass

    def get_revisions_for_url(self, vcs_system_url):
        vs = self.client.get_database(self.database).get_collection('vcs_system').find_one({'url': vcs_system_url})
        return self.client.get_database(self.database).get_collection('commit').find({'vcs_system_id': vs['_id']}, {'revision_hash': 1})

    def get_vcs_url_for_project_id(self, mongo_id):
        url = None
        urls = self.client.get_database(self.database).get_collection('vcs_system').find({'project_id': ObjectId(mongo_id)}, {'url': 1})
        try:
            url = urls[0]['url']
        except IndexError:
            pass
        return url

    def clear_code_entity_state_lists(self, revision_hashes, vcs_system_url):
        revision_hashes = revision_hashes.split(',')
        vs = self.client.get_database(self.database).get_collection('vcs_system').find_one({'url': vcs_system_url})

        # new changes
        # 1. find all childs where the parent is in the list that are not themselves contained in the list
        # 2. for each child get the CES from the list and check if the commit_id is in the list of commits where we delete the code_entity_states
        # 3. if yes change the commit_id to the childs id

        # 1
        childs = self.client.get_database(self.database).get_collection('commit').find({'vcs_system_id': ObjectId(vs['_id']), 'parents': {'$in': revision_hashes}, 'revision_hash': {'$nin': revision_hashes}})

        # prefetch the commit_ids for our revision_hashes for 2,3
        commit_ids = [ObjectId(c['_id']) for c in self.client.get_database(self.database).get_collection('commit').find({'vcs_system_id': ObjectId(vs['_id']), 'revision_hash': {'$in': revision_hashes}}, {'_id': 1})]

        # 2, 3
        changed_commit_ids = 0
        num_childs = 0
        for c in childs:
            update_result_commit = self.client.get_database(self.database).get_collection('code_entity_state').update_many({'_id': {'$in': c['code_entity_states']}, 'commit_id': {'$in': commit_ids}}, {'$set': {'commit_id': c['_id']}})
            changed_commit_ids += update_result_commit.matched_count
            num_childs += 1

        # delete code_entity_states
        update_result = self.client.get_database(self.database).get_collection('commit').update_many({'revision_hash': {'$in': revision_hashes}, 'vcs_system_id': vs['_id']}, {'$set': {'code_entity_states': []}})
        return update_result.matched_count, changed_commit_ids, num_childs


handler = MongoHandler()
