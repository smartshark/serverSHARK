from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404

# Create your views here.
from form_utils.forms import BetterForm

from smartshark.forms import ProjectForm
from smartshark.hpchandler import HPCHandler
from smartshark.models import Project, Plugin, Argument
from django import forms

def parse_argument_values(form_data, parameters):
    for id_string, value in form_data.items():
        parts = id_string.split("_")
        plugin_id = parts[0]
        argument_id = parts[2]
        parameter = {'argument': get_object_or_404(Argument, pk=argument_id), 'value': value}
        parameters[plugin_id]['parameters'].append(parameter)

def get_form(plugins, post, type):
        created_fieldsets = []
        plugin_fields = {}

        # Create lists for the fieldsets and a list for the fields of the form
        for plugin in plugins:
            arguments=[]
            for argument in plugin.argument_set.all().filter(type=type):
                identifier = '%s_argument_%s' % (plugin.id, argument.id)
                arguments.append(identifier)
                plugin_fields[identifier] = forms.CharField(label=argument.name, required=argument.required)
            created_fieldsets.append([str(plugin), {'fields': arguments}])


        # Dynamically creted pluginform
        class PluginForm(BetterForm):

            class Meta:
                fieldsets = created_fieldsets

            def __init__(self, *args, **kwargs):
                super(PluginForm, self).__init__(*args, **kwargs)
                self.fields = plugin_fields

        return PluginForm(post)


def install(request):
    plugins = []
    parameters = {}

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

    })


def collection_start(request):
    projects = []

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
                plugin_ids.append(plugin.id)

                # check for each plugin if it is active and installed
                if not plugin.active or not plugin.installed:
                    messages.error(request, 'Plugin %s is not active or installed.' % str(plugin))


            # 1. check for each plugin if required plugin is set
            # 2. if plugin with this name and project is in pluginexec and hast status != finished | error -> problem


            # add plugin execreturn HttpResponseRedirect("/smartshark/install/?ids=%s" % (",".join(selected)))
            return HttpResponseRedirect('/smartshark/collection/arguments?plugins=%s&projects=%s' %
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
            try:
                # 3. order: first plugins without requirements (can directly be sent)
                # TODO

                # 4. rest is put into a queue (signal: projectname/plugin/?status=success

                for project in projects:
                    # Sorting arguments according to position attribute and execute for each choosen project
                    for plugin_id, value in parameters.items():
                        sorted_parameter = sorted(value['parameters'], key=lambda k: k['argument'].position)
                        hpc_handler.execute_plugin(value['plugin'], project, sorted_parameter)

                messages.success(request, 'Started the data collection of plugins %s for projects %s' %
                                (plugins, projects))
            except Exception as e:
                messages.error(request, str(e))
                return HttpResponseRedirect('/admin/smartshark/plugin')

            return HttpResponseRedirect('/admin/smartshark/plugin')


    # if a GET (or any other method) we'll create a blank form
    else:
        form = get_form(plugins, request.POST or None, 'execute')

    return render(request, 'smartshark/project/execution.html', {
        'form': form,
        'plugins': plugins,
        'projects': projects,

    })






