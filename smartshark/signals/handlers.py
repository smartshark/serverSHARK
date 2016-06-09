from smartshark.models import SmartsharkUser, Plugin
from django.db.models.signals import post_save, pre_save, m2m_changed
from django.dispatch import receiver
import tarfile

from smartshark.mongohandler import handler


@receiver(m2m_changed, sender=SmartsharkUser.roles.through)
def add_roles(sender, **kwargs):
    if kwargs['action'] == 'post_remove' or kwargs['action'] == 'post_add':
        user = kwargs["instance"]
        roles = [role.name for role in user.roles.all()]
        handler.update_roles(user.user.username, roles)


@receiver(pre_save, sender=Plugin)
def read_data(sender, **kwargs):
    plugin = kwargs["instance"]

    #print(kwargs)