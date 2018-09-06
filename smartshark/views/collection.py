import threading
import logging

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.conf import settings
from bson.objectid import ObjectId

from smartshark.common import create_substitutions_for_display, order_plugins, append_success_messages_to_req
from smartshark.datacollection.executionutils import create_jobs_for_execution
from smartshark.forms import ProjectForm, get_form, set_argument_values, set_argument_execution_values
from smartshark.models import Plugin, Project, PluginExecution, Job

from smartshark.mongohandler import handler
from smartshark.datacollection.pluginmanagementinterface import PluginManagementInterface

logger = logging.getLogger('django')


class JobSubmissionThread(threading.Thread):
    def __init__(self, project, plugin_executions, create_jobs=True):
        threading.Thread.__init__(self)
        self.project = project
        self.plugin_executions = plugin_executions
        self.create_jobs = create_jobs

    def run(self):
        interface = PluginManagementInterface.find_correct_plugin_manager()
        jobs = []
        if self.create_jobs:
            jobs = create_jobs_for_execution(self.project, self.plugin_executions)
        interface.execute_plugins(self.project, jobs, self.plugin_executions)


def install(request):
    plugins = []

    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.install_plugin'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/plugin')

    if not request.GET.get('ids'):
        messages.error(request, 'No plugin ids were given to install.')
        return HttpResponseRedirect('/admin/smartshark/plugin')

    for plugin_id in request.GET.get('ids', '').split(','):
        plugin = get_object_or_404(Plugin, pk=plugin_id)
        plugins.append(plugin)

    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/plugin')

        # create a form instance and populate it with data from the request:
        form = get_form(plugins, request.POST, 'install')
        # check whether it's valid:
        if form.is_valid():
            # Parse the fields and set the corresponding values of the install arguments in the database
            set_argument_values(form.cleaned_data)

            # Install plugins
            installations = PluginManagementInterface.find_correct_plugin_manager().install_plugins(plugins)

            # Check if plugins successfully installed
            append_success_messages_to_req(installations, plugins, request)

            return HttpResponseRedirect('/admin/smartshark/plugin')

    # if a GET (or any other method) we'll create a blank form
    else:
        form = get_form(plugins, request.POST or None, 'install')

    return render(request, 'smartshark/plugin/install.html', {
        'form': form,
        'plugins': plugins,
        'substitutions': create_substitutions_for_display()
    })


def _check_if_at_least_one_execution_was_successful(req_plugin, project):
    # Go through all plugin executions

    tmp = req_plugin.split('_')  # one version of a plugin is enough for now
    # todo: check if version of plugin is higher than our required
    for plugin_execution in PluginExecution.objects.filter(plugin__startswith=tmp[0], project=project).all():
        if plugin_execution.was_successful():
            return True

    return False


def choose_plugins(request):
    projects = []

    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.start_collection'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if request.GET.get('ids'):
        for project_id in request.GET.get('ids', '').split(','):
            projects.append(get_object_or_404(Project, pk=project_id))
    else:
        messages.error(request, 'No project ids were given.')
        return HttpResponseRedirect('/admin/smartshark/project')

    # if this is a POST request we need to process the form data
    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/project')

        # create a form instance and populate it with data from the request:
        form = ProjectForm(request.POST)
        # check whether it's valid:
        if form.is_valid():
            plugin_ids = []
            interface = PluginManagementInterface.find_correct_plugin_manager()

            # check requirements
            for plugin in form.cleaned_data['plugins']:
                plugin_ids.append(str(plugin.id))

                # check for each plugin if required plugin is set
                '''
                missing_plugins = []
                for req_plugin in plugin.requires.all():
                    if req_plugin not in form.cleaned_data['plugins']:
                        missing_plugins.append(str(req_plugin))

                if missing_plugins:
                    messages.error(request, 'Not all requirements for plugin %s are met. Plugin(s) %s is/are required!'
                                   % (str(plugin), ', '.join(missing_plugins)))
                    return HttpResponseRedirect(request.get_full_path())
                '''
                # check if schema problems exist between plugins
                # TODO

                # if plugin with this project is in plugin execution and has status != finished | error -> problem
                for project in projects:
                    for req_plugin in plugin.requires.all():
                        logger.debug("Looking at required plugin %s" % str(req_plugin))

                        # todo: implement check for plugins taking into account the plugin version e.g., if vcsshark-0.10 is required
                        # also allow vcsshark-0.11 or newer (if info.json allows that (>=))
                        #if not _check_if_at_least_one_execution_was_successful(req_plugin, project):
                        #    messages.error(request,
                        #                   'Not all requirements for plugin %s are met. Plugin %s was not executed '
                        #                   'successfully for project %s before!'
                        #                   % (str(plugin), str(req_plugin), str(project)))
                        #    return HttpResponseRedirect(request.get_full_path())

                        logger.debug("At least one plugin execution for plugin %s was successful." % str(req_plugin))

                    # Update job information
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
                        messages.error(request, 'Plugin %s is already scheduled for project %s.' % (str(plugin),
                                                                                                    project))
                        return HttpResponseRedirect(request.get_full_path())

            return HttpResponseRedirect('/smartshark/project/collection/start?plugins=%s&projects=%s' %
                                        (','.join(plugin_ids), request.GET.get('ids')))

    # if a GET (or any other method) we'll create a blank form
    else:
        form = ProjectForm()

    return render(request, 'smartshark/project/action_collection.html', {
        'form': form,
        'projects': projects,

    })


