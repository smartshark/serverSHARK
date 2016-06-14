from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
import tarfile
import json

from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django import forms
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from form_utils.forms import BetterForm

from smartshark.hpchandler import HPCHandler
from smartshark.pluginhandler import PluginInformationHandler
from .models import MongoRole, SmartsharkUser, Plugin, Argument, Project
# Register your models here.

admin.site.unregister(User)


class MyUserAdmin(UserAdmin):
    def get_readonly_fields(self, request, obj=None):
        """
        Do not allow changing of account once created
        """
        if obj:
            return self.readonly_fields + ('username',)
        return self.readonly_fields


class MongoModelAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


class SmartsharkUserAdmin(admin.ModelAdmin):
    readonly_fields = ('user', )
    fields = ('user', 'roles')


class ArgumentAdmin(admin.ModelAdmin):
    def get_model_perms(self, request):
        return {}


class PluginAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'abstraction_level', 'active', 'installed')
    actions = ('delete_model', 'install_plugin' )

    # A little hack to remove the plugin deleted successfully message
    def changelist_view(self, request, extra_context=None):

        storage = get_messages(request)
        all_messages = list(get_messages(request))

        for i in range(0, len(all_messages)):
            if storage._loaded_messages[i].message.startswith('The plugin "'):
                del storage._loaded_messages[i]

        return super(PluginAdmin, self).changelist_view(request, extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if request.method == 'POST':
            changed_plugin = get_object_or_404(Plugin, pk=object_id)
            required_plugins = request.POST.getlist('requires')

            if len(required_plugins) != len(changed_plugin.get_required_plugins()):
                messages.error(request, 'Number of required plugins are not matching!')
                return redirect(request.get_full_path())

            for req_plugin_id in required_plugins:
                req_plugin = get_object_or_404(Plugin, pk=req_plugin_id)

                try:
                    changed_plugin.validate_required_plugins(req_plugin)
                except ValidationError as e:
                    messages.error(request, str(e))
                    return redirect(request.get_full_path())

        return super(PluginAdmin, self).change_view(request, object_id, form_url, extra_context)

    def get_fields(self, request, obj=None):
        if not obj:
            return 'archive',
        else:
            return 'name', 'author', 'version', 'abstraction_level', 'archive', 'requires', 'active', 'installed'

    def get_readonly_fields(self, request, obj=None):
        if not obj:
            return 'name', 'author', 'version', 'abstraction_level', 'installed'
        else:
            return 'name', 'author', 'version', 'abstraction_level', 'archive', 'installed'

    def get_actions(self, request):
        actions = super(PluginAdmin, self).get_actions(request)
        del actions['delete_selected']
        return actions

    def save_model(self, request, obj, form, change):
        #file = tarfile.open(fileobj=request.FILES['archive'])
        #plugin_description = json.loads(file.extractfile('info.json').read().decode('utf-8'))
        #plugin_schema = json.loads(file.extractfile('schema.json').read().decode('utf-8'))

        if change:
            obj.save()
        else:
            plugin = Plugin()
            plugin.load_from_json(request.FILES['archive'])

    def install_plugin(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect("/smartshark/install/?ids=%s" % (",".join(selected)))

    def delete_model(self, request, obj):

        if isinstance(obj, Plugin):
            obj = [obj]

        # For all plugins that are marked to delete
        for plugin in obj:
            plugins = Plugin.objects.all().filter(requires=plugin)
            successful = True

            # Go through all plugins that require the plugin that is marked for deletion
            for requires_this_plugin in plugins:
                # If there are no problems with substitutions, go on, otherwise set successful to False
                if requires_this_plugin.get_substitution_plugin_for(plugin) is None:
                    successful = False

            # If we are not successful, we can not delete this plugin, because the requirements can not be met
            if not successful:
                messages.error(request, 'Could not delete plugin, because it is required by other plugins '
                                        'and requirements can not be matched otherwise!')

            # Otherwise, we need to go through all plugins that require this plugin again to substitue the requires
            else:
                plugin.delete()
                for requires_this_plugin in plugins:
                    fitting_plugin = requires_this_plugin.get_substitution_plugin_for(plugin)
                    requires_this_plugin.requires.add(fitting_plugin)

    delete_model.short_description = 'Delete Plugin(s)'
    install_plugin.short_description = 'Install Plugin(s)'

class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'url')
    actions = ['start_collection']

    def start_collection(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        return HttpResponseRedirect("/smartshark/collection/start/?ids=%s" % (",".join(selected)))

    start_collection.short_description = 'Start Collection for selected Projects'


admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)