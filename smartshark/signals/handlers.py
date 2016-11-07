import os

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.models import SmartsharkUser, Plugin, Project
from django.db.models.signals import post_save, pre_save, m2m_changed, post_delete, pre_delete
from django.dispatch import receiver
import tarfile

from smartshark.mongohandler import handler


interface = PluginManagementInterface.find_correct_plugin_manager()

@receiver(m2m_changed, sender=SmartsharkUser.roles.through)
def add_roles(sender, **kwargs):
    if kwargs['action'] == 'post_remove' or kwargs['action'] == 'post_add':
        user = kwargs["instance"]
        roles = [role.name for role in user.roles.all()]
        handler.update_roles(user.user.username, roles)


@receiver(post_delete, sender=Plugin)
def delete_archive(sender, **kwargs):
    plugin = kwargs["instance"]
    try:
        os.remove(plugin.get_full_path_to_archive())
    except FileNotFoundError:
        pass

    # delete plugin on bash system
    interface.delete_plugins([plugin])

    # delete schema
    handler.delete_schema(plugin)

@receiver(pre_save, sender=Project)
def add_project_to_mongodb(sender, **kwargs):
    project = kwargs["instance"]
    mongo_id = handler.add_project(project)
    project.mongo_id = str(mongo_id)


@receiver(post_delete, sender=Project)
def delete_project_from_mongodb(sender, **kwargs):
    project = kwargs["instance"]
    handler.delete_project(project)