def start_collection(request):
    projects = []
    plugins = []

    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.start_collection'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if request.GET.get('projects'):
        for project_id in request.GET.get('projects', '').split(','):
            projects.append(get_object_or_404(Project, pk=project_id))
    else:
        messages.error(request, 'No project ids were given.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if request.GET.get('plugins'):
        for plugin_id in request.GET.get('plugins', '').split(','):
            plugin = get_object_or_404(Plugin, pk=plugin_id)
            plugins.append(plugin)
    else:
        messages.error(request, 'No plugin ids were given.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/project')

        # create a form instance and populate it with data from the request:
        form = get_form(plugins, request.POST, 'execute')

        # check whether it's valid:
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

                    messages.success(request, 'Started plugin %s on project %s.' %
                             (str(plugin), project.name))

                # Set execution history with execution values for the plugin execution
                set_argument_execution_values(form.cleaned_data, plugin_executions)

                # Create jobs and execute them in a separate thread
                thread = JobSubmissionThread(project, plugin_executions)
                thread.start()

            return HttpResponseRedirect('/admin/smartshark/project')

    # if a GET (or any other method) we'll create a blank form
    else:
        form = get_form(plugins, request.POST or None, 'execute')

    return render(request, 'smartshark/project/execution.html', {
        'form': form,
        'plugins': plugins,
        'projects': projects,
        'substitutions': create_substitutions_for_display()
    })


def delete_project_data(request):
    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/project')

    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_execution_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    projects = []

    if request.GET.get('ids'):
        for project_id in request.GET.get('ids', '').split(','):
            projects.append(get_object_or_404(Project, pk=project_id))
    else:
        messages.error(request, 'No project ids were given.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if(len(projects) != 1):
        messages.error(request, 'Deletion progress is only supported for one project at the same time.')
        return HttpResponseRedirect('/admin/smartshark/project')

    project = projects[0]
    # Start of the deletion process
    plugin_path = settings.LOCALQUEUE['plugin_installation']

    # Collect all schemas
    schemas = getPlugins()

    # Analyze the schema
    deb = []
    x = findDependencyOfSchema('project', schemas.values(),[])
    schemaProject = SchemaReference('project', '_id', x)
    deb.append(schemaProject)

    # Create a preview, count collections the schema
    if request.method == 'POST':
        if 'start' in request.POST:
            deleteOnDependencyTree(schemaProject,ObjectId(project.mongo_id))
            return render(request, 'smartshark/project/action_deletion_finish.html', {
                'project': project
            })
    else:
        countOnDependencyTree(schemaProject,ObjectId(project.mongo_id))

    return render(request, 'smartshark/project/action_deletion.html', {
        'project': project,
        'dependencys': deb

    })

def getPlugins():
    # Load the tables directly from the MongoDB
    schemas = {}
    query = handler.client.get_database(handler.database).get_collection('plugin_schema').find()

    plugins = {}
    for schema in query:
        name, version = schema["plugin"].split('_')
        version = version.split('.')  # Split into tuple
        if name in plugins:
            if version > plugins[name]:
                schemas[name] = schema

        else:
            schemas[name] = schema
            plugins[name] = version

    # Alternativ way to get the schema via the files of the plugin installations
    # for root, dirs, files in os.walk(plugin_path):
    #    for name in files:
    #        if name == 'schema.json':
    #            filepath = os.path.join(root, name)
    #            json1_file = open(filepath).read()
    #            json_data = json.loads(json1_file)
    #            schemas.append(json_data)
    return schemas

def findDependencyOfSchema(name, schemas,ground_dependencys=[]):
    dependencys = []
    for schema in schemas:
        for collection in schema['collections']:
            # For each field in the collection check if the field is a reference
            if(collection['collection_name'] not in ground_dependencys):
                for field in collection['fields']:
                    if('reference_to' in field and field['reference_to'] == name):
                        ground_dependencys.append(collection['collection_name'])
                        dependencys.append(SchemaReference(collection['collection_name'],field['field_name'], findDependencyOfSchema(collection['collection_name'],schemas, ground_dependencys)))

    return dependencys

def countOnDependencyTree(tree, parent_id):
    #print(handler.database)
    query = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id})
    count = query.count()
    # print(tree.collection_name)
    tree.count = tree.count + count
    for object in query:
        #print(object)
        #print(object.get('_id'))
        for deb in tree.dependencys:
            countOnDependencyTree(deb,object.get('_id'))

def deleteOnDependencyTree(tree, parent_id):
    query = handler.client.get_database(handler.database).get_collection(tree.collection_name).find({tree.field: parent_id})
    count = query.count()
    # print(tree.collection_name)
    tree.count = tree.count + count
    for object in query:
        #print(object)
        #print(object.get('_id'))
        for deb in tree.dependencys:
            deleteOnDependencyTree(deb,object.get('_id'))
    # Delete finally
    #if(tree.collection_name != 'project'):
    handler.client.get_database(handler.database).get_collection(tree.collection_name).delete_many({tree.field: parent_id})

class SchemaReference:

    def __init__(self, collection_name, field, deb):
        self.collection_name = collection_name
        self.field = field
        self.dependencys = deb
        self.count = 0

    def __repr__(self):
        return str(self.collection_name) + " --> " + str(self.field) + " Dependencys:" + str(self.dependencys)

    def __str__(self):
        return str(self.collection_name) + " --> " + str(self.field) + " Dependencys:" + str(self.dependencys)
