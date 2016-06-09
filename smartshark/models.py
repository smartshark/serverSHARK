from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_save, pre_save
from django import forms
from django.utils.deconstruct import deconstructible

from smartshark.mongohandler import handler
import inspect, os
from django.template.defaultfilters import filesizeformat
import magic
import tarfile
import json
from collections import Counter


@deconstructible
class FileValidator(object):
    error_messages = {
        'max_size': ("Ensure this file size is not greater than %(max_size)s."
                     " Your file size is %(size)s."),
        'min_size': ("Ensure this file size is not less than %(min_size)s. "
                     "Your file size is %(size)s."),
        'content_type': "Files of type %(content_type)s are not supported.",
        'tar_file': "Invalid tar file.",
        'info_file': "info.json not found in tar archive.",
        'schema_file': "schema.json not found in tar archive.",
        'schema_file_json': "schema.json is not parsable. Please put valid json in there.",
        'info_file_json': "info.json is not parsable. Please put valid json in there."
    }

    def __init__(self, max_size=None, min_size=None, content_types=()):
        self.max_size = max_size
        self.min_size = min_size
        self.content_types = content_types

    def __call__(self, data):
        if self.max_size is not None and data.size > self.max_size:
            params = {
                'max_size': filesizeformat(self.max_size),
                'size': filesizeformat(data.size),
            }
            raise ValidationError(self.error_messages['max_size'], 'max_size', params)

        if self.min_size is not None and data.size < self.min_size:
            params = {
                'min_size': filesizeformat(self.mix_size),
                'size': filesizeformat(data.size)
            }
            raise ValidationError(self.error_messages['min_size'], 'min_size', params)

        if self.content_types:
            content_type = magic.from_buffer(data.read(), mime=True)
            data.seek(0)
            if content_type.decode("utf-8") not in self.content_types:
                params = {'content_type': content_type}
                raise ValidationError(self.error_messages['content_type'], 'content_type', params)

            if content_type.decode("utf-8") == 'application/x-tar':
                try:
                    file = tarfile.open(fileobj=data)
                except tarfile.TarError as e:
                    raise ValidationError(self.error_messages['tar_file'], 'tar_file')

                if 'info.json' not in file.getnames():
                    raise ValidationError(self.error_messages['info_file'], 'info_file')
                else:
                    try:
                        info_json = json.loads(file.extractfile('info.json').read().decode('utf-8'))
                    except json.decoder.JSONDecodeError:
                        raise ValidationError(self.error_messages['info_file_json'], 'info_file_json')
                    self.check_info_json_structure(info_json)
                    self.check_info_json_requires_plugins_available(info_json)

                if 'schema.json' not in file.getnames():
                    raise ValidationError(self.error_messages['schema_file'], 'schema_file')
                else:
                    try:
                        json.loads(file.extractfile('schema.json').read().decode('utf-8'))
                    except json.decoder.JSONDecodeError:
                        raise ValidationError(self.error_messages['schema_file_json'], 'schema_file_json')

                data.seek(0)

    def check_info_json_structure(self, info_json):
        required_fields = ['name', 'author', 'version', 'abstraction_level', 'requires', 'arguments']
        for field in required_fields:
            if field not in info_json:
                raise ValidationError("%s not in info_json" % field, 'info_file_%s' % field)

        required_requires_fields = ['name', 'operator', 'version']
        for requires_fields in info_json['requires']:
            for field in required_requires_fields:
                if field not in requires_fields:
                    raise ValidationError("%s not in info_json requires attribute." % field, 'info_file_requires_%s'
                                          % field)

        required_requires_fields = ['name', 'required', 'position', 'type', 'description']
        for argument_fields in info_json['arguments']:
            for field in required_requires_fields:
                if field not in argument_fields:
                    raise ValidationError("%s not in info_json arguments attribute." % field, 'info_file_arugment_%s'
                                          % field)

    def check_info_json_requires_plugins_available(self, info_json):
        from smartshark.common import find_required_plugins
        for req_plugin in info_json['requires']:
            plugin = find_required_plugins(req_plugin)
            if plugin is None:
                raise ValidationError("Plugin requirements for this plugin can not be matched. Plugin %s "
                                      "with version %s %s is not in this database." % (req_plugin['name'],
                                                                                       req_plugin['operator'],
                                                                                       req_plugin['version']),
                                      'info_file_requirements')

    def __eq__(self, other):
        return isinstance(other, FileValidator)


