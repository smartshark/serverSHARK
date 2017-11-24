"""
WIP

Allow the visualshark to start / restart jobs remotely.
"""

import threading
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse

from smartshark.common import order_plugins
from smartshark.datacollection.executionutils import create_jobs_for_execution
from smartshark.forms import get_form, set_argument_execution_values
from smartshark.models import Plugin, Project, PluginExecution, Job, Argument

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface

logger = logging.getLogger('django')


class JobSubmissionThread(threading.Thread):
    def __init__(self, project, plugin_executions):
        threading.Thread.__init__(self)
        self.project = project
        self.plugin_executions = plugin_executions

    def run(self):
        interface = PluginManagementInterface.find_correct_plugin_manager()
        jobs = create_jobs_for_execution(self.project, self.plugin_executions)
        interface.execute_plugins(self.project, jobs, self.plugin_executions)


def list_arguments(request):
    ak = request.GET.get('ak', None)
    plugin_ids = request.GET.get('plugin_ids', None)

    if not ak:
        return HttpResponse('Unauthorized', status=401)
    if ak != settings.API_KEY:
        return HttpResponse('Unauthorized', status=401)

    if not plugin_ids:
        return HttpResponse('Missing plugin id', status=400)

    dat = {}
    for plugin_id in plugin_ids.split(','):
        dat[plugin_id] = []
        for arg in Argument.objects.filter(plugin=Plugin.objects.get(id=plugin_id)):
            dat[plugin_id].append({'id': arg.id, 'name': arg.name, 'description': arg.description, 'position': arg.position, 'required': arg.required})

    return JsonResponse(dat)


def list_plugins(request):
    ak = request.GET.get('ak', None)
    if not ak:
        return HttpResponse('Unauthorized', status=401)
    if ak != settings.API_KEY:
        return HttpResponse('Unauthorized', status=401)

    dat = {'plugins': []}
    for plugin in Plugin.objects.filter(active=True, installed=True):
        dat['plugins'].append({'name': plugin.name, 'id': plugin.id})

    return JsonResponse(dat)


def start_collection(request):
    ak = request.POST.get('ak', None)
    if not ak:
        return HttpResponse('Unauthorized', status=401)
    if ak != settings.API_KEY:
        return HttpResponse('Unauthorized', status=401)

    project_mongo_ids = request.POST.get('project_mongo_ids', None)
    plugin_ids = request.POST.get('plugin_ids', None)

    if not project_mongo_ids:
        return HttpResponse('project mongo ids required', status=400)

    if not plugin_ids:
        return HttpResponse('no plugins selected', status=400)

    interface = PluginManagementInterface.find_correct_plugin_manager()

    plugins = []
    projects = []

    for plugin_id in plugin_ids.split(','):
        plugin = Plugin.objects.get(pk=plugin_id, active=True, installed=True)
        plugins.append(plugin)

        for mongo_id in project_mongo_ids.split(','):
            project = Project.objects.get(mongo_id=mongo_id)
            projects.append(project)

            # check plugin requirements
            for req_plugin in plugin.requires.all():
                if not _check_if_at_least_one_execution_was_successful(req_plugin, project):
                    return HttpResponse('not all requirements for plugin {} are met. Plugin {} was not executed successfully for project {} before'.format(plugin, req_plugin, project), status=400)

            # check if plugin alredy runs
            plugin_executions = PluginExecution.objects.all().filter(plugin=plugin, project=project)

            # Get all jobs from all plugin_executions which did not terminate yet
            jobs = []
            for plugin_execution in plugin_executions:
                jobs.extend(Job.objects.filter(plugin_execution=plugin_execution, status='WAIT').all())

            # Update the job stati for these jobs
            job_stati = interface.get_job_stati(jobs)
            i = 0
            for job in jobs:
                job.status = job_stati[i]
                job.save()

            # check if some plugin has unfinished jobs
            has_unfinished_jobs = False
            for plugin_execution in plugin_executions:
                if plugin_execution.has_unfinished_jobs():
                    has_unfinished_jobs = True

            if has_unfinished_jobs:
                return HttpResponse('Plugin {} has unfinished jobs in project {}'.format(plugin, project))

    form = get_form(plugins, request.POST, 'execute')

    if form.is_valid():
        execution_type = form.cleaned_data.get('execution', None)
        revisions = form.cleaned_data.get('revisions', None)
        repository_url = form.cleaned_data.get('repository_url', None)

        sorted_plugins = order_plugins(plugins)

        for project in projects:

            plugin_executions = []
            for plugin in sorted_plugins:
                # Create Plugin Execution Objects
                plugin_execution = PluginExecution(project=project, plugin=plugin)

                if plugin.plugin_type == 'repo' or plugin.plugin_type == 'rev':
                    plugin_execution.repository_url = repository_url

                if plugin.plugin_type == 'rev':
                    plugin_execution.execution_type = execution_type
                    plugin_execution.revisions = revisions

                plugin_execution.save()
                plugin_executions.append(plugin_execution)

            # Set execution history with execution values for the plugin execution
            set_argument_execution_values(form.cleaned_data, plugin_executions)

            # Create jobs and execute them in a separate thread
            thread = JobSubmissionThread(project, plugin_executions)
            thread.start()
        return HttpResponse(status=202)


def _check_if_at_least_one_execution_was_successful(req_plugin, project):
    # Go through all plugin executions
    for plugin_execution in PluginExecution.objects.filter(plugin=req_plugin, project=project).all():
        if plugin_execution.was_successful():
            return True

    return False
