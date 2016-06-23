from difflib import SequenceMatcher

from django.shortcuts import get_object_or_404
from form_utils.forms import BetterForm

from server.base import SUBSTITUTIONS
from .models import Plugin, Argument
from django import forms


class ProjectForm(forms.Form):
    plugins = forms.ModelMultipleChoiceField(queryset=Plugin.objects.all().filter(active=True, installed=True))

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
        EXEC_OPTIONS = (('all', 'Execute on all revisions'), ('error', 'Execute on all revisions with errors'),
                        ('new', 'Execute on new revisions'), ('rev', 'Execute on following revisions:'))

        if type == 'execute':
            rev_plugins = [plugin for plugin in plugins if plugin.abstraction_level == 'rev']
            if len(rev_plugins) > 0:
                plugin_fields['execution'] = forms.ChoiceField(widget=forms.RadioSelect, choices=EXEC_OPTIONS)
                plugin_fields['revisions'] = forms.CharField(label='Revisions (comma-separated)', required=False)
                created_fieldsets.append(['Basis Configuration', {'fields': ['execution', 'revisions']}])

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