class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    url = models.URLField(unique=True)
    clone_username = models.CharField(max_length=200, blank=True)


class Plugin(models.Model):
    ABSTRACTIONLEVEL_CHOICES = (
        ('rev', 'Revision'),
        ('repo', 'Repository'),
        ('other', 'Other'),
    )
    name = models.CharField(max_length=100)
    author = models.CharField(max_length=200)
    version = models.DecimalField(max_digits=5, decimal_places=2)
    abstraction_level = models.CharField(max_length=5, choices=ABSTRACTIONLEVEL_CHOICES)
    validate_file = FileValidator(max_size=1024*1024*50, content_types=('application/x-tar', 'application/octet-stream'))
    archive = models.FileField(upload_to="uploads/plugins/", validators=[validate_file])
    requires = models.ManyToManyField("self", blank=True)

    active = models.BooleanField(default=True)
    installed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('name', 'version',)

    def __str__(self):
        return self.name+"_"+str(self.version)

    @staticmethod
    def get_required_plugins_from_json(plugin_description):
        requires = []
        from smartshark.common import find_required_plugins
        for req_plugin in plugin_description['requires']:
            requires.append(find_required_plugins(req_plugin))

        return requires

    def load_from_json(self, plugin_description, archive):
        self.name = plugin_description['name']
        self.author = plugin_description['author']
        self.version = plugin_description['version']
        self.abstraction_level = plugin_description['abstraction_level']
        self.archive = archive

        try:
            self.full_clean()
        except ValidationError as e:
            raise e
        else:
            self.save()

            for db_plugin in self.get_required_plugins_from_json(plugin_description):
                self.requires.add(db_plugin)

            for argument in self.load_arguments_from_json(plugin_description):
                argument.save()

    def load_arguments_from_json(self, plugin_description):
        arguments = []
        for argument_desc in plugin_description['arguments']:
                argument = Argument()
                argument.name = argument_desc['name']
                argument.required = argument_desc['required']
                argument.position = argument_desc['position']
                argument.type = argument_desc['type']
                argument.description = argument_desc['description']
                argument.plugin = self

                try:
                    argument.full_clean()
                except ValidationError as e:
                    raise e
                else:
                    arguments.append(argument)

        return arguments

class Argument(models.Model):
    TYPE_CHOICES = (
        ('install', 'Installation Argument'),
        ('execute', 'Execution Argument'),
    )
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=250)
    required = models.BooleanField()
    position = models.IntegerField()
    type = models.CharField(max_length=7, choices=TYPE_CHOICES)
    plugin = models.ForeignKey(Plugin, on_delete=models.CASCADE)


class PluginExecution(models.Model):
    STATUS_CHOICES = (
        ('queue', 'In Queue'),
        ('running', 'Running'),
        ('finished', 'Finished'),
        ('error', 'Error'),
    )
    plugin = models.ForeignKey(Plugin)
    project = models.ForeignKey(Project)
    added_at = models.DateTimeField(auto_now_add=True)
    submission_value = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES)


class MongoRole(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class SmartsharkUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    roles = models.ManyToManyField(MongoRole, blank=True)

    def __str__(self):
        return self.user.username

    @staticmethod
    @receiver(post_save, sender=User)
    def create_profile(sender, **kwargs):
        user = kwargs["instance"]
        if kwargs["created"]:
            up = SmartsharkUser(user=user)
            up.save()

    @receiver(pre_save, sender=User)
    def get_user_in_signal(sender, **kwargs):
        user = kwargs["instance"]
        for entry in reversed(inspect.stack()):
            if entry[1].endswith('/django/contrib/admin/sites.py'):
                print("in")
                try:
                    password = entry[0].f_locals['request'].POST.get('password1')
                except:
                    password = None
                break
        handler.update_user(username=user.username, password=password, roles=[])


