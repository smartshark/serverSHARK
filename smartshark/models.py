from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_save, pre_save
from django import forms
from django.utils.deconstruct import deconstructible

from server import settings
from smartshark.mongohandler import handler
import inspect, os
from django.template.defaultfilters import filesizeformat
import magic
import tarfile
import json
from collections import Counter

from smartshark.pluginhandler import PluginInformationHandler


@deconstructible
class FileValidator(object):
    error_messages = {
        'max_size': ("Ensure this file size is not greater than %(max_size)s."
                     " Your file size is %(size)s."),
        'min_size': ("Ensure this file size is not less than %(min_size)s. "
                     "Your file size is %(size)s."),
        'content_type': "Files of type %(content_type)s are not supported.",
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
                plugin_handler = PluginInformationHandler(data)
                plugin_handler.validate_tar()
                data.seek(0)

    def __eq__(self, other):
        return isinstance(other, FileValidator)

class Project(models.Model):
    name = models.CharField(max_length=100, unique=True)
    url = models.URLField(unique=True)
    clone_username = models.CharField(max_length=200, blank=True)
    mongo_id = models.CharField(max_length=50, blank=True)

    class Meta:
        permissions = (
            ("start_collection", "Starts the collection process for projects"),
        )

    def __str__(self):
        return self.name


class Plugin(models.Model):
    ABSTRACTIONLEVEL_CHOICES = (
        ('rev', 'Revision'),
        ('repo', 'Repository'),
        ('other', 'Other'),
    )
    name = models.CharField(max_length=100)
    author = models.CharField(max_length=200)
    version = models.DecimalField(max_digits=5, decimal_places=2)
    description = models.CharField(max_length=400)
    abstraction_level = models.CharField(max_length=5, choices=ABSTRACTIONLEVEL_CHOICES)
    validate_file = FileValidator(max_size=1024*1024*500, content_types=('application/x-tar', 'application/octet-stream'))
    archive = models.FileField(upload_to="uploads/plugins/", validators=[validate_file])
    requires = models.ManyToManyField("self", blank=True, symmetrical=False)

    active = models.BooleanField(default=False)
    installed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('name', 'version',)
        permissions = (
            ("install_plugin", "Permission to install plugins."),
        )

    def __str__(self):
        return self.name+"_"+str(self.version)

    def __eq__(self, other):
        if self.name == other.name and self.version == other.version:
            return True

        return False

    def get_revision_hashes_of_failed_jobs_for_project(self, project):
        """
        We want to get all revision hashes of jobs that failed for this plugin and the given project. Thats why
        we go thorugh all plugin executions of this plugin and collect all done jobs (=NOT FAILED) and exit jobs (=FAILED).

        We only put the revision_hash of the job into the list if a job for this plugin and project always failed.

        E.g.,
                1 2 3 4 5 6 7 8 9
        1. run: x x x f f x f x f
        2. run: f f x x f x f x f

        => would get revision hashes of 5,7, and 9

        3. run: f f f f x f x f f

        => would return revision hash of 9


        :param project: project on which plugin is executed
        :return:
        """
        revisions = set()

        # Get all plugin executions for this plugin and project
        plugin_executions = self.pluginexecution_set.all().filter(project=project, plugin=self)
        for plugin_execution in plugin_executions:
            # For each plugin_execution get all done_jobs and their revisions
            done_jobs_revisions = plugin_execution.job_set.all().filter(status='DONE').order_by('revision_hash')\
                .values_list('revision_hash', flat=True).distinct()

            # Get all revisions of exit jobs
            exit_jobs_revisions = plugin_execution.job_set.all().filter(status='EXIT').order_by('revision_hash')\
                .values_list('revision_hash', flat=True).distinct()

            # For each plugin execution get all error jobs. If this job is also in done_jobs then ignore it
            difference_set = set(exit_jobs_revisions) - set(done_jobs_revisions)
            revisions = revisions.union(difference_set)

        return revisions

    def get_all_jobs_for_project(self, project):
        jobs = []
        plugin_executions = PluginExecution.objects.all().filter(project=project, plugin=self)
        for plugin_execution in plugin_executions:
            jobs.extend(Job.objects.all().filter(plugin_execution=plugin_execution))

        return jobs

    def get_substitution_plugin_for(self, plugin):
        # Read the information in again from the tar archive
        plugin_handler = PluginInformationHandler(self.get_full_path_to_archive())
        info_file = plugin_handler.get_info()
        fitting_plugin = None

        # Go through all plugins that are required, to find the one that must be substituted
        for info_req_plugins in info_file['requires']:
            if info_req_plugins['name'] == plugin.name:
                # Get all plugins that match the statement in the json file
                substitution_plugins = plugin_handler.find_required_plugins(info_req_plugins)
                # Delete the plugin that is possibly already there as match
                available_plugins = [avail_plugin for avail_plugin in substitution_plugins if avail_plugin != plugin]
                if available_plugins:
                    # Find the best plugin
                    fitting_plugin = max(available_plugins, key=lambda x:x.version)

        return fitting_plugin

    def get_full_path_to_archive(self):
        return os.path.join(settings.MEDIA_ROOT, self.archive.name)

    def get_install_arguments(self):
        return self.argument_set.filter(type='install').order_by('position')

    def get_name_of_archive(self):
        return os.path.basename(os.path.normpath(self.archive.name))

    def get_required_plugins(self):
        plugin_handler = PluginInformationHandler(self.get_full_path_to_archive())
        info_file = plugin_handler.get_info()
        return [in_info_file_specified for in_info_file_specified in info_file['requires']]

    def load_from_json(self, archive):
        plugin_handler = PluginInformationHandler(archive)
        info_json = plugin_handler.get_info()
        self.name = info_json['name']
        self.author = info_json['author']
        self.version = info_json['version']
        self.abstraction_level = info_json['abstraction_level']
        self.description = info_json['description']
        self.archive = archive

        try:
            self.full_clean()
        except ValidationError as e:
            raise e
        else:
            self.save()

        for db_plugin in plugin_handler.find_fitting_plugins():
            self.requires.add(db_plugin)

        for argument in plugin_handler.get_arguments():
            argument.plugin = self
            try:
                argument.full_clean()
            except ValidationError as e:
                raise e
            else:
                argument.save()

    def validate_required_plugins(self, plugin):
        plugin_handler = PluginInformationHandler(self.get_full_path_to_archive())
        info_file = plugin_handler.get_info()
        available_plugins = []

        for in_info_file_specified in info_file['requires']:
            if in_info_file_specified['name'] == plugin.name:
                available_plugins = plugin_handler.find_required_plugins(in_info_file_specified)

        if plugin not in available_plugins:
            raise ValidationError('Plugin %s can not be used as substitution!' % str(plugin))


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

    plugin = models.ForeignKey(Plugin)
    project = models.ForeignKey(Project)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def has_unfinished_jobs(self):
        for job in self.job_set.all():
            if job.status not in ['DONE', 'EXIT']:
                return True

        return False


class Job(models.Model):
    STATUS_CHOICES = (
        ('PEND', 'Pending'),
        ('PROV', 'Dispatched to power-save host'),
        ('PSUSP', 'Suspended (pending)'),
        ('RUN', 'Running'),
        ('USUSP', 'Suspended (running)'),
        ('SSUSP', 'Suspended (other)'),
        ('DONE', 'Done'),
        ('EXIT', 'Exit'),
        ('UNKWN', 'Unknown'),
        ('WAIT', 'Waiting'),
        ('ZOMBI', 'Zombie!!'),
    )
    job_id = models.IntegerField()
    plugin_execution = models.ForeignKey(PluginExecution)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES)
    output_log = models.CharField(max_length=200)
    error_log = models.CharField(max_length=200)
    revision_path = models.CharField(max_length=100, blank=True)
    submission_string = models.CharField(max_length=2000)
    revision_hash = models.CharField(max_length=100, blank=True)




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
                try:
                    password = entry[0].f_locals['request'].POST.get('password1')
                except:
                    password = None
                break
        handler.update_user(username=user.username, password=password, roles=[])


