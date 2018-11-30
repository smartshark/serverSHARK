from difflib import SequenceMatcher

from django import forms
from django.forms import HiddenInput
from django.shortcuts import get_object_or_404
from form_utils.forms import BetterForm

from server.base import SUBSTITUTIONS
from server.settings import DATABASES

from .models import Plugin, Argument, ExecutionHistory, PluginExecution
from .datacollection.pluginmanagementinterface import PluginManagementInterface
from .mongohandler import handler


class ProjectForm(forms.Form):
    plugins = forms.ModelMultipleChoiceField(queryset=Plugin.objects.all().filter(active=True, installed=True))


class SparkSubmitForm(forms.Form):
    change_form_template = 'progressbarupload/change_form.html'
    add_form_template = 'progressbarupload/change_form.html'

    file = forms.FileField(label='Jar / Python File')
    class_name = forms.CharField(label='Fully Qualified Class Name', max_length=300, required=False)
    arguments = forms.CharField(label='Arguments', max_length=1000, required=False)


def set_argument_values(form_data):
    for id_string, value in form_data.items():
        if "argument" in id_string:
            parts = id_string.split("_")
            argument_id = parts[2]
            argument = get_object_or_404(Argument, pk=argument_id)
            argument.install_value = value
            argument.save()


def set_argument_execution_values(form_data, plugin_executions):
    for id_string, value in form_data.items():
        if "argument" in id_string:
            parts = id_string.split("_")
            plugin_id = parts[0]
            argument_id = parts[2]

            for plugin_execution in plugin_executions:
                if plugin_execution.plugin.id == int(plugin_id):
                    found_plugin_execution = plugin_execution

            exe = ExecutionHistory(execution_argument=get_object_or_404(Argument, pk=argument_id),
                                   plugin_execution=found_plugin_execution,
                                   execution_value=value)
            exe.save()


def get_form(plugins, post, type, project):
        created_fieldsets = []
        plugin_fields = {}
        EXEC_OPTIONS = (('all', 'Execute on all revisions'), ('error', 'Execute on all revisions with errors'),
                        ('new', 'Execute on new revisions'), ('rev', 'Execute on following revisions:'))

        # we need to get the correct pluginmanager for this information because that depends on selected queue
        interface = PluginManagementInterface.find_correct_plugin_manager()
        cores_per_job = interface.default_cores_per_job()
        queue = interface.default_queue()

        added_fields = []
        if type == 'execute':
            vcs_url = handler.get_vcs_url_for_project_id(project.mongo_id)

            # Add fields if there are plugins that work on revision level
            rev_plugins = [plugin for plugin in plugins if plugin.plugin_type == 'rev']
            if len(rev_plugins) > 0:
                plugin_fields['execution'] = forms.ChoiceField(widget=forms.RadioSelect, choices=EXEC_OPTIONS)
                plugin_fields['revisions'] = forms.CharField(label='Revisions (comma-separated)', required=False)
                added_fields.append('execution')
                added_fields.append('revisions')

            repo_plugins = [plugin for plugin in plugins if plugin.plugin_type == 'repo']
            # If we have revision or repository plugins, we need to ask for the repository to use
            if len(rev_plugins) > 0 or len(repo_plugins) > 0:
                plugin_fields['repository_url'] = forms.CharField(label='Repository URL', required=True)
                added_fields.append('repository_url')

            plugin_fields['queue'] = forms.CharField(label='Default job queue', required=False, initial=queue)
            added_fields.append('queue')

            plugin_fields['cores_per_job'] = forms.CharField(label='Cores per job (HPC only)', required=False, initial=cores_per_job)
            added_fields.append('cores_per_job')

        created_fieldsets.append(['Basis Configuration', {'fields': added_fields}])
        # Create lists for the fieldsets and a list for the fields of the form
        for plugin in plugins:
            arguments = []
            for argument in plugin.argument_set.all().filter(type=type):
                identifier = '%s_argument_%s' % (plugin.id, argument.id)
                arguments.append(identifier)
                initial = None
                for name, value in SUBSTITUTIONS.items():
                    if SequenceMatcher(None, argument.name, name).ratio() > 0.8:
                        initial = value['name']

                plugin_fields[identifier] = forms.CharField(label=argument.name, required=argument.required,
                                                            initial=initial, help_text=argument.description)

            created_fieldsets.append([str(plugin), {'fields': arguments}])

        # Dynamically created pluginform
        class PluginForm(BetterForm):

            class Meta:
                fieldsets = created_fieldsets

            def __init__(self, *args, **kwargs):
                super(PluginForm, self).__init__(*args, **kwargs)
                self.fields = plugin_fields

        return PluginForm(post)
