import copy

import itertools
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

# Create your views here.
from form_utils.forms import BetterForm

from smartshark.forms import ProjectForm
from smartshark.hpchandler import HPCHandler
from smartshark.models import Project, Plugin, Argument, PluginExecution, Job
from django import forms
from difflib import SequenceMatcher
from server.settings import SUBSTITUTIONS


def parse_argument_values(form_data, parameters):
    for id_string, value in form_data.items():
        if "argument" in id_string:
            parts = id_string.split("_")
            plugin_id = parts[0]
            argument_id = parts[2]
            parameter = {'argument': get_object_or_404(Argument, pk=argument_id), 'value': value}
            parameters[plugin_id]['parameters'].append(parameter)


def get_form(plugins, post, type):
        created_fieldsets = []
        plugin_fields = {}

        if type == 'execute':
            plugin_fields['force_renew'] = forms.BooleanField(label="Force renew of all revisions?", required=False)
            created_fieldsets.append(['Basis Configuration', {'fields': ['force_renew']}])

        print(plugin_fields)

        # Create lists for the fieldsets and a list for the fields of the form
        for plugin in plugins:
            arguments=[]
            for argument in plugin.argument_set.all().filter(type=type):
                identifier = '%s_argument_%s' % (plugin.id, argument.id)
                arguments.append(identifier)
                initial = None
                for name, value in SUBSTITUTIONS.items():
                    if SequenceMatcher(None, argument.name, name).ratio() > 0.8:
                        initial = value['name']
                plugin_fields[identifier] = forms.CharField(label=argument.name,
                                                            required=argument.required,
                                                            initial=initial)

            created_fieldsets.append([str(plugin), {'fields': arguments}])


        # Dynamically creted pluginform
        class PluginForm(BetterForm):

            class Meta:
                fieldsets = created_fieldsets

            def __init__(self, *args, **kwargs):
                super(PluginForm, self).__init__(*args, **kwargs)
                self.fields = plugin_fields

        return PluginForm(post)


def create_substitutions_for_display():
    display_dict = {}
    for substitution, value in SUBSTITUTIONS.items():
        display_dict[value['name']] = value['description']

    return display_dict


def install(request):
    plugins = []
    parameters = {}

    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.install_plugin'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/plugin')

    if not request.GET.get('ids'):
        messages.error(request, 'No plugin ids were given to install.')
        return HttpResponseRedirect('/admin/smartshark/plugin')

    for plugin_id in request.GET.get('ids', '').split(','):
        plugin = get_object_or_404(Plugin, pk=plugin_id)
        parameters[plugin_id] = {'plugin': plugin, 'parameters': []}
        plugins.append(plugin)

    if request.method == 'POST':
        if 'cancel' in request.POST:
            return HttpResponseRedirect('/admin/smartshark/plugin')

        # create a form instance and populate it with data from the request:
        form = get_form(plugins, request.POST, 'install')
        # check whether it's valid:
        if form.is_valid():
            parse_argument_values(form.cleaned_data, parameters)
            hpc_handler = HPCHandler()
            try:
                # Sorting arguments according to position attribute and install
                for plugin_id, value in parameters.items():
                    sorted_parameter = sorted(value['parameters'], key=lambda k: k['argument'].position)
                    hpc_handler.install_plugin(value['plugin'], sorted_parameter)

                    # Save the status
                    value['plugin'].installed = True
                    value['plugin'].save()

                    messages.success(request, 'Successfully installed plugin %s in version %.2f' %
                                     (value['plugin'].name, value['plugin'].version))
            except Exception as e:
                messages.error(request, str(e))
                return HttpResponseRedirect('/admin/smartshark/plugin')

            return HttpResponseRedirect('/admin/smartshark/plugin')

    # if a GET (or any other method) we'll create a blank form
    else:
        form = get_form(plugins, request.POST or None, 'install')

    print(create_substitutions_for_display())
    return render(request, 'smartshark/plugin/install.html', {
        'form': form,
        'plugins': plugins,
        'substitutions': create_substitutions_for_display()
    })


def plugin_execution_status(request, id):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_execution_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    plugin_execution = get_object_or_404(PluginExecution, pk=id)

    jobs = Job.objects.all().filter(plugin_execution=plugin_execution).order_by('job_id')
    hpc_handler = HPCHandler()
    hpc_handler.update_job_information(jobs)

    return render(request, 'smartshark/project/plugin_execution_status.html', {
        'plugin_execution': plugin_execution,
        'jobs': jobs,
    })

