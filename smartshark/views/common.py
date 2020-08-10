import json
from collections import defaultdict
from queue import Queue

from django.contrib import messages
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface
from smartshark.filters import JobExecutionFilter
from smartshark.models import PluginExecution, Job, Project, Plugin
from smartshark.mongohandler import handler


def index(request):
    return render(request, 'smartshark/frontend/index.html')


def is_first_higher(semver1, semver2):
    """Check if first semVer is higher than the second."""
    sv1 = semver1.split('.')
    sv2 = semver2.split('.')

    if int(sv1[0]) > int(sv2[0]):
        return True

    if int(sv1[1]) > int(sv2[1]):
        return True

    if len(sv1) > 2 and len(sv2) > 2:
        if int(sv1[2]) > int(sv2[2]):
            return True
    return False


class Item(object):
    def __init__(self, id, name, desc=None, sub_fields=None, parent='#', logical_types=None, reference_to=None):
        self.id = id
        self.name = name
        self.reference_to = reference_to

        if desc is None:
            self.desc = []
        else:
            self.desc = [desc]

        if sub_fields is None:
            self.sub_fields = []

        if logical_types is None:
            self.logical_types = []
        else:
            self.logical_types = logical_types

        self.parent = parent

    def add_field(self, field):
        self.sub_fields.append(field)

    def get_max_description(self):
        max_version = {}
        for d in self.desc:
            name, version = d['plugin'].split(' ')
            desc = d['desc']

            if name not in max_version.keys():
                max_version[name] = {'desc': desc, 'plugin': d['plugin'], 'version': version}
            else:
                if is_first_higher(version, max_version[name]['version']):
                    max_version[name]['version'] = version
                    max_version[name]['desc'] = desc
                    max_version[name]['plugin'] = d['plugin']
        ret = []
        for name, values in max_version.items():
            ret.append({'desc': values['desc'], 'plugin': values['plugin']})
        return ret

    def add_description(self, description):
        found = False
        for d in self.desc:

            # same plugin and version
            if description['plugin'] == d['plugin']:
                found = True
            v1 = description['plugin'].split(' ')[-1]
            v2 = d['plugin'].split(' ')[-1]

            if is_first_higher(v1, v2):  # if current SemVer is not higher we do not add it to the description
                found = False
        if not found:
            self.desc.append(description)


def recursion(item, parent, plugin_name, items):
    if 'fields' not in item:
        return

    for field in item['fields']:
        if isinstance(field['logical_type'], list):
            logical_types = field['logical_type']
        else:
            logical_types = [field['logical_type']]

        reference_to = None
        if 'reference_to' in field:
            reference_to = field['reference_to']

        new_field = Item(
            parent+'_'+field['field_name'], field['field_name'], desc={'desc': field['desc'], 'plugin': ' '.join(plugin_name.split('_'))},
            parent=parent, logical_types=logical_types, reference_to=reference_to)

        if new_field.id in items:
            stored_field = items[new_field.id]
            stored_field.add_description({'desc': field['desc'], 'plugin': ' '.join(plugin_name.split('_'))})
        else:
            items[new_field.id] = new_field

        if 'fields' in field:
            recursion(field, new_field.id, plugin_name, items)


def documentation(request):
    items = {}
    data = []

    for schema in handler.get_plugin_schemas():

        plugin_name = schema['plugin']

        for mongo_collection in schema['collections']:

            desc = ''
            if 'desc' in mongo_collection.keys():
                desc = mongo_collection['desc']

            collection_name = ''
            if 'collection_name' in mongo_collection.keys():
                collection_name = mongo_collection['collection_name']

            collection = Item(collection_name, collection_name, desc={'desc': desc, 'plugin': ' '.join(plugin_name.split('_'))})
            if collection.id in items:
                stored_collection = items[collection.id]
                stored_collection.add_description({'desc': desc, 'plugin': ' '.join(plugin_name.split('_'))})
            else:
                items[collection.id] = collection

            recursion(mongo_collection, collection_name, plugin_name, items)

    for item_id, item_data in items.items():
        json_collection = {
            'id': item_id,
            'parent': item_data.parent,
            'text': item_data.name,
            'data': {
                'desc': item_data.get_max_description(),
                'logical_types': item_data.logical_types,
                'reference_to': item_data.reference_to
            }
        }
        data.append(json_collection)

    return render(request, 'smartshark/frontend/documentation.html', {
        'data': json.dumps(data),
        'plugins': Plugin.objects.all().filter(active=True).order_by('name'),
    })


def plugin_execution_status(request, id):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_execution_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    interface = PluginManagementInterface.find_correct_plugin_manager()
    plugin_execution = get_object_or_404(PluginExecution, pk=id)

    # Get all jobs from all plugin_executions which did not terminate yet
    # Update the job stati for these jobs
    jobs = Job.objects.filter(plugin_execution=plugin_execution, status='WAIT').all()
    job_stati = interface.get_job_stati(jobs)
    i = 0
    for job in jobs:
        job.status = job_stati[i]
        job.save()
        i += 1

    job_filter = JobExecutionFilter(request.GET, queryset=Job.objects.all().filter(plugin_execution=plugin_execution))

    rev = [exitjob.revision_hash if exitjob.revision_hash else '' for exitjob in job_filter.qs.filter(status='EXIT')]
    exit_job_revisions = ''
    if rev:
        exit_job_revisions = ','.join(rev)

    # Set up pagination
    paginator = Paginator(job_filter.qs, 10)
    page = request.GET.get('page')
    try:
        jobs = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        jobs = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        jobs = paginator.page(paginator.num_pages)

    return render(request, 'smartshark/project/plugin_execution_status.html', {
        'plugin_execution': plugin_execution,
        'filter': job_filter,
        'jobs': jobs,
        'overall': len(job_filter.qs),
        'queried_status': job_filter.data.get('status', None),
        'done_jobs': len(job_filter.qs.filter(status='DONE')),
        'exit_jobs': len(rev),
        'waiting_jobs': len(job_filter.qs.filter(status='WAIT')),
        'exit_job_revisions': exit_job_revisions
    })


def plugin_status(request, id):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    project = get_object_or_404(Project, pk=id)
    execution_list = PluginExecution.objects.all().filter(project=project).order_by('-submitted_at')

    paginator = Paginator(execution_list, 10)
    page = request.GET.get('page')
    try:
        executions = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        executions = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        executions = paginator.page(paginator.num_pages)

    return render(request, 'smartshark/project/plugin_status.html', {
        'executions': executions,
        'project': project
    })


def job_output(request, id, type):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.job_output'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    job = get_object_or_404(Job, pk=id)
    interface = PluginManagementInterface.find_correct_plugin_manager()

    if type == 'output':
        output = interface.get_output_log(job)
    elif type == 'error':
        output = interface.get_error_log(job)
    elif type == 'arguments':
        return render(request, 'smartshark/job/execution_arguments.html', {
            'exe_arguments': job.plugin_execution.executionhistory_set.all().order_by('execution_argument__position'),
            'cmd': interface.get_sent_bash_command(job),
        })

    return render(request, 'smartshark/job/output.html', {
        'output': '\n'.join(output),
        'job': job,
    })
