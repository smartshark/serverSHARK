from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin
import tarfile
import json

from django.contrib.contenttypes.models import ContentType
from django.core.checks import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import render, render_to_response
from django.template import RequestContext

from smartshark.forms import ProjectForm
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

    def get_fields(self, request, obj=None):
        if not obj:
            return 'archive',
        else:
            return 'name', 'author', 'version', 'abstraction_level', 'archive', 'requires', 'active', 'installed'

    def get_readonly_fields(self, request, obj=None):
        if not obj:
            return 'name', 'author', 'version', 'abstraction_level', 'requires', 'active', 'installed'
        else:
            return 'name', 'author', 'version', 'abstraction_level', 'archive', 'requires', 'active', 'installed'

    def save_model(self, request, obj, form, change):
        file = tarfile.open(fileobj=request.FILES['archive'])
        plugin_description = json.loads(file.extractfile('info.json').read().decode('utf-8'))
        plugin_schema = json.loads(file.extractfile('schema.json').read().decode('utf-8'))

        plugin = Plugin()
        plugin.load_from_json(plugin_description, request.FILES['archive'])


class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'url')
    actions = ['start_collection']

    def start_collection(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        ct = ContentType.objects.get_for_model(queryset.model)
        return HttpResponseRedirect("/smartshark/collection/%s" % (",".join(selected)))

    start_collection.short_description = 'Start Collection for selected Projects'


admin.site.register(User, MyUserAdmin)
admin.site.register(SmartsharkUser, SmartsharkUserAdmin)
admin.site.register(MongoRole, MongoModelAdmin)
admin.site.register(Plugin, PluginAdmin)
admin.site.register(Argument, ArgumentAdmin)
admin.site.register(Project, ProjectAdmin)