def plugin_status(request):
    projects = []
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.plugin_status'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    if request.GET.get('ids'):
        for project_id in request.GET.get('ids', '').split(','):
            projects.append(get_object_or_404(Project, pk=project_id))
    else:
        messages.error(request, 'No project ids were given.')
        return HttpResponseRedirect('/admin/smartshark/project')

    executions = {}
    for project in projects:
        executions[project.name] = PluginExecution.objects.all().filter(project=project).order_by('submitted_at')

    return render(request, 'smartshark/project/plugin_status.html', {
        'projects': projects,
        'executions': executions,

    })

def job_output(request, id, type):
    if not request.user.is_authenticated() or not request.user.has_perm('smartshark.job_output'):
        messages.error(request, 'You are not authorized to perform this action.')
        return HttpResponseRedirect('/admin/smartshark/project')

    job = get_object_or_404(Job, pk=id)

    hpc_handler = HPCHandler()
    if type == 'output':
        output = hpc_handler.get_output_log(job)
    elif type == 'error':
        output = hpc_handler.get_error_log(job)
    elif type == 'history':
        output = hpc_handler.get_history(job)

    return render(request, 'smartshark/job/output.html', {
        'output': '\n'.join(output),
        'job': job,
    })


def collection_start(request):
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
            # check requirements
            for plugin in form.cleaned_data['plugins']:
                plugin_ids.append(str(plugin.id))

                # check for each plugin if required plugin is set
                missing_plugins = []
                for req_plugin in plugin.requires.all():
                    if req_plugin not in form.cleaned_data['plugins']:
                        missing_plugins.append(str(req_plugin))

                if missing_plugins:
                    messages.error(request, 'Not all requirements for plugin %s are met. Plugin(s) %s is/are required!'
                                   % (str(plugin), ', '.join(missing_plugins)))
                    return HttpResponseRedirect(request.get_full_path())

                # check if schema problems exist between plugins
                # TODO

                # if plugin with this project is in plugin execution and has status != finished | error -> problem
                for project in projects:
                    plugin_executions = PluginExecution.objects.all().filter(plugin=plugin, project=project)
                    unfinished_jobs = [plugin_execution.get_unfinished_jobs() for plugin_execution in plugin_executions]
                    unfinished_jobs = list(itertools.chain.from_iterable(unfinished_jobs))
                    if unfinished_jobs:
                        messages.error(request, 'Plugin %s is already scheduled for project %s.' % (str(plugin),
                                                                                                    project))
                        return HttpResponseRedirect(request.get_full_path())

            return HttpResponseRedirect('/smartshark/project/collection/arguments?plugins=%s&projects=%s' %
                                        (','.join(plugin_ids), request.GET.get('ids')))

    # if a GET (or any other method) we'll create a blank form
    else:
        form = ProjectForm()

    return render(request, 'smartshark/project/action_collection.html', {
        'form': form,
        'projects': projects,

    })


def order_plugins(plugins):
    new_list = []
    while len(new_list) != len(plugins):
        for plugin in plugins:
            if plugin in new_list:
                continue

            # If a plugin do not have any required plugins: add it
            if not plugin.requires.all():
                new_list.append(plugin)
            else:
                # Check if all requirements are met for the plugin. If yes: add it
                all_requirements_met = True
                for req_plugin in plugin.requires.all():
                    if req_plugin not in new_list:
                        all_requirements_met = False

                if all_requirements_met:
                    new_list.append(plugin)
    return new_list


def collection_arguments(request):
    projects = []
    plugins = []
    plugin_types = set()
    parameters = {}

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
            parameters[plugin_id] = {'plugin': plugin, 'parameters': []}
            plugins.append(plugin)
            plugin_types.add(plugin.abstraction_level)
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
            parse_argument_values(form.cleaned_data, parameters)
            hpc_handler = HPCHandler()

            try:
                # 3. order: first plugins without requirements (can directly be sent) and then
                #ordered_plugins = order_plugins(plugins)
                #print(ordered_plugins)

                for project in projects:
                    # Sorting arguments according to position attribute and execute for each chosen project
                    #hpc_handler.prepare_project(project, plugin_types, form.cleaned_data['force_renew'])

                    for plugin_id, value in parameters.items():
                        sorted_parameter = sorted(value['parameters'], key=lambda k: k['argument'].position)
                        hpc_handler.execute_plugin(value['plugin'], project, sorted_parameter)

                messages.success(request, 'Started the data collection of plugins %s for projects %s' %
                                (plugins, projects))
            except Exception as e:
                messages.error(request, str(e))
                return HttpResponseRedirect('/admin/smartshark/project')

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






