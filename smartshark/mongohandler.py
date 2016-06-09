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

        self.client = MongoClient(host=self.address, port=self.port)
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

handler = MongoHandler()