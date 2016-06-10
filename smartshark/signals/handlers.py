import os

from smartshark.hpchandler import HPCHandler
from smartshark.models import SmartsharkUser, Plugin
from django.db.models.signals import post_save, pre_save, m2m_changed, post_delete, pre_delete
from django.dispatch import receiver
import tarfile

from smartshark.mongohandler import handler


@receiver(m2m_changed, sender=SmartsharkUser.roles.through)
def add_roles(sender, **kwargs):
    if kwargs['action'] == 'post_remove' or kwargs['action'] == 'post_add':
        user = kwargs["instance"]
        roles = [role.name for role in user.roles.all()]
        handler.update_roles(user.user.username, roles)


@receiver(post_delete, sender=Plugin)
def delete_archive(sender, **kwargs):
    plugin = kwargs["instance"]
    os.remove(plugin.get_full_path_to_archive())

    # delete plugin on hpc
    hpc_handler = HPCHandler()
    hpc_handler.delete_plugin(plugin)