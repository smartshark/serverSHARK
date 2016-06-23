import copy

import itertools
from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

# Create your views here.
from smartshark.common import create_substitutions_for_display, order_plugins
from smartshark.forms import ProjectForm, get_form, parse_argument_values
from smartshark.hpchandler import HPCHandler
from smartshark.models import Project, Plugin, Argument, PluginExecution, Job


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
            hpc_handler = HPCHandler()
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
                    # Update job information
                    plugin_executions = PluginExecution.objects.all().filter(plugin=plugin, project=project)
                    jobs = [plugin_execution.job_set.all() for plugin_execution in plugin_executions]
                    jobs = list(itertools.chain.from_iterable(jobs))
                    hpc_handler.update_job_information(jobs)

                    # check if some plugin has unfinished jobs
                    has_unfinished_jobs = False
                    for plugin_execution in plugin_executions:
                        if plugin_execution.has_unfinished_jobs():
                            has_unfinished_jobs = True

                    if has_unfinished_jobs:
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


def collection_arguments(request):
    projects = []
    plugins = []
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
            execution = None
            revisions = None
            if 'execution' in form.cleaned_data:
                execution = form.cleaned_data['execution']

            if 'revisions' in form.cleaned_data:
                revisions = form.cleaned_data['revisions']

            try:
                for project in projects:
                    # First prepare project (clone repo, set up revisions, etc.)
                    hpc_handler.prepare_project(project, plugins, execution, revisions)

                    # Sort plugins (first the one without requirements, than the one that requires the first, etc.)
                    sorted_plugins = order_plugins(parameters)

                    # For each plugin: execute it with the choosen project
                    for value in sorted_plugins:
                        sorted_parameter = sorted(value['parameters'], key=lambda k: k['argument'].position)
                        hpc_handler.execute_plugin(value['plugin'], project, sorted_parameter, execution, revisions)

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